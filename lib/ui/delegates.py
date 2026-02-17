# lib/ui/delegates.py — Custom table delegate for the creature table
from PyQt5.QtCore import Qt, QSize, QRect
from PyQt5.QtGui import QColor, QFont, QPen
from PyQt5.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from ui.colors import (
    ACTIVE_BAR_COLOR, ACTIVE_BAR_WIDTH,
    BOOL_TRUE_FG, BOOL_FALSE_FG,
)


class CreatureTableDelegate(QStyledItemDelegate):
    """
    Custom rendering for the creature table:
    - Gold accent bar on left edge of active creature row
    - Bold text for active creature row
    - Centered checkmark/cross symbols for boolean cells
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_creature_name = None

    def set_active_creature(self, name: str):
        self._active_creature_name = name

    def paint(self, painter, option, index):
        # Determine if this row is the active creature
        model = index.model()
        row = index.row()
        is_active = False
        if model and self._active_creature_name:
            names = getattr(model, "creature_names", [])
            if row < len(names) and names[row] == self._active_creature_name:
                is_active = True

        # Check if this is a boolean cell by looking at display text
        display = index.data(Qt.DisplayRole)
        is_bool_cell = display in ("\u2714", "\u2718")  # ✔ or ✘

        # Let the base class paint background and selection
        super().paint(painter, option, index)

        # Paint boolean symbol with color on top if applicable
        if is_bool_cell:
            painter.save()
            color = QColor(BOOL_TRUE_FG) if display == "\u2714" else QColor(BOOL_FALSE_FG)
            font = QFont(option.font)
            font.setPointSize(font.pointSize() + 2)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(option.rect, Qt.AlignCenter, display)
            painter.restore()

        # Draw gold accent bar for active row
        if is_active:
            painter.save()
            bar_rect = QRect(
                option.rect.left(),
                option.rect.top(),
                ACTIVE_BAR_WIDTH,
                option.rect.height(),
            )
            painter.fillRect(bar_rect, QColor(ACTIVE_BAR_COLOR))
            painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Add a bit of extra height for readability
        return QSize(size.width(), max(size.height(), 28))
