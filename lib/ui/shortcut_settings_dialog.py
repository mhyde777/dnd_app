# lib/ui/shortcut_settings_dialog.py
"""
User-rebindable keyboard shortcuts.

The shipped sequences in SHORTCUT_SCHEMA *are* the defaults; settings.json
stores only what the user changed, so a future default can still reach people
who never touched that binding.

Adding a shortcut means adding it here and to `_shortcut_targets` in
lib/ui/ui.py -- the ids must match, the same contract the toolbar registry
uses. It then appears in this dialog and in Help -> Keyboard Shortcuts with no
further work.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import app.settings as settings

_SETTINGS_KEY = "shortcuts"

# ---- Registry ---------------------------------------------------------------
# (group, [(id, label, default sequence, tooltip), ...])
SHORTCUT_SCHEMA: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("Combat", [
        ("next_turn",     "Next turn",      "Ctrl+N",       "Advance the initiative order"),
        ("prev_turn",     "Previous turn",  "Ctrl+Shift+N", "Step back one turn"),
        ("focus_filter",  "Focus combatant filter", "Ctrl+F",
         "Jump to the filter box above the combatant list"),
    ]),
    ("Encounters", [
        ("save_state",    "Save state",     "Ctrl+S", "Write the current combat to disk"),
    ]),
    ("Content", [
        ("reference_lookup", "Reference lookup", "Ctrl+L",
         "Open the spell / monster / item reference"),
    ]),
    ("Statblock", [
        ("statblock_zoom_in",    "Zoom in",    "Ctrl++",
         "Ctrl+= does the same thing while this is at its default, since + needs Shift"),
        ("statblock_zoom_out",   "Zoom out",   "Ctrl+-", "Shrink the statblock text"),
        ("statblock_zoom_reset", "Reset zoom", "Ctrl+0", "Back to the original size"),
    ]),
    ("App", [
        ("show_shortcuts", "Keyboard shortcuts", "F1", "This list of shortcuts"),
    ]),
]

# Shortcuts that aren't rebindable, shown in the help dialog for completeness.
FIXED_SHORTCUTS: list[tuple[str, str]] = [
    ("Enter",       "Damage selected (in an HP value box)"),
    ("Shift+Enter", "Heal selected (in an HP value box)"),
    ("Shift+Click", "Select a run of combatants in the list"),
    ("Ctrl+Scroll", "Zoom the statblock"),
    ("Esc",         "Clear selection / close dropdowns"),
]

# Ctrl+= is the same physical key as Ctrl++ without Shift. It rides along with
# the zoom-in binding, but only while that binding is still the default -- once
# someone picks their own key, a stray alias would be a surprise.
ZOOM_IN_ALIAS = "Ctrl+="

_ENTRIES: list[tuple[str, str, str, str]] = [
    entry for _group, entries in SHORTCUT_SCHEMA for entry in entries
]
_DEFAULTS: dict[str, str] = {key: default for key, _label, default, _tip in _ENTRIES}
_LABELS: dict[str, str] = {key: label for key, label, _default, _tip in _ENTRIES}
_VALID_IDS: set[str] = set(_DEFAULTS)


# ---- Persistence helpers ----------------------------------------------------

def defaults() -> dict[str, str]:
    return dict(_DEFAULTS)


def label_for(key: str) -> str:
    return _LABELS.get(key, key)


def load() -> dict[str, str]:
    """Every binding, defaults filled in and unknown ids dropped.

    An empty string is a real value -- it means the user unbound the shortcut.
    """
    resolved = dict(_DEFAULTS)
    saved = settings.get(_SETTINGS_KEY) or {}
    if isinstance(saved, dict):
        for key, sequence in saved.items():
            if key in _VALID_IDS and isinstance(sequence, str):
                resolved[key] = sequence
    return resolved


def save(mapping: dict[str, str]) -> None:
    """Persist only what differs from the defaults."""
    overrides = {
        key: sequence
        for key, sequence in mapping.items()
        if key in _VALID_IDS and sequence != _DEFAULTS[key]
    }
    data = dict(settings.load())
    if overrides:
        data[_SETTINGS_KEY] = overrides
    else:
        data.pop(_SETTINGS_KEY, None)
    settings.save(data)


def conflicts(mapping: dict[str, str]) -> dict[str, list[str]]:
    """Sequences bound to more than one action, as {sequence: [ids]}.

    Qt resolves a duplicate by firing neither, so this has to be caught before
    it is saved rather than debugged later as "the shortcut stopped working".
    """
    seen: dict[str, list[str]] = {}
    for key, sequence in mapping.items():
        if not sequence:
            continue
        # Compare canonically: "ctrl+n" and "Ctrl+N" are the same binding.
        canonical = QKeySequence(sequence).toString(QKeySequence.PortableText)
        if not canonical:
            continue
        seen.setdefault(canonical, []).append(key)
    return {seq: ids for seq, ids in seen.items() if len(ids) > 1}


# ---- Widgets ----------------------------------------------------------------

class ShortcutEdit(QKeySequenceEdit):
    """A key-sequence box that records one chord, not a four-chord sequence.

    QKeySequenceEdit keeps listening after the first chord and would happily
    record "Ctrl+N, Ctrl+S" as a single binding, which is not what anyone means
    to do while rebinding one key.
    """

    def __init__(self, sequence: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setKeySequence(QKeySequence(sequence))
        self.editingFinished.connect(self._truncate)
        self.keySequenceChanged.connect(self._truncate)

    def _truncate(self, *_args) -> None:
        sequence = self.keySequence()
        if sequence.count() > 1:
            # Re-entrant, but the second pass has one chord and stops here.
            self.setKeySequence(QKeySequence(sequence[0]))

    def text(self) -> str:
        return self.keySequence().toString(QKeySequence.PortableText)


class ShortcutSettingsDialog(QDialog):
    """Rebind shortcuts. Nothing is applied until Save."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Shortcuts")
        self.setMinimumSize(560, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._tracker = parent
        self._current = load()

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Click a box and press the keys you want. Clear unbinds a shortcut "
            "entirely; Reset puts one back to how it shipped."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 8, 0)
        container_layout.setSpacing(10)

        self._edits: dict[str, ShortcutEdit] = {}

        for group_name, entries in SHORTCUT_SCHEMA:
            group = QGroupBox(group_name)
            grid = QGridLayout(group)
            grid.setColumnStretch(0, 1)
            grid.setSpacing(6)

            for row, (key, label, default, tooltip) in enumerate(entries):
                name_label = QLabel(label)
                if tooltip:
                    name_label.setToolTip(tooltip)
                grid.addWidget(name_label, row, 0)

                edit = ShortcutEdit(self._current.get(key, default))
                edit.setMinimumWidth(150)
                if tooltip:
                    edit.setToolTip(tooltip)
                edit.keySequenceChanged.connect(self._revalidate)
                self._edits[key] = edit
                grid.addWidget(edit, row, 1)

                clear = QPushButton("Clear")
                clear.setMinimumWidth(64)
                clear.setToolTip("Leave this command with no shortcut")
                clear.clicked.connect(lambda _c, k=key: self._clear_one(k))
                grid.addWidget(clear, row, 2)

                reset = QPushButton("Reset")
                reset.setMinimumWidth(72)
                reset.setToolTip(f"Back to the default ({default})")
                reset.clicked.connect(
                    lambda _c, k=key, d=default: self._reset_one(k, d)
                )
                grid.addWidget(reset, row, 3)

            container_layout.addWidget(group)

        container_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, stretch=1)

        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setObjectName("shortcutConflictWarning")
        self._warning.hide()
        root.addWidget(self._warning)

        bottom = QHBoxLayout()
        restore = QPushButton("Restore All Defaults")
        restore.clicked.connect(self._restore_defaults)
        bottom.addWidget(restore)
        bottom.addStretch()

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self.reject)
        bottom.addWidget(self._buttons)
        root.addLayout(bottom)

        self._revalidate()

    # ---- helpers ------------------------------------------------------------

    def values(self) -> dict[str, str]:
        return {key: edit.text() for key, edit in self._edits.items()}

    def _clear_one(self, key: str) -> None:
        self._edits[key].clear()
        self._revalidate()

    def _reset_one(self, key: str, default: str) -> None:
        self._edits[key].setKeySequence(QKeySequence(default))
        self._revalidate()

    def _restore_defaults(self) -> None:
        for key, edit in self._edits.items():
            edit.setKeySequence(QKeySequence(_DEFAULTS[key]))
        self._revalidate()

    def _revalidate(self, *_args) -> None:
        """Block Save while two commands share a key, and say which."""
        clashes = conflicts(self.values())
        clashing_ids = {key for ids in clashes.values() for key in ids}

        for key, edit in self._edits.items():
            edit.setStyleSheet(
                "border: 1px solid #c0392b;" if key in clashing_ids else ""
            )

        if clashes:
            described = "; ".join(
                f"{sequence} → " + " and ".join(label_for(i) for i in ids)
                for sequence, ids in sorted(clashes.items())
            )
            self._warning.setText(
                f"Two commands can't share a shortcut — Qt would fire neither. {described}"
            )
            self._warning.show()
        else:
            self._warning.hide()

        self._buttons.button(QDialogButtonBox.Save).setEnabled(not clashes)

    def _on_save(self) -> None:
        save(self.values())
        tracker = self._tracker
        if tracker is not None and hasattr(tracker, "apply_shortcuts"):
            tracker.apply_shortcuts()
        self.accept()
