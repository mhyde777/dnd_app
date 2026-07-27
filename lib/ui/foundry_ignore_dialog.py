# lib/ui/foundry_ignore_dialog.py
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QMessageBox, QGroupBox, QCheckBox,
)


class FoundryIgnoreDialog(QDialog):
    """Manage which Foundry combatants are kept out of the tracker.

    Two ways in: pick something out of the live combat (precise — it ignores
    that actor by id), or type a name pattern that survives across sessions
    (e.g. "Eldritch Cannon", "*Echo", "Summon*").
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.setWindowTitle("Foundry Sync — Ignore List")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Ignored combatants are dropped from every Foundry snapshot: they are\n"
            "never added to initiative and never sync HP or conditions."
        ))

        self.summons_check = QCheckBox(
            "Ignore player-owned NPCs (summons, familiars, companions)"
        )
        self.summons_check.setToolTip(
            "Foundry actors of type 'npc' that a player owns. PCs are type "
            "'character' and monsters aren't player-owned, so this catches "
            "summons and effect tokens only."
        )
        self.summons_check.setChecked(self.app.ignore_player_owned_npcs)
        self.summons_check.toggled.connect(self.on_toggle_summons)
        layout.addWidget(self.summons_check)

        # --- Live combat ---
        live_box = QGroupBox("In the current Foundry combat")
        live_layout = QVBoxLayout(live_box)
        self.live_list = QListWidget()
        self.live_list.setSelectionMode(QListWidget.ExtendedSelection)
        live_layout.addWidget(self.live_list)
        live_row = QHBoxLayout()
        self.ignore_btn = QPushButton("Ignore Selected")
        self.ignore_btn.clicked.connect(self.on_ignore_selected)
        live_row.addWidget(self.ignore_btn)
        live_row.addStretch(1)
        live_layout.addLayout(live_row)
        layout.addWidget(live_box)

        # --- Ignore list ---
        rules_box = QGroupBox("Ignore rules")
        rules_layout = QVBoxLayout(rules_box)
        self.rules_list = QListWidget()
        self.rules_list.setSelectionMode(QListWidget.ExtendedSelection)
        rules_layout.addWidget(self.rules_list)

        add_row = QHBoxLayout()
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("Name or pattern, e.g. Eldritch Cannon or *Echo")
        self.pattern_edit.returnPressed.connect(self.on_add_pattern)
        add_row.addWidget(self.pattern_edit, 1)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self.on_add_pattern)
        add_row.addWidget(self.add_btn)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.on_remove)
        add_row.addWidget(self.remove_btn)
        rules_layout.addLayout(add_row)
        layout.addWidget(rules_box)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        close_row.addWidget(self.close_btn)
        layout.addLayout(close_row)

        self._populate_rules()
        self._populate_live()

    # -------- population --------
    def _populate_rules(self):
        self.rules_list.clear()
        for pattern in self.app.foundry_ignore_patterns:
            item = QListWidgetItem(f"name:  {pattern}")
            item.setData(Qt.UserRole, ("pattern", pattern))
            self.rules_list.addItem(item)
        for actor_id in self.app.foundry_ignore_actor_ids:
            item = QListWidgetItem(f"actor: {self._actor_label(actor_id)}")
            item.setData(Qt.UserRole, ("actor_id", actor_id))
            self.rules_list.addItem(item)
        if self.rules_list.count() == 0:
            item = QListWidgetItem("(nothing ignored)")
            item.setFlags(Qt.NoItemFlags)
            self.rules_list.addItem(item)

    def _actor_label(self, actor_id: str) -> str:
        """Show the last known name for an ignored actor id, not just the id."""
        for combatant in self._snapshot_combatants(include_ignored=True):
            if str(combatant.get("actorId")) == str(actor_id):
                return f"{combatant.get('name')}  ({actor_id})"
        return actor_id

    def _snapshot_combatants(self, include_ignored: bool = False):
        snapshot = getattr(self.app, "bridge_snapshot", None) or {}
        rows = snapshot.get("combatants", [])
        if not isinstance(rows, list):
            return []
        if include_ignored:
            # bridge_snapshot is already filtered; re-read the raw feed for names.
            raw = getattr(self.app, "_last_raw_combatants", None)
            if isinstance(raw, list):
                return raw
        return rows

    def _populate_live(self):
        self.live_list.clear()
        rows = self._snapshot_combatants(include_ignored=True)
        if not rows:
            item = QListWidgetItem("(no Foundry combat data — is the bridge connected?)")
            item.setFlags(Qt.NoItemFlags)
            self.live_list.addItem(item)
            return
        for combatant in rows:
            name = (combatant.get("name") or "").strip() or "(unnamed)"
            reason = self.app.combatant_ignore_reason(combatant)
            actor_type = combatant.get("actorType") or "?"
            label = f"{name}   [{actor_type}]"
            if reason:
                label += f"   — ignored ({reason})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, combatant)
            if reason:
                item.setForeground(Qt.gray)
            self.live_list.addItem(item)

    # -------- actions --------
    def on_ignore_selected(self):
        combatants = [
            item.data(Qt.UserRole) for item in self.live_list.selectedItems()
            if isinstance(item.data(Qt.UserRole), dict)
        ]
        if not combatants:
            QMessageBox.information(self, "No Selection", "Select one or more combatants to ignore.")
            return
        for combatant in combatants:
            actor_id = combatant.get("actorId")
            if actor_id:
                self.app.add_foundry_ignore(actor_id=str(actor_id))
            else:
                name = (combatant.get("name") or "").strip()
                if name:
                    self.app.add_foundry_ignore(pattern=name)
        self._after_change()

    def on_toggle_summons(self, checked: bool):
        self.app.set_foundry_ignore(
            self.app.foundry_ignore_patterns,
            self.app.foundry_ignore_actor_ids,
            player_owned_npcs=bool(checked),
        )
        self._after_change()

    def on_add_pattern(self):
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            return
        self.app.add_foundry_ignore(pattern=pattern)
        self.pattern_edit.clear()
        self._after_change()

    def on_remove(self):
        rules = [
            item.data(Qt.UserRole) for item in self.rules_list.selectedItems()
            if isinstance(item.data(Qt.UserRole), tuple)
        ]
        if not rules:
            QMessageBox.information(self, "No Selection", "Select one or more rules to remove.")
            return
        patterns = self.app.foundry_ignore_patterns
        actor_ids = self.app.foundry_ignore_actor_ids
        for kind, value in rules:
            if kind == "pattern" and value in patterns:
                patterns.remove(value)
            elif kind == "actor_id" and value in actor_ids:
                actor_ids.remove(value)
        self.app.set_foundry_ignore(patterns, actor_ids)
        self._after_change()

    def _after_change(self):
        """Apply the new rules right away: drop anything now ignored."""
        removed = self.app.prune_ignored_creatures()
        if removed and hasattr(self.app, "show_status_message"):
            self.app.show_status_message(
                f"Removed from initiative: {', '.join(removed)}"
            )
        self._populate_rules()
        self._populate_live()
