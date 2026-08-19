# lib/ui/color_settings_dialog.py
"""
Let the user pick every colour the app uses.

The shipped values are the defaults, so anyone who doesn't care sees exactly
what they saw before. The dialog is generated from `ui.colors.PALETTE_SCHEMA` —
adding a colour there is enough to make it editable here.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ui import colors


class ColorSwatch(QPushButton):
    """A button whose face *is* the colour, opening a picker when clicked."""

    def __init__(self, key: str, value: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self._value = value
        self.setFixedSize(64, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        self._refresh()

    def _refresh(self) -> None:
        # A visible border keeps a swatch legible when it matches the backdrop.
        self.setStyleSheet(
            f"background-color: {self._value};"
            " border: 1px solid #6a6a7a;"
            " border-radius: 3px;"
        )
        self.setToolTip(self._value)

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._value), self, "Choose Colour"
        )
        if chosen.isValid():
            self.set_value(chosen.name())
            parent = self.window()
            preview = getattr(parent, "preview", None)
            if callable(preview):
                preview()


class ColorSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Colors")
        self.setMinimumSize(520, 620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._tracker = parent
        self._original = colors.load()
        self._original_tint = colors.tint_action_cells()

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Click a swatch to change it. Changes preview immediately; "
            "Cancel puts everything back."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Scrolled: the palette is longer than any sensible dialog height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 8, 0)
        container_layout.setSpacing(10)

        self._swatches: dict[str, ColorSwatch] = {}

        for group_name, entries in colors.PALETTE_SCHEMA:
            group = QGroupBox(group_name)
            grid = QGridLayout(group)
            grid.setColumnStretch(0, 1)
            grid.setSpacing(6)

            for row, (key, label, _default, tooltip) in enumerate(entries):
                name_label = QLabel(label)
                if tooltip:
                    name_label.setToolTip(tooltip)
                grid.addWidget(name_label, row, 0)

                swatch = ColorSwatch(key, self._original[key])
                if tooltip:
                    swatch.setToolTip(f"{tooltip}\n{self._original[key]}")
                self._swatches[key] = swatch
                grid.addWidget(swatch, row, 1)

                reset = QPushButton("Reset")
                # Fixed-width clipped the label once button padding was applied.
                reset.setMinimumWidth(72)
                reset.setToolTip(f"Back to the default ({_default})")
                reset.clicked.connect(
                    lambda _checked, k=key, d=_default: self._reset_one(k, d)
                )
                grid.addWidget(reset, row, 2)

            container_layout.addWidget(group)

            # The action-tracker tint is only meaningful alongside its colours.
            if group_name == "Action Tracker":
                self.tint_checkbox = QCheckBox(
                    "Tint the background of action / bonus / reaction cells"
                )
                self.tint_checkbox.setChecked(self._original_tint)
                self.tint_checkbox.setToolTip(
                    "Off: only the ✔ / ✘ marks are coloured, so the active-turn "
                    "highlight runs unbroken across the row."
                )
                self.tint_checkbox.toggled.connect(self.preview)
                container_layout.addWidget(self.tint_checkbox)

        container_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, stretch=1)

        bottom = QHBoxLayout()
        restore = QPushButton("Restore All Defaults")
        restore.clicked.connect(self._restore_defaults)
        bottom.addWidget(restore)
        bottom.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self._on_cancel)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

    # ---- internal ----

    def current_palette(self) -> dict[str, str]:
        return {key: swatch.value() for key, swatch in self._swatches.items()}

    def preview(self, *_args) -> None:
        colors.apply(self.current_palette())
        colors.set_tint_action_cells(self.tint_checkbox.isChecked())
        repaint = getattr(self._tracker, "refresh_theme", None)
        if callable(repaint):
            repaint()

    def _reset_one(self, key: str, default: str) -> None:
        self._swatches[key].set_value(default)
        self.preview()

    def _restore_defaults(self) -> None:
        for key, swatch in self._swatches.items():
            swatch.set_value(colors.DEFAULTS[key])
        self.tint_checkbox.setChecked(colors.TINT_ACTION_CELLS_DEFAULT)
        self.preview()

    def _on_save(self) -> None:
        palette = self.current_palette()
        colors.save(palette)
        colors.set_tint_action_cells(self.tint_checkbox.isChecked())
        colors.apply(palette)
        repaint = getattr(self._tracker, "refresh_theme", None)
        if callable(repaint):
            repaint()
        self.accept()

    def _on_cancel(self) -> None:
        colors.apply(self._original)
        colors.set_tint_action_cells(self._original_tint)
        repaint = getattr(self._tracker, "refresh_theme", None)
        if callable(repaint):
            repaint()
        self.reject()
