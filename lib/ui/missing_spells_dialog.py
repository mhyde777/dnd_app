# ui/missing_spells_dialog.py
"""
MissingSpellsDialog — shown after a statblock is saved when some of its
spells are not yet in the spell library.

Usage:
    dlg = MissingSpellsDialog(missing=["fireball", "shield"], storage_api=api, parent=self)
    dlg.exec_()   # result doesn't matter — spells are saved inline
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
)


class MissingSpellsDialog(QDialog):
    """
    Lists spell names that are not yet in the storage library and lets
    the user import them one at a time.
    """

    def __init__(
        self,
        missing: list[str],
        storage_api=None,
        parent=None,
    ):
        super().__init__(parent)
        self.storage_api = storage_api
        self._missing = list(missing)          # original names, e.g. ["Fireball", "Shield"]
        self._row_widgets: dict[str, dict] = {}  # name → {status_label, import_btn}

        self.setWindowTitle("Missing Spells")
        self.resize(420, min(120 + len(missing) * 48, 520))
        self.setMinimumWidth(360)

        self._build_ui()

    # ── Layout ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        count = len(self._missing)
        intro = QLabel(
            f"<b>{count} spell{'s' if count != 1 else ''}</b> in this statblock "
            f"{'are' if count != 1 else 'is'} not in your spell library.<br>"
            "Import them now, or close to skip."
        )
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(intro)

        # Scroll area for the spell list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.StyledPanel)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(6, 6, 6, 6)

        for spell_name in self._missing:
            row = self._make_spell_row(spell_name)
            inner_layout.addWidget(row)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _make_spell_row(self, spell_name: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        name_lbl = QLabel(spell_name)
        name_lbl.setMinimumWidth(160)
        row.addWidget(name_lbl, stretch=1)

        status_lbl = QLabel("")
        status_lbl.setStyleSheet("color: #2d862d; font-style: italic;")
        status_lbl.hide()
        row.addWidget(status_lbl)

        import_btn = QPushButton("Import…")
        import_btn.setFixedWidth(80)
        row.addWidget(import_btn)

        self._row_widgets[spell_name] = {
            "status_label": status_lbl,
            "import_btn":   import_btn,
        }

        import_btn.clicked.connect(lambda checked=False, n=spell_name: self._import_spell(n))
        return container

    # ── Import flow ───────────────────────────────────────────────────

    def _import_spell(self, spell_name: str) -> None:
        from ui.spell_import_dialog import SpellImportDialog

        dlg = SpellImportDialog(
            storage_api=self.storage_api,
            spell_name=spell_name,
            parent=self,
        )
        if dlg.exec_() == SpellImportDialog.Accepted:
            widgets = self._row_widgets.get(spell_name, {})
            status_lbl: Optional[QLabel] = widgets.get("status_label")
            import_btn: Optional[QPushButton] = widgets.get("import_btn")
            if status_lbl:
                status_lbl.setText("Imported")
                status_lbl.show()
            if import_btn:
                import_btn.setEnabled(False)
                import_btn.setText("Done")
