"""
The paste box in the import dialogs collapses once, not on every parse.

All three importers parse on a 500ms debounce after you stop typing, and each
used to collapse the paste box whenever a parse succeeded. That is fine the
first time -- it hands the window to the preview -- and wrong every time after:
reopening the box to correct the pasted text meant it vanished again the moment
you paused, taking the keyboard focus with it. Correcting several things turned
into clicking "Show" between every edit.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")
from PyQt5.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


STATBLOCK = """\
Goblin
Small humanoid (goblinoid), neutral evil
Armor Class 15 (leather armor, shield)
Hit Points 7 (2d6)
Speed 30 ft.
STR 8 (-1) DEX 14 (+2) CON 10 (+0) INT 10 (+0) WIS 8 (-1) CHA 8 (-1)
Challenge 1/4 (50 XP)
Actions
Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage.
"""

SPELL = """\
Fireball
3rd-level evocation
Casting Time: 1 action
Range: 150 feet
Components: V, S, M (a tiny ball of bat guano and sulfur)
Duration: Instantaneous
A bright streak flashes from your pointing finger and blossoms into an explosion of flame.
"""

ITEM = """\
Acheron Blade
Rare
Weapon
Required
Bonus: Magic
Weapon (any sword), rare (requires attunement)
The black blade of this sword is crafted from a mysterious arcane alloy.

Notes: Bonus: Magic
View Details Page
Explorer's Guide to Wildemount
"""


def _statblock_dialog(qapp):
    from ui.statblock_import_dialog import StatblockImportDialog

    dlg = StatblockImportDialog(storage=None)
    return dlg, STATBLOCK, dlg._toggle_text_panel, "Goblin"


def _spell_dialog(qapp):
    from ui.spell_import_dialog import SpellImportDialog

    dlg = SpellImportDialog(storage=None)
    return dlg, SPELL, dlg._toggle_text_panel, "Fireball"


def _item_dialog(qapp):
    from ui.bulk_item_import_dialog import BulkItemImportDialog

    dlg = BulkItemImportDialog(storage=None)
    return dlg, ITEM, dlg._toggle_paste_area, "Acheron Blade"


DIALOGS = [
    pytest.param(_statblock_dialog, id="statblock"),
    pytest.param(_spell_dialog, id="spell"),
    pytest.param(_item_dialog, id="bulk-items"),
]


@pytest.mark.parametrize("factory", DIALOGS)
def test_paste_box_collapses_once_after_a_successful_parse(qapp, factory):
    dlg, text, _toggle, _name = factory(qapp)
    dlg.show()
    assert dlg.text_edit.isVisible(), "the paste box is where you start"

    dlg.text_edit.setPlainText(text)
    dlg._do_parse()
    assert not dlg.text_edit.isVisible(), "collapses to hand the window over"


@pytest.mark.parametrize("factory", DIALOGS)
def test_reopened_paste_box_survives_repeated_edits(qapp, factory):
    """The reported bug: one edit and you are kicked back out."""
    dlg, text, toggle, name = factory(qapp)
    dlg.show()
    dlg.text_edit.setPlainText(text)
    dlg._do_parse()
    toggle()                                  # the user clicks "Show"
    assert dlg.text_edit.isVisible()

    for i in range(5):
        dlg.text_edit.setPlainText(text.replace(name, f"{name} {i}", 1))
        dlg._do_parse()                       # the debounce firing mid-edit
        assert dlg.text_edit.isVisible(), f"kicked out of the box on edit {i}"


@pytest.mark.parametrize("factory", DIALOGS)
def test_reopening_puts_the_cursor_in_the_box(qapp, factory):
    """You clicked Show to type; you should not have to click again."""
    dlg, text, toggle, _name = factory(qapp)
    dlg.show()
    dlg.text_edit.setPlainText(text)
    dlg._do_parse()
    toggle()
    assert dlg.focusWidget() is dlg.text_edit


@pytest.mark.parametrize("factory", DIALOGS)
def test_hide_still_works_by_hand(qapp, factory):
    """Only the automatic collapse is once-only; the button is not."""
    dlg, text, toggle, _name = factory(qapp)
    dlg.show()
    dlg.text_edit.setPlainText(text)
    dlg._do_parse()
    toggle()
    assert dlg.text_edit.isVisible()
    toggle()
    assert not dlg.text_edit.isVisible()
    toggle()
    assert dlg.text_edit.isVisible()


@pytest.mark.parametrize("factory", DIALOGS)
def test_the_preview_still_follows_the_edits(qapp, factory):
    """Keeping the box open must not cost the live preview it was hiding for."""
    dlg, text, toggle, name = factory(qapp)
    dlg.show()
    dlg.text_edit.setPlainText(text)
    dlg._do_parse()
    toggle()

    dlg.text_edit.setPlainText(text.replace(name, "Renamed Thing", 1))
    dlg._do_parse()

    if hasattr(dlg, "_parsed_data"):
        assert dlg._parsed_data["name"] == "Renamed Thing"
    else:
        # The bulk dialog builds a row per item rather than one parsed dict.
        assert dlg._rows and dlg._rows[0].block.name == "Renamed Thing"
