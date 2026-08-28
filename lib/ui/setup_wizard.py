# lib/ui/setup_wizard.py
"""
First-run setup wizard (also opened from File → Settings).

Asks where the library should live -- a folder on this computer, a folder a
cloud client keeps in sync, or a service reached over the network -- and saves
the answer to the config directory (see app.paths).

The Storage tab renders itself from `app.storage.providers`, so it has no
knowledge of any individual provider and needs no edit when one is added.
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QTabWidget,
    QWidget,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

import app.settings as settings
from app import config, paths, settings_sync, srd_content
from app.storage import cloud_folders, providers

_DEFAULT_DATA_DIR = paths.config_path("data")


class SetupWizard(QDialog):
    """Settings, one tab per decision — shown on first run and from File → Settings."""

    #: (ok, message) from the Test Connection worker. A signal, not a timer:
    #: a QTimer created on a thread with no event loop never fires, and the
    #: result would be silently dropped.
    storage_test_finished = pyqtSignal(bool, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("D&D Combat Tracker — Settings")
        self.setMinimumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # One tab per decision. Storage first because it is the only one that
        # must be answered; everything else has a working default, so a
        # first-run user can fill in one tab and press Save.
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        storage_page = QWidget()
        storage = QVBoxLayout(storage_page)
        storage.setSpacing(12)
        self.tabs.addTab(storage_page, "Storage")
        self._build_storage_page(storage)

        # --- Included content ---
        content_page = QWidget()
        content = QVBoxLayout(content_page)
        content.setSpacing(12)
        self._build_content_box(content)
        content.addStretch()
        if self.content_box is not None:
            self.tabs.addTab(content_page, "Content")

        # --- Updates ---
        updates_page = QWidget()
        updates = QVBoxLayout(updates_page)
        updates.setSpacing(12)
        self._build_updates_box(updates)
        updates.addStretch()
        self.tabs.addTab(updates_page, "Updates")

        # --- Sync ---
        sync_page = QWidget()
        sync = QVBoxLayout(sync_page)
        sync.setSpacing(12)
        self._build_sync_box(sync)
        sync.addStretch()
        self.tabs.addTab(sync_page, "Sync")

        # --- Foundry VTT ---
        # Last, deliberately: it is the only optional integration here, and
        # most people do not run Foundry. Leading with it would put a bridge
        # URL and a shared secret in front of users who need neither.
        foundry_page = QWidget()
        foundry = QVBoxLayout(foundry_page)
        foundry.setSpacing(12)
        self._build_bridge_box(foundry)
        foundry.addStretch()
        self.tabs.addTab(foundry_page, "Foundry VTT")

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setDefault(True)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        self._prefill()
        self._prefill_bridge()
        self._prefill_updates()
        self._refresh_sync_status()

    def _build_storage_page(self, root) -> None:
        """The provider picker and the form for whichever one is chosen.

        Nothing here knows about any particular provider. The combo is filled
        from `providers.PROVIDERS` and the form is generated from the selected
        provider's `fields`, so a new backend appears in this dialog by being
        registered -- there is no branch here to forget to update, which is
        exactly how the old two-radio-button version accumulated an "API URL"
        row that was meaningless in local mode.
        """
        from app.storage import providers

        info = QLabel(
            "Where to keep your encounters, monsters, spells and magic items."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # Values typed for a provider survive switching away and back, so
        # comparing two options does not cost you the credentials you just
        # entered for the first one. Committed to settings only on Save.
        self._provider_values: dict = {}
        self._field_edits: dict = {}
        self._current_provider = ""

        self.provider_combo = QComboBox()
        for provider in providers.PROVIDERS:
            label = provider.label
            if provider.group == providers.FOLDER and provider.id != "local":
                # Say up front whether this machine actually has the service,
                # rather than letting the user pick Dropbox and then discover
                # the folder box is empty and they must go hunting.
                label += (
                    "  — detected"
                    if cloud_folders.is_detected(provider.id)
                    else "  — not found on this computer"
                )
            self.provider_combo.addItem(label, provider.id)
        root.addWidget(self.provider_combo)

        self.provider_summary = QLabel()
        self.provider_summary.setWordWrap(True)
        self.provider_summary.setStyleSheet("color: #888;")
        root.addWidget(self.provider_summary)

        self.provider_form_box = QGroupBox("Settings")
        self.provider_form = QFormLayout(self.provider_form_box)
        root.addWidget(self.provider_form_box)

        self.provider_caution = QLabel()
        self.provider_caution.setWordWrap(True)
        self.provider_caution.setStyleSheet("color: #b58900;")
        self.provider_caution.setVisible(False)
        root.addWidget(self.provider_caution)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test_storage)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, stretch=1)
        root.addLayout(test_row)

        root.addStretch()
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.storage_test_finished.connect(self._on_test_finished)

    def _build_bridge_box(self, root) -> None:
        """Foundry sync, collapsed behind a single switch.

        Everything below the checkbox is meaningless to someone who does not
        run Foundry -- a bridge URL and a shared secret invite exactly the
        "what is this and do I need it?" that keeps people from finishing
        setup. So the switch is the only thing visible until it is on.

        Inside, the local case is the one that has to be effortless: running
        the bridge here means the URL is not a question and the secret is
        generated, so the two fields stop being things to fill in and become
        things to copy across to Foundry.
        """
        box = QGroupBox("Foundry VTT")
        outer = QVBoxLayout(box)

        self.bridge_enabled_check = QCheckBox("Sync with Foundry VTT")
        self.bridge_enabled_check.setToolTip(
            "Two-way sync of initiative, HP and conditions with a Foundry game"
        )
        outer.addWidget(self.bridge_enabled_check)

        self.bridge_details = QWidget()
        details = QVBoxLayout(self.bridge_details)
        details.setContentsMargins(18, 4, 0, 0)

        self.local_bridge_check = QCheckBox(
            "Run the bridge on this computer (Foundry is on this machine)"
        )
        self.local_bridge_check.setToolTip(
            "Starts the bridge inside this app, so there is nothing to install or host"
        )
        details.addWidget(self.local_bridge_check)

        self.bridge_lan_check = QCheckBox("Reachable from other machines on my network")
        self.bridge_lan_check.setToolTip(
            "Tick if Foundry runs on a different computer on your LAN.\n"
            "Leave off to keep the bridge private to this machine."
        )
        lan_row = QHBoxLayout()
        lan_row.setContentsMargins(18, 0, 0, 0)
        lan_row.addWidget(self.bridge_lan_check)
        details.addLayout(lan_row)

        row_url = QHBoxLayout()
        lbl_url = QLabel("Bridge URL:")
        lbl_url.setFixedWidth(95)
        self.bridge_url_edit = QLineEdit()
        self.bridge_url_edit.setPlaceholderText("http://127.0.0.1:8787")
        row_url.addWidget(lbl_url)
        row_url.addWidget(self.bridge_url_edit)
        details.addLayout(row_url)

        row_secret = QHBoxLayout()
        lbl_secret = QLabel("Shared secret:")
        lbl_secret.setFixedWidth(95)
        self.bridge_token_edit = QLineEdit()
        self.bridge_token_edit.setEchoMode(QLineEdit.Password)
        self.bridge_token_edit.setPlaceholderText("must match the Foundry module setting")
        self.bridge_copy_btn = QPushButton("Copy")
        self.bridge_copy_btn.setFixedWidth(60)
        self.bridge_copy_btn.setToolTip("Copy the secret, to paste into Foundry")
        self.bridge_copy_btn.clicked.connect(self._copy_bridge_secret)
        row_secret.addWidget(lbl_secret)
        row_secret.addWidget(self.bridge_token_edit)
        row_secret.addWidget(self.bridge_copy_btn)
        details.addLayout(row_secret)

        self.bridge_hint = QLabel()
        self.bridge_hint.setWordWrap(True)
        self.bridge_hint.setStyleSheet("color: #888; font-size: 11px;")
        details.addWidget(self.bridge_hint)

        self.bridge_stream_check = QCheckBox("Use live streaming instead of polling")
        details.addWidget(self.bridge_stream_check)

        outer.addWidget(self.bridge_details)
        self.bridge_enabled_check.toggled.connect(self.bridge_details.setVisible)
        self.local_bridge_check.toggled.connect(self._sync_bridge_mode)
        self.bridge_lan_check.toggled.connect(self._sync_bridge_mode)
        self.bridge_details.setVisible(False)

        root.addWidget(box)

    def _sync_bridge_mode(self) -> None:
        """Reshape the bridge fields around who is hosting it.

        Local: the URL is ours to state rather than the user's to supply, and
        the secret is something they need to read and copy -- so it is shown,
        not masked. Remote: both are credentials for someone else's service,
        typed in and hidden again.
        """
        local = self.local_bridge_check.isChecked()
        self.bridge_lan_check.setVisible(local)

        if local:
            from app.config import ensure_bridge_secret, local_bridge_port

            # Generating on tick rather than on save is what makes the Copy
            # button meaningful now, while the Foundry instructions are on
            # screen, instead of only after a save-and-reopen.
            if not self.bridge_token_edit.text().strip():
                self.bridge_token_edit.setText(ensure_bridge_secret())
            self.bridge_url_edit.setText(f"http://127.0.0.1:{local_bridge_port()}")
            self.bridge_url_edit.setReadOnly(True)
            self.bridge_url_edit.setEnabled(False)
            self.bridge_token_edit.setEchoMode(QLineEdit.Normal)
            self.bridge_token_edit.setReadOnly(True)
            self.bridge_copy_btn.setVisible(True)
            port = local_bridge_port()
            extra = ""
            if self.bridge_lan_check.isChecked():
                # Foundry on another machine cannot reach our loopback, so the
                # address it needs is this machine's on the LAN. Look it up
                # rather than asking the user to go and find it.
                from app.local_bridge_server import lan_address

                found = lan_address()
                where = f"http://{found or 'this-computer'}:{port}"
                if not found:
                    extra = (
                        "  Replace <i>this-computer</i> with this machine's "
                        "network address.<br>"
                    )
            else:
                where = f"http://127.0.0.1:{port}"
            self.bridge_hint.setText(
                "In Foundry: <b>Game Settings → Configure Settings → "
                "D&amp;D Combat Tracker Bridge</b>, and enter:<br>"
                f"&nbsp;&nbsp;<b>Bridge URL:</b> {where}<br>"
                f"&nbsp;&nbsp;<b>Bridge shared secret:</b> the value above "
                "(<i>Copy</i>)<br>" + extra
            )
        else:
            self.bridge_url_edit.setReadOnly(False)
            self.bridge_url_edit.setEnabled(True)
            self.bridge_token_edit.setEchoMode(QLineEdit.Password)
            self.bridge_token_edit.setReadOnly(False)
            self.bridge_copy_btn.setVisible(False)
            self.bridge_hint.setText(
                "The bridge runs elsewhere; enter its address and secret. "
                "See docs/foundry-setup.md."
            )

    def _copy_bridge_secret(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(self.bridge_token_edit.text())
        self.bridge_copy_btn.setText("Copied")
        from PyQt5.QtCore import QTimer

        QTimer.singleShot(1200, lambda: self.bridge_copy_btn.setText("Copy"))

    def _prefill_bridge(self) -> None:
        from app.config import (
            bridge_flag,
            bridge_stream_enabled,
            bridge_value,
            foundry_bridge_enabled,
        )
        enabled = foundry_bridge_enabled()
        self.bridge_enabled_check.setChecked(enabled)
        self.bridge_details.setVisible(enabled)
        self.bridge_url_edit.setText(bridge_value("BRIDGE_URL", ""))
        self.bridge_token_edit.setText(bridge_value("BRIDGE_TOKEN", ""))
        self.local_bridge_check.setChecked(bridge_flag("LOCAL_BRIDGE_ENABLED", False))
        self.bridge_lan_check.setChecked(bridge_flag("LOCAL_BRIDGE_LAN", False))
        self.bridge_stream_check.setChecked(bridge_stream_enabled())
        self._sync_bridge_mode()

    def _bridge_changes(self) -> dict:
        enabled = self.bridge_enabled_check.isChecked()
        changes = {"foundry_bridge_enabled": enabled}
        if not enabled:
            return changes
        token = self.bridge_token_edit.text().strip()
        local = self.local_bridge_check.isChecked()
        if local and not token:
            # Belt and braces: the box is filled in on tick, but a settings
            # file hand-edited to local-with-no-secret would otherwise start a
            # bridge the app itself could not authenticate against.
            from app.config import ensure_bridge_secret

            token = ensure_bridge_secret()
        changes.update({
            "bridge_url": self.bridge_url_edit.text().strip(),
            "bridge_token": token,
            # The ingest secret has always defaulted to the token; keeping them
            # in step means one field to fill in instead of two identical ones.
            "bridge_ingest_secret": token,
            "local_bridge_enabled": local,
            "local_bridge_lan": local and self.bridge_lan_check.isChecked(),
            "bridge_stream_enabled": self.bridge_stream_check.isChecked(),
        })
        return changes

    def _build_sync_box(self, root) -> None:
        """Push/pull the portable half of settings.json through storage."""
        group = QGroupBox("Settings on other machines")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        blurb = QLabel(
            "Your layout, colours, shortcuts and toolbar can travel with you. "
            "They are stored wherever your encounters are — the API if you use "
            "one, otherwise your data folder, which works if that folder is "
            "itself synced."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self.sync_status = QLabel()
        self.sync_status.setWordWrap(True)
        layout.addWidget(self.sync_status)

        row = QHBoxLayout()
        self.sync_push_btn = QPushButton("Push From This Machine")
        self.sync_push_btn.setToolTip(
            "Overwrite the stored settings with this machine's"
        )
        self.sync_push_btn.clicked.connect(self._on_sync_push)
        self.sync_pull_btn = QPushButton("Pull To This Machine")
        self.sync_pull_btn.setToolTip(
            "Replace this machine's preferences with the stored ones"
        )
        self.sync_pull_btn.clicked.connect(self._on_sync_pull)
        row.addWidget(self.sync_push_btn)
        row.addWidget(self.sync_pull_btn)
        row.addStretch()
        layout.addLayout(row)

        excluded = QLabel(
            "Stays on this machine:\n"
            + "\n".join(f"  • {what} — {why}" for what, why in settings_sync.NOT_SYNCED)
        )
        excluded.setWordWrap(True)
        excluded.setStyleSheet("color: #888;")
        layout.addWidget(excluded)

        root.addWidget(group)

    def _sync_storage(self):
        """The backend to sync through, or None with the reason shown."""
        tracker = self.parent()
        storage = getattr(tracker, "storage", None)
        if storage is not None:
            return storage
        try:
            provider_id = config.get_storage_provider()
            return providers.build(provider_id, config.get_storage_config(provider_id))
        except Exception:
            return None

    def _refresh_sync_status(self) -> None:
        storage = self._sync_storage()
        if storage is None:
            self.sync_status.setText("Storage is not configured yet.")
            self.sync_push_btn.setEnabled(False)
            self.sync_pull_btn.setEnabled(False)
            return

        payload = settings_sync.fetch(storage)
        text = settings_sync.describe(payload)
        changed = settings_sync.differences(payload)
        if payload is not None:
            text += (
                f"\n{len(changed)} would change here: {', '.join(sorted(changed))}"
                if changed
                else "\nIdentical to this machine."
            )
        self.sync_status.setText(text)
        self.sync_push_btn.setEnabled(True)
        self.sync_pull_btn.setEnabled(payload is not None)

    def _on_sync_push(self) -> None:
        storage = self._sync_storage()
        if storage is None:
            return
        try:
            settings_sync.push(storage)
        except Exception as exc:
            QMessageBox.warning(self, "Sync", f"Could not push settings:\n{exc}")
            return
        self._refresh_sync_status()
        QMessageBox.information(
            self, "Sync", "This machine's preferences are now the stored ones."
        )

    def _on_sync_pull(self) -> None:
        storage = self._sync_storage()
        if storage is None:
            return

        changed = settings_sync.differences(settings_sync.fetch(storage))
        if changed and QMessageBox.question(
            self,
            "Pull Settings",
            "Replace this machine's "
            + ", ".join(sorted(changed))
            + " with the stored ones?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        try:
            payload = settings_sync.pull(storage)
        except Exception as exc:
            QMessageBox.warning(self, "Sync", f"Could not pull settings:\n{exc}")
            return
        if payload is None:
            QMessageBox.information(self, "Sync", "There is nothing stored to pull.")
            return

        self._refresh_sync_status()
        tracker = self.parent()
        if tracker is not None and hasattr(tracker, "apply_synced_settings"):
            tracker.apply_synced_settings()

    def _build_updates_box(self, root) -> None:
        box = QGroupBox("Updates")
        layout = QVBoxLayout(box)

        self.update_check_box = QCheckBox("Tell me when a new version is available")
        layout.addWidget(self.update_check_box)

        note = QLabel(
            "Checks GitHub for the latest release when the app starts. It never "
            "downloads or installs anything -- if the version you have works, "
            "keep it. Help -> Release Notes lists what changed in each version."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(note)

        root.addWidget(box)

    def _prefill_updates(self) -> None:
        from app.config import update_check_enabled
        self.update_check_box.setChecked(update_check_enabled())

    def _build_content_box(self, root) -> None:
        """Offer to install the bundled SRD library into the chosen backend.

        Hidden entirely when this build has no payload -- a source checkout
        without srd_content/ is a normal state, not a misconfiguration.
        """
        self.content_box = None
        if not srd_content.is_available():
            return

        counts = srd_content.counts()
        self.content_box = QGroupBox("Included Content")
        layout = QVBoxLayout(self.content_box)

        blurb = QLabel(
            "This app ships with the D&D System Reference Document 5.2.1. "
            "Installing it gives you a starting library you can edit, add to, "
            "or delete."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self.install_statblocks = QCheckBox(f"Monsters ({counts.get('statblocks', 0)})")
        self.install_spells = QCheckBox(f"Spells ({counts.get('spells', 0)})")
        self.install_items = QCheckBox(f"Magic items ({counts.get('items', 0)})")
        for box in (self.install_statblocks, self.install_spells, self.install_items):
            box.setChecked(True)
            layout.addWidget(box)

        previous = settings.get("srd_installed") or {}
        if previous:
            note = QLabel(
                f"Already installed to {previous.get('destination', 'your library')}. "
                "Re-running adds anything missing and leaves your edits alone."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #888;")
            layout.addWidget(note)
            self.install_statblocks.setChecked(False)
            self.install_spells.setChecked(False)
            self.install_items.setChecked(False)

        licence = QLabel(
            "SRD 5.2.1 by Wizards of the Coast LLC, used under CC-BY-4.0. "
            "See LICENSE-SRD.md."
        )
        licence.setWordWrap(True)
        licence.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(licence)

        root.addWidget(self.content_box)

    def _selected_categories(self) -> list:
        if self.content_box is None:
            return []
        chosen = []
        if self.install_statblocks.isChecked():
            chosen.append("statblocks")
        if self.install_spells.isChecked():
            chosen.append("spells")
        if self.install_items.isChecked():
            chosen.append("items")
        return chosen

    def _storage_for(self, provider_id: str, values: dict):
        """Build the backend the user just configured, for the install step."""
        try:
            backend = providers.build(provider_id, values)
            return backend, backend.describe()
        except Exception as exc:
            QMessageBox.warning(
                self, "Storage", f"Could not open your storage:\n{exc}"
            )
            return None, ""

    def _install_content(self, provider_id: str, values: dict) -> None:
        categories = self._selected_categories()
        if not categories:
            return
        storage, destination = self._storage_for(provider_id, values)
        if storage is None:
            return

        from ui.content_install_dialog import run_install

        result = run_install(self, storage, categories, destination)
        if result is not None and result.installed:
            from app.content_installer import install_marker
            settings.set("srd_installed", install_marker(result, destination))

    # ---- slots ----

    def _on_provider_changed(self, _index: int = 0) -> None:
        self._remember_fields()
        self._rebuild_provider_form()

    def _remember_fields(self) -> None:
        """Stash what is typed for the provider currently on screen."""
        if not self._current_provider:
            return
        self._provider_values[self._current_provider] = {
            key: edit.text() for key, edit in self._field_edits.items()
        }

    def _selected_provider_id(self) -> str:
        return self.provider_combo.currentData() or providers.DEFAULT_PROVIDER_ID

    def _rebuild_provider_form(self) -> None:
        while self.provider_form.count():
            item = self.provider_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

        self._field_edits = {}
        provider_id = self._selected_provider_id()
        self._current_provider = provider_id
        provider = providers.get(provider_id)
        if provider is None:
            return

        self.provider_summary.setText(provider.summary)
        self.provider_caution.setText(provider.caution)
        self.provider_caution.setVisible(bool(provider.caution))
        self.test_result.setText("")

        values = self._provider_values.get(provider_id)
        if values is None:
            values = config.get_storage_config(provider_id)
            self._provider_values[provider_id] = dict(values)

        for spec in provider.fields:
            edit = QLineEdit(str(values.get(spec.key, "") or ""))
            if spec.kind == "password":
                edit.setEchoMode(QLineEdit.Password)
            edit.setPlaceholderText(
                spec.placeholder or self._placeholder_for(provider_id, spec)
            )
            if spec.help:
                edit.setToolTip(spec.help)
            self._field_edits[spec.key] = edit

            if spec.kind == "folder":
                row = QHBoxLayout()
                row.addWidget(edit)
                browse = QPushButton("Browse…")
                browse.setFixedWidth(80)
                browse.clicked.connect(lambda _c, e=edit: self._browse_into(e))
                row.addWidget(browse)
                self.provider_form.addRow(f"{spec.label}:", row)
            else:
                self.provider_form.addRow(f"{spec.label}:", edit)

            if spec.help:
                hint = QLabel(spec.help)
                hint.setWordWrap(True)
                hint.setStyleSheet("color: #888; font-size: 11px;")
                self.provider_form.addRow("", hint)

        self.provider_form_box.setVisible(bool(provider.fields))

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @staticmethod
    def _placeholder_for(provider_id: str, spec) -> str:
        """For a folder field, show where it would go if left blank."""
        if spec.kind != "folder":
            return ""
        if provider_id == "local":
            return _DEFAULT_DATA_DIR
        suggested = cloud_folders.suggested_path(provider_id)
        return suggested or "choose a folder"

    def _current_field_values(self) -> dict:
        return {key: edit.text().strip() for key, edit in self._field_edits.items()}

    def _browse_into(self, edit) -> None:
        start = edit.text().strip() or edit.placeholderText() or _DEFAULT_DATA_DIR
        chosen = QFileDialog.getExistingDirectory(self, "Select Folder", start)
        if chosen:
            edit.setText(chosen)

    def _on_test_storage(self) -> None:
        """Try the current settings without committing them.

        On a worker thread: a WebDAV server that is down takes the full connect
        timeout to say so, and blocking the settings dialog for that long makes
        the app look hung at the exact moment the user is trying to fix it.
        """
        provider_id = self._selected_provider_id()
        values = self._current_field_values()
        missing = providers.missing_fields(provider_id, values)
        if missing:
            self.test_result.setText(f"Fill in: {', '.join(missing)}")
            return

        self.test_btn.setEnabled(False)
        self.test_result.setText("Testing…")

        def run() -> None:
            try:
                backend = providers.build(provider_id, values)
                self.storage_test_finished.emit(True, backend.check())
            except Exception as exc:
                self.storage_test_finished.emit(False, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_result.setStyleSheet("color: #2aa198;" if ok else "color: #dc322f;")
        self.test_result.setText(message)

    def _prefill(self) -> None:
        """Select the configured provider and draw its form.

        `config.get_storage_provider()` understands the pre-provider settings
        and the environment variables behind them, so an install that has only
        ever known "Remote API Server" opens here on "HTTP server" with its URL
        and key already filled in.
        """
        provider_id = config.get_storage_provider()
        index = self.provider_combo.findData(provider_id)
        if index < 0:
            index = self.provider_combo.findData(providers.DEFAULT_PROVIDER_ID)
        self.provider_combo.setCurrentIndex(max(index, 0))
        self._rebuild_provider_form()

    def _on_save(self) -> None:
        provider_id = self._selected_provider_id()
        values = self._current_field_values()

        missing = providers.missing_fields(provider_id, values)
        if missing:
            QMessageBox.warning(
                self,
                "Missing Settings",
                f"{providers.label(provider_id)} needs: {', '.join(missing)}.",
            )
            return

        before = (config.get_storage_provider(), config.get_storage_config())

        # Merge, never replace. settings.save() writes the dict it is given
        # wholesale, so passing only these keys wiped panel_layout, the
        # toolbar, the palette, the active PC group and the bridge settings
        # every time this dialog was used from File -> Settings.
        merged = dict(settings.load())
        stored = dict(merged.get(config.CONFIG_KEY) or {})
        # Every provider's fields, not just the active one, so credentials
        # typed while comparing options are not lost on save. Providers that
        # were only looked at are skipped, so browsing the list does not
        # litter settings.json with eight empty stanzas.
        self._remember_fields()
        for pid, pvalues in self._provider_values.items():
            cleaned = {k: str(v).strip() for k, v in pvalues.items()}
            if any(cleaned.values()) or pid in stored:
                stored[pid] = cleaned
        stored[provider_id] = values
        merged[config.PROVIDER_KEY] = provider_id
        merged[config.CONFIG_KEY] = stored
        merged.update(self._bridge_changes())
        merged["update_check_enabled"] = self.update_check_box.isChecked()
        settings.save(merged)

        self._install_content(provider_id, values)

        # Bridge changes take effect immediately; a storage change cannot,
        # because the backend is wired up at construction and referenced all
        # over the app. Say which one happened rather than making the user
        # guess whether anything took.
        parent = self.parent()
        if parent is not None and hasattr(parent, "apply_settings_changes"):
            parent.apply_settings_changes()

        storage_changed = before != (provider_id, values)
        self.accept()

        # After accept(), so the offer to restart isn't stacked on top of a
        # dialog the user has to dismiss first.
        if storage_changed and parent is not None and hasattr(parent, "prompt_restart"):
            parent.prompt_restart("Storage settings")
