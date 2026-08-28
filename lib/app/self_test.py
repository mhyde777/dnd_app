# lib/app/self_test.py
"""
Checks a freshly installed build runs against itself, once, after an update.

The point is to decide something specific: is it safe to delete the version
this one replaced? Passing means yes, immediately. Failing means tell the user
what broke and offer to go back, while the old build is still there.

Every check must be fast, side-effect-free outside a temp directory, and
honest about "cannot tell" -- a check that fails because the user is offline
would revert people for no reason, so anything that depends on the network or
on optional configuration reports SKIPPED rather than FAILED.

Checks touching Qt objects run on the GUI thread (the runner in ui.py drives
them one per timer tick, so the app stays usable while they run). Nothing here
may block: no network waits, no dialogs, no sleeps.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Callable, List, Optional


class Skip(Exception):
    """Raised by a check that cannot run here -- not a failure."""


@dataclass
class Check:
    key: str
    label: str
    run: Callable[[], None]


@dataclass
class Result:
    key: str
    label: str
    status: str          # "passed" | "failed" | "skipped"
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"


def run_check(check: Check) -> Result:
    try:
        check.run()
    except Skip as exc:
        return Result(check.key, check.label, "skipped", str(exc))
    except Exception as exc:
        return Result(check.key, check.label, "failed", f"{type(exc).__name__}: {exc}")
    return Result(check.key, check.label, "passed")


# ---- the checks -------------------------------------------------------------

def _check_settings_readable() -> None:
    from app import settings

    data = settings.load()
    if not isinstance(data, dict):
        raise TypeError(f"settings.json did not load as a dict, got {type(data).__name__}")


def _check_config_writable() -> None:
    from app.paths import config_dir

    directory = config_dir()
    os.makedirs(directory, exist_ok=True)
    probe = os.path.join(directory, ".selftest")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("ok")
    with open(probe, "r", encoding="utf-8") as handle:
        if handle.read() != "ok":
            raise IOError("wrote to the config directory but read back something else")
    os.remove(probe)


def _check_creature_roundtrip() -> None:
    from app.creature import Monster, I_Creature

    original = Monster("Goblin 1", init=14, max_hp=7, curr_hp=5, notes="bloodied")
    restored = I_Creature.from_dict(original.to_dict())
    for field in ("name", "initiative", "max_hp", "curr_hp", "notes"):
        if getattr(restored, field) != getattr(original, field):
            raise ValueError(
                f"{field} did not survive a save/load round trip: "
                f"{getattr(original, field)!r} -> {getattr(restored, field)!r}"
            )


def _check_natural_ordering() -> None:
    from app.creature import Monster
    from app.manager import CreatureManager

    manager = CreatureManager()
    for name in ("Goblin 10", "Goblin 2", "Goblin 1"):
        manager.add_creature(Monster(name, init=10))
    names = manager.ordered_names()
    if names != ["Goblin 1", "Goblin 2", "Goblin 10"]:
        raise ValueError(f"combatants sorted as {names}, expected natural order")


def _check_turn_order() -> None:
    from app.creature import Monster
    from app.manager import CreatureManager

    manager = CreatureManager()
    manager.add_creature(Monster("Bandit", init=8))
    manager.add_creature(Monster("Archer", init=20))
    manager.add_creature(Monster("Adept", init=20))
    names = manager.ordered_names()
    if names != ["Adept", "Archer", "Bandit"]:
        raise ValueError(
            f"turn order was {names}, expected initiative descending then name"
        )


def _check_table_model() -> None:
    """The table has to be able to describe a creature without raising."""
    from PyQt5.QtCore import Qt
    from app.creature import Monster
    from app.manager import CreatureManager
    from ui.creature_table_model import CreatureTableModel

    manager = CreatureManager()
    manager.add_creature(Monster("Goblin 1", init=12, max_hp=7, curr_hp=7))
    model = CreatureTableModel(manager)
    model.set_fields_from_sample()
    model.refresh()
    if model.rowCount() != 1:
        raise ValueError(f"model showed {model.rowCount()} rows for one creature")
    if model.columnCount() < 1:
        raise ValueError("model reported no columns")
    for column in range(model.columnCount()):
        model.data(model.index(0, column), Qt.DisplayRole)
        model.headerData(column, Qt.Horizontal, Qt.DisplayRole)


def _check_theme() -> None:
    from ui import colors
    from ui.theme import get_stylesheet

    palette = colors.load()
    if not palette:
        raise ValueError("the colour palette loaded empty")
    sheet = get_stylesheet()
    if "QTableView" not in sheet:
        raise ValueError("the generated stylesheet is missing its table rules")


def _check_state_roundtrip() -> None:
    """A combat has to survive being written and read back."""
    from app.creature import Monster
    from app.manager import CreatureManager

    manager = CreatureManager()
    manager.add_creature(Monster("Ogre", init=9, max_hp=59, curr_hp=41))
    # CustomEncoder is what the app itself writes state with -- it is the
    # thing that knows how to serialise a CreatureType.
    from app.creature import CustomEncoder, I_Creature

    payload = {
        "creatures": [c.to_dict() for c in manager.creatures.values()],
        "round_counter": 3,
    }
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "state.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, cls=CustomEncoder)
        with open(path, "r", encoding="utf-8") as handle:
            restored = json.load(handle)

    if restored.get("round_counter") != 3:
        raise ValueError("the round counter did not survive a save/load round trip")
    creatures = restored.get("creatures") or []
    if len(creatures) != 1:
        raise ValueError(f"expected one creature back, got {len(creatures)}")
    revived = I_Creature.from_dict(creatures[0])
    if (revived.name, revived.curr_hp) != ("Ogre", 41):
        raise ValueError(
            f"creature came back as {revived.name!r} at {revived.curr_hp} hp"
        )


def _check_storage_backend() -> None:
    from app import config
    from app.storage import providers

    provider_id = config.get_storage_provider()
    provider = providers.get(provider_id)
    if provider is None:
        raise IOError(f"unknown storage provider: {provider_id!r}")
    if provider.group != providers.FOLDER:
        # A network backend means a network call, and being offline is not a
        # reason to revert someone's update.
        raise Skip(f"storage is {provider.label}; not exercised here")

    try:
        backend = providers.build(provider_id, config.get_storage_config(provider_id))
    except Exception as exc:
        raise IOError(f"storage could not be opened: {exc}") from exc

    directory = backend.describe()
    if not os.path.isdir(directory):
        raise IOError(f"the library folder does not exist: {directory}")
    if not os.access(directory, os.R_OK | os.W_OK):
        raise IOError(f"the library folder is not readable and writable: {directory}")


def _check_install_layout() -> None:
    from app import install_layout

    layout = install_layout.detect()
    if layout is None:
        raise Skip("not a versioned install")
    if not layout.has_launcher():
        raise IOError("the launcher is missing, so this build could not restart itself")
    selected = install_layout.read_current(layout)
    if selected and selected != layout.version:
        raise ValueError(
            f"'current' names {selected} but {layout.version} is running"
        )


def all_checks() -> List[Check]:
    return [
        Check("settings", "Settings load", _check_settings_readable),
        Check("config_dir", "Config directory is writable", _check_config_writable),
        Check("creature", "Creatures survive save and load", _check_creature_roundtrip),
        Check("ordering", "Combatants sort naturally", _check_natural_ordering),
        Check("turn_order", "Turn order follows initiative", _check_turn_order),
        Check("table", "The initiative table renders", _check_table_model),
        Check("theme", "Colours and stylesheet load", _check_theme),
        Check("state", "Combat state round-trips", _check_state_roundtrip),
        Check("storage", "Storage is reachable", _check_storage_backend),
        Check("layout", "The install can restart itself", _check_install_layout),
    ]


def summarise(results: List[Result]) -> str:
    passed = sum(1 for r in results if r.status == "passed")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = [r for r in results if r.failed]
    text = f"{passed} passed"
    if skipped:
        text += f", {skipped} skipped"
    if failed:
        text += f", {len(failed)} failed"
    return text


def first_failure(results: List[Result]) -> Optional[Result]:
    return next((r for r in results if r.failed), None)
