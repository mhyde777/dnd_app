# lib/ui/icons.py — toolbar iconography
"""
Hand-drawn toolbar icons.

Qt's `QStyle.standardIcon` set is small and renders differently on every
platform and theme, so the same button can end up looking like an unrelated
concept on someone else's machine — a packaged build has no control over that.
These are painted from primitives instead: identical everywhere, sharp at any
DPI, and tinted from the user's palette.

A misleading icon is worse than none, so `icon_for()` returns a null QIcon for
any action without an honest visual metaphor. Those stay text-only.
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_CANVAS = 64  # drawn large, scaled down by Qt — keeps edges clean on hi-DPI


def _pen(color: QColor, width: float = 6.0) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# ── Individual glyphs. Each draws into a 64×64 painter. ──────────────

def _draw_plus(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 7))
    p.drawLine(32, 14, 32, 50)
    p.drawLine(14, 32, 50, 32)


def _draw_minus(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 7))
    p.drawLine(14, 32, 50, 32)


def _draw_chevron_right(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 7))
    p.drawPolyline(QPointF(24, 14), QPointF(42, 32), QPointF(24, 50))


def _draw_chevron_left(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 7))
    p.drawPolyline(QPointF(40, 14), QPointF(22, 32), QPointF(40, 50))


def _draw_save(p: QPainter, c: QColor) -> None:
    # Floppy outline with a shutter and a label.
    p.setPen(_pen(c, 5))
    p.drawRoundedRect(QRectF(12, 12, 40, 40), 4, 4)
    p.drawRect(QRectF(22, 12, 20, 14))
    p.drawRect(QRectF(20, 34, 24, 18))


def _draw_save_as(p: QPainter, c: QColor) -> None:
    _draw_save(p, c)
    p.setPen(_pen(c, 5))
    p.drawLine(44, 44, 44, 56)
    p.drawLine(38, 50, 50, 50)


def _draw_folder(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    path = QPainterPath()
    path.moveTo(10, 48)
    path.lineTo(10, 18)
    path.lineTo(26, 18)
    path.lineTo(31, 25)
    path.lineTo(54, 25)
    path.lineTo(54, 48)
    path.closeSubpath()
    p.drawPath(path)


def _draw_trash(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    p.drawLine(14, 20, 50, 20)
    p.drawLine(26, 20, 26, 13)
    p.drawLine(26, 13, 38, 13)
    p.drawLine(38, 13, 38, 20)
    p.drawPolyline(QPointF(19, 20), QPointF(22, 52), QPointF(42, 52), QPointF(45, 20))
    p.drawLine(32, 28, 32, 44)


def _draw_search(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 6))
    p.drawEllipse(QRectF(14, 14, 26, 26))
    p.drawLine(38, 38, 51, 51)


def _draw_refresh(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 6))
    # Arc stops at 12 o'clock (90°) and a solid head carries on clockwise from
    # there; without a head large enough to read, a gapped ring is just a "C".
    p.drawArc(QRectF(15, 15, 34, 34), 150 * 16, 300 * 16)
    head = QPainterPath()
    head.moveTo(28, 4)
    head.lineTo(28, 26)
    head.lineTo(48, 15)
    head.closeSubpath()
    p.fillPath(head, c)


def _draw_download(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 6))
    p.drawLine(32, 12, 32, 38)
    p.drawPolyline(QPointF(20, 28), QPointF(32, 40), QPointF(44, 28))
    p.drawLine(14, 50, 50, 50)


def _draw_merge(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    p.drawPolyline(QPointF(14, 14), QPointF(32, 32), QPointF(50, 32))
    p.drawPolyline(QPointF(14, 50), QPointF(32, 32))
    head = QPainterPath()
    head.moveTo(54, 32)
    head.lineTo(42, 25)
    head.lineTo(42, 39)
    head.closeSubpath()
    p.fillPath(head, c)


def _draw_people(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    p.drawEllipse(QRectF(11, 14, 16, 16))
    p.drawArc(QRectF(5, 32, 28, 26), 0, 180 * 16)
    p.drawEllipse(QRectF(37, 16, 14, 14))
    p.drawArc(QRectF(32, 33, 26, 24), 0, 180 * 16)


def _draw_gear(p: QPainter, c: QColor) -> None:
    # Thick stubby teeth around a heavy ring — thin radiating lines read as a
    # sun or an asterisk at toolbar size.
    p.save()
    p.translate(32, 32)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for _ in range(8):
        p.drawRoundedRect(QRectF(-5.5, -25, 11, 12), 2, 2)
        p.rotate(45)
    p.restore()
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, 8))
    p.drawEllipse(QRectF(15, 15, 34, 34))
    p.setPen(_pen(c, 5))
    p.drawEllipse(QRectF(25, 25, 14, 14))


def _draw_lair(p: QPainter, c: QColor) -> None:
    # A cave mouth in a mountain: the environment itself taking a turn.
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    mountain = QPainterPath()
    mountain.moveTo(6, 54)
    mountain.lineTo(24, 16)
    mountain.lineTo(34, 32)
    mountain.lineTo(42, 22)
    mountain.lineTo(58, 54)
    mountain.closeSubpath()
    p.drawPath(mountain)

    # Punch the opening back out in the background colour by drawing the arch
    # with the composition mode that clears it.
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    arch = QPainterPath()
    arch.moveTo(24, 55)
    arch.lineTo(24, 44)
    arch.quadTo(32, 34, 40, 44)
    arch.lineTo(40, 55)
    arch.closeSubpath()
    p.drawPath(arch)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.setBrush(Qt.NoBrush)


def _draw_flag(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    p.drawLine(18, 10, 18, 54)
    path = QPainterPath()
    path.moveTo(18, 14)
    path.lineTo(48, 22)
    path.lineTo(18, 32)
    path.closeSubpath()
    p.fillPath(path, c)


def _draw_block(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 6))
    p.drawEllipse(QRectF(13, 13, 38, 38))
    p.drawLine(20, 20, 44, 44)


def _draw_document(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    path = QPainterPath()
    path.moveTo(17, 10)
    path.lineTo(38, 10)
    path.lineTo(48, 20)
    path.lineTo(48, 54)
    path.lineTo(17, 54)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(25, 28, 40, 28)
    p.drawLine(25, 38, 40, 38)


def _draw_list(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    for y in (18, 32, 46):
        p.drawLine(14, y, 17, y)
        p.drawLine(26, y, 50, y)


def _draw_info(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 5))
    p.drawEllipse(QRectF(13, 13, 38, 38))
    p.drawLine(32, 29, 32, 43)
    p.drawPoint(QPointF(32, 21))


_GLYPHS = {
    "plus": _draw_plus,
    "minus": _draw_minus,
    "next": _draw_chevron_right,
    "prev": _draw_chevron_left,
    "save": _draw_save,
    "save_as": _draw_save_as,
    "folder": _draw_folder,
    "trash": _draw_trash,
    "search": _draw_search,
    "refresh": _draw_refresh,
    "download": _draw_download,
    "merge": _draw_merge,
    "people": _draw_people,
    "gear": _draw_gear,
    "lair": _draw_lair,
    "flag": _draw_flag,
    "block": _draw_block,
    "document": _draw_document,
    "list": _draw_list,
    "info": _draw_info,
}

# Toolbar action id → glyph. Anything absent stays text-only on purpose:
# no honest picture beats a misleading one.
ACTION_GLYPHS = {
    "save": "save",
    "save_as": "save_as",
    "load_encounter": "folder",
    "build_encounter": "document",
    "merge_encounters": "merge",
    "delete_encounter": "trash",
    "activate_encounters": "list",
    "add_combatant": "plus",
    "remove_combatants": "minus",
    "add_lair_action": "lair",
    "next_turn": "next",
    "prev_turn": "prev",
    "initialize": "refresh",
    "reference_lookup": "search",
    "update_characters": "people",
    "import_statblock": "download",
    "import_spell": "download",
    "bulk_import_items": "download",
    "shop_generator": "flag",
    "settings": "gear",
    "foundry_ignore": "block",
    "show_log": "info",
}


def glyph_icon(glyph: str, color: str, size: int = _CANVAS) -> QIcon:
    """Render one named glyph into a QIcon. Unknown names give a null icon."""
    draw = _GLYPHS.get(glyph)
    if draw is None:
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if size != _CANVAS:
            painter.scale(size / _CANVAS, size / _CANVAS)
        draw(painter, QColor(color))
    finally:
        painter.end()
    return QIcon(pixmap)


def icon_for(action_id: str, color: str) -> QIcon:
    """Icon for a toolbar action id, or a null QIcon when none is appropriate."""
    glyph = ACTION_GLYPHS.get(action_id)
    return glyph_icon(glyph, color) if glyph else QIcon()
