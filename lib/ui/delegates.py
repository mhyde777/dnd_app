# lib/ui/delegates.py — Custom table delegate for the creature table
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QStyledItemDelegate

from ui.colors import BOOL_TRUE_FG, BOOL_FALSE_FG


class CreatureTableDelegate(QStyledItemDelegate):
    """
    Custom rendering for the creature table:
    - Bold text for active creature row
    - Centered checkmark/cross symbols for boolean cells
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
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


    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Add a bit of extra height for readability
        return QSize(size.width(), max(size.height(), 28))
