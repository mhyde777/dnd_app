# lib/ui/layout_settings_dialog.py
"""
Configure the window layout from a dialog rather than by dragging panels.

Dragging docks around is easy to trigger by accident and hard to undo precisely
mid-session, so the saved configuration here is the source of truth: which
panels are shown, which side each one sits on, and how wide it is. Free-form
dragging is available as an opt-in for anyone who wants it.
"""
from __future__ import annotations

from copy import deepcopy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout,
)

import app.settings as settings

_SETTING_KEY = "panel_layout"

# key, display label, default side
PANEL_REGISTRY: list[tuple[str, str, str]] = [
    ("controls", "Combat Controls", "left"),
    ("statblock", "Statblock", "right"),
]

SIDES = [("Left", "left"), ("Right", "right")]
TOOLBAR_AREAS = [("Top", "top"), ("Bottom", "bottom")]
BUTTON_STYLES = [
    ("Icon and text", "text_beside_icon"),
    ("Text only", "text_only"),
    ("Icon only", "icon_only"),
    ("Icon above text", "text_under_icon"),
]

MIN_PANEL_WIDTH = 180
MAX_PANEL_WIDTH = 1200

DEFAULT_PANEL_LAYOUT: dict = {
    # Off by default: the dialog is the intended way to change the layout.
    "allow_drag": False,
    "panels": {
        "controls": {"visible": True, "side": "left", "width": 250},
        "statblock": {"visible": True, "side": "right", "width": 420},
    },
    "toolbar": {"visible": True, "area": "top", "button_style": "text_beside_icon"},
}


def load_panel_layout() -> dict:
    """Saved layout merged over the defaults, so new keys can't KeyError."""
    saved = settings.get(_SETTING_KEY) or {}
    config = deepcopy(DEFAULT_PANEL_LAYOUT)
    if not isinstance(saved, dict):
        return config

    config["allow_drag"] = bool(saved.get("allow_drag", config["allow_drag"]))

    saved_panels = saved.get("panels") or {}
    for key, _label, _side in PANEL_REGISTRY:
        entry = config["panels"][key]
        saved_entry = saved_panels.get(key) or {}
        entry["visible"] = bool(saved_entry.get("visible", entry["visible"]))
        side = saved_entry.get("side", entry["side"])
        entry["side"] = side if side in ("left", "right") else entry["side"]
        try:
            width = int(saved_entry.get("width", entry["width"]))
        except (TypeError, ValueError):
            width = entry["width"]
        entry["width"] = max(MIN_PANEL_WIDTH, min(MAX_PANEL_WIDTH, width))

    saved_toolbar = saved.get("toolbar") or {}
    config["toolbar"]["visible"] = bool(
        saved_toolbar.get("visible", config["toolbar"]["visible"])
    )
    area = saved_toolbar.get("area", config["toolbar"]["area"])
    config["toolbar"]["area"] = area if area in ("top", "bottom") else "top"
    style = saved_toolbar.get("button_style", config["toolbar"]["button_style"])
    valid_styles = {value for _label, value in BUTTON_STYLES}
    config["toolbar"]["button_style"] = (
        style if style in valid_styles else "text_beside_icon"
    )

    return config


def save_panel_layout(config: dict) -> None:
    settings.set(_SETTING_KEY, config)


class LayoutSettingsDialog(QDialog):
    """Live-previewing layout editor: changes apply as you make them."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Layout")
        self.setMinimumWidth(440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._tracker = parent
        self._original = load_panel_layout()
        config = deepcopy(self._original)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Choose where each panel sits and how much room it gets. "
            "Changes preview immediately."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._panel_widgets: dict[str, dict] = {}
        for key, label, _default_side in PANEL_REGISTRY:
            entry = config["panels"][key]
            group = QGroupBox(label)
            form = QFormLayout(group)
            form.setSpacing(6)

            visible = QCheckBox("Show this panel")
            visible.setChecked(entry["visible"])
            form.addRow(visible)

            side = QComboBox()
            for side_label, side_value in SIDES:
                side.addItem(side_label, side_value)
            side.setCurrentIndex(max(0, side.findData(entry["side"])))
            form.addRow("Position:", side)

            width = QSpinBox()
            width.setRange(MIN_PANEL_WIDTH, MAX_PANEL_WIDTH)
            width.setSingleStep(10)
            width.setSuffix(" px")
            width.setValue(entry["width"])
            form.addRow("Width:", width)

            # Width and side are meaningless while the panel is hidden.
            def _sync_enabled(checked, _side=side, _width=width):
                _side.setEnabled(checked)
                _width.setEnabled(checked)

            _sync_enabled(entry["visible"])
            visible.toggled.connect(_sync_enabled)

            for widget, signal in (
                (visible, "toggled"), (side, "currentIndexChanged"), (width, "valueChanged")
            ):
                getattr(widget, signal).connect(self._preview)

            root.addWidget(group)
            self._panel_widgets[key] = {
                "visible": visible, "side": side, "width": width,
            }

        # --- Toolbar ---
        toolbar_group = QGroupBox("Toolbar")
        toolbar_form = QFormLayout(toolbar_group)
        toolbar_form.setSpacing(6)

        self.toolbar_visible = QCheckBox("Show the toolbar")
        self.toolbar_visible.setChecked(config["toolbar"]["visible"])
        toolbar_form.addRow(self.toolbar_visible)

        self.toolbar_area = QComboBox()
        for area_label, area_value in TOOLBAR_AREAS:
            self.toolbar_area.addItem(area_label, area_value)
        self.toolbar_area.setCurrentIndex(
            max(0, self.toolbar_area.findData(config["toolbar"]["area"]))
        )
        toolbar_form.addRow("Position:", self.toolbar_area)

        self.toolbar_button_style = QComboBox()
        for style_label, style_value in BUTTON_STYLES:
            self.toolbar_button_style.addItem(style_label, style_value)
        self.toolbar_button_style.setCurrentIndex(
            max(0, self.toolbar_button_style.findData(config["toolbar"]["button_style"]))
        )
        self.toolbar_button_style.currentIndexChanged.connect(self._preview)
        self.toolbar_visible.toggled.connect(self.toolbar_button_style.setEnabled)
        self.toolbar_button_style.setEnabled(config["toolbar"]["visible"])
        toolbar_form.addRow("Buttons:", self.toolbar_button_style)

        self.toolbar_visible.toggled.connect(self.toolbar_area.setEnabled)
        self.toolbar_area.setEnabled(config["toolbar"]["visible"])
        self.toolbar_visible.toggled.connect(self._preview)
        self.toolbar_area.currentIndexChanged.connect(self._preview)

        customize_row = QHBoxLayout()
        customize_row.addStretch()
        customize_btn = QPushButton("Choose Toolbar Buttons…")
        customize_btn.clicked.connect(self._open_toolbar_customizer)
        customize_row.addWidget(customize_btn)
        toolbar_form.addRow(customize_row)

        root.addWidget(toolbar_group)

        # --- Advanced ---
        advanced_group = QGroupBox("Advanced")
        advanced_layout = QVBoxLayout(advanced_group)
        self.allow_drag = QCheckBox("Let me drag panels around the window")
        self.allow_drag.setChecked(config["allow_drag"])
        self.allow_drag.setToolTip(
            "Off: panels stay exactly where this dialog puts them.\n"
            "On: panels can be dragged, floated and tabbed together, and their\n"
            "arrangement is remembered instead of the settings above."
        )
        self.allow_drag.toggled.connect(self._preview)
        advanced_layout.addWidget(self.allow_drag)

        hint = QLabel(
            "With dragging off, panels can't be moved or closed by accident "
            "mid-session."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a09c8c;")
        advanced_layout.addWidget(hint)
        root.addWidget(advanced_group)

        # --- Buttons ---
        bottom = QHBoxLayout()
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self._restore_defaults)
        bottom.addWidget(restore_btn)
        bottom.addStretch()

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self._on_cancel)
        bottom.addWidget(button_box)
        root.addLayout(bottom)

    # ---- internal ----

    def current_config(self) -> dict:
        panels = {}
        for key, widgets in self._panel_widgets.items():
            panels[key] = {
                "visible": widgets["visible"].isChecked(),
                "side": widgets["side"].currentData(),
                "width": widgets["width"].value(),
            }
        return {
            "allow_drag": self.allow_drag.isChecked(),
            "panels": panels,
            "toolbar": {
                "visible": self.toolbar_visible.isChecked(),
                "area": self.toolbar_area.currentData(),
                "button_style": self.toolbar_button_style.currentData(),
            },
        }

    def _apply(self, config: dict) -> None:
        applier = getattr(self._tracker, "apply_panel_layout", None)
        if callable(applier):
            applier(config)

    def _preview(self, *_args) -> None:
        self._apply(self.current_config())

    def _open_toolbar_customizer(self) -> None:
        from ui.toolbar_customize_dialog import ToolbarCustomizeDialog

        dialog = ToolbarCustomizeDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            applier = getattr(self._tracker, "_apply_toolbar_config", None)
            if callable(applier):
                applier()
            # Re-apply so a toolbar that was empty (and therefore hidden) comes
            # back in the position this dialog is configured for.
            self._preview()

    def _restore_defaults(self) -> None:
        defaults = deepcopy(DEFAULT_PANEL_LAYOUT)
        for key, widgets in self._panel_widgets.items():
            entry = defaults["panels"][key]
            widgets["visible"].setChecked(entry["visible"])
            widgets["side"].setCurrentIndex(max(0, widgets["side"].findData(entry["side"])))
            widgets["width"].setValue(entry["width"])
        self.toolbar_visible.setChecked(defaults["toolbar"]["visible"])
        self.toolbar_area.setCurrentIndex(
            max(0, self.toolbar_area.findData(defaults["toolbar"]["area"]))
        )
        self.toolbar_button_style.setCurrentIndex(
            max(0, self.toolbar_button_style.findData(defaults["toolbar"]["button_style"]))
        )
        self.allow_drag.setChecked(defaults["allow_drag"])
        self._preview()

    def _on_save(self) -> None:
        config = self.current_config()
        save_panel_layout(config)
        self._apply(config)
        self.accept()

    def _on_cancel(self) -> None:
        # Undo the live preview.
        self._apply(self._original)
        self.reject()
