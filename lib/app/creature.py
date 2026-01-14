from __future__ import annotations
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
import json
from enum import Enum
from app.exceptions import CreatureTypeError


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


class CreatureType(Enum):
    BASE = 0
    MONSTER = 1
    PLAYER = 2

    def __repr__(self) -> str:
        return str(self.name)


@dataclass
class I_Creature:
    _type: CreatureType = field(default=CreatureType.BASE)
    _name: str = field(default="")
    _init: int = field(default=-1)
    _max_hp: int = field(default=-1)
    _curr_hp: int = field(default=-1)
    _armor_class: int = field(default=-1)
    _movement: int = field(default=-1)
    _action: bool = field(default=False)
    _bonus_action: bool = field(default=False)
    _reaction: bool = field(default=False)
    _object_interaction: bool = field(default=False)
    _notes: str = field(default="")
    _public_notes: str = field(default="")
    _player_visible: bool = field(default=True)
    _conditions: List[str] = field(default_factory=list)
    _status_time: int = field(default=-1)
    _spell_slots: dict[int, int] = field(default_factory=dict)
    _innate_slots: dict[str, int] = field(default_factory=dict)
    _spell_slots_used: dict[int, int] = field(default_factory=dict)
    _innate_slots_used: dict[str, int] = field(default_factory=dict)
    _death_successes: int = field(default=0)
    _death_failures: int = field(default=0)
    _death_stable: bool = field(default=False)
    _death_saves_prompt: bool = field(default=False)
    _active: bool = field(default=True)

    def __gt__(self, other: I_Creature) -> bool:
        if not isinstance(other, I_Creature):
            raise CreatureTypeError
        return self._init > other._init

    def __lt__(self, other: I_Creature) -> bool:
        if not isinstance(other, I_Creature):
            raise CreatureTypeError
        return self._init < other._init

    def __eq__(self, other: I_Creature) -> bool:
        if not isinstance(other, I_Creature):
            raise CreatureTypeError
        return self._init == other._init

    def to_dict(self) -> Dict[str, Any]:
        return {
            "_type": self._type,
            "_name": self.name,
            "_init": self.initiative,
            "_max_hp": self.max_hp,
            "_curr_hp": self.curr_hp,
            "_armor_class": self.armor_class,
            "_movement": self.movement,
            "_action": self.action,
            "_bonus_action": self.bonus_action,
            "_reaction": self.reaction,
            "_object_interaction": self.object_interaction,
            "_notes": self.notes,
            "_public_notes": self.public_notes,
            "_player_visible": self.player_visible,
            "_conditions": self.conditions,
            "_status_time": self.status_time,
            "_spell_slots": self._spell_slots,
            "_innate_slots": self._innate_slots,
            "_spell_slots_used": self._spell_slots_used,
            "_innate_slots_used": self._innate_slots_used,
            "_death_successes": self._death_successes,
            "_death_failures": self._death_failures,
            "_death_stable": self._death_stable,
            "_death_saves_prompt": self._death_saves_prompt,
            "_active": self._active
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> I_Creature:
        creature_type = CreatureType(data["_type"])
        conditions = data.get("_conditions", [])
        public_notes = data.get("_public_notes", "")
        player_visible = data.get("_player_visible")
        spell_slots = data.get("_spell_slots", {})
        innate_slots = data.get("_innate_slots", {})
        spell_slots_used = data.get("_spell_slots_used")
        innate_slots_used = data.get("_innate_slots_used")
        death_successes = data.get("_death_successes", 0)
        death_failures = data.get("_death_failures", 0)
        death_stable = data.get("_death_stable", False)
        death_saves_prompt = data.get("_death_saves_prompt", False)
        active = data.get("_active", True)
        # print("[LOAD CREATURE]", data["_name"])
        # print("  _innate_slots_used:", data.get("_innate_slots_used"))
        # print("  _spell_slots_used:", data.get("_spell_slots_used"))

        if creature_type == CreatureType.PLAYER:
            if player_visible is None:
                player_visible = True
            return Player(
                name=data["_name"],
                init=data["_init"],
                max_hp=data["_max_hp"],
                curr_hp=data["_curr_hp"],
                armor_class=data["_armor_class"],
                movement=data["_movement"],
                action=data["_action"],
                bonus_action=data["_bonus_action"],
                reaction=data["_reaction"],
                object_interaction=data["_object_interaction"],
                notes=data["_notes"],
                public_notes=public_notes,
                player_visible=player_visible,
                conditions = conditions,
                status_time=data["_status_time"],
                spell_slots=spell_slots,
                innate_slots=innate_slots,
                spell_slots_used=spell_slots_used,
                innate_slots_used=innate_slots_used,
                death_successes=death_successes,
                death_failures=death_failures,
                death_stable=death_stable,
                active=active
            )
        elif creature_type == CreatureType.MONSTER:
            if player_visible is None:
                player_visible = True
            return Monster(
                name=data["_name"],
                init=data["_init"],
                max_hp=data["_max_hp"],
                curr_hp=data["_curr_hp"],
                armor_class=data["_armor_class"],
                movement=data["_movement"],
                action=data["_action"],
                bonus_action=data["_bonus_action"],
                reaction=data["_reaction"],
                notes=data["_notes"],
                public_notes=public_notes,
                player_visible=player_visible,
                conditions=conditions,
                status_time=data["_status_time"],
                spell_slots=spell_slots,
                innate_slots=innate_slots,
                spell_slots_used=spell_slots_used,
                innate_slots_used=innate_slots_used,
                death_saves_prompt=bool(death_saves_prompt) if death_saves_prompt is not None else False,
                active=active
            )
        else:
            return I_Creature(**data)


    # Properties
    @property
    def name(self) -> str: return self._name
    @name.setter
    def name(self, value: str): self._name = value

    @property
    def initiative(self) -> int: return self._init
    @initiative.setter
    def initiative(self, value: int): self._init = value

    @property
    def max_hp(self) -> int: return self._max_hp
    @max_hp.setter
    def max_hp(self, value: int): self._max_hp = value

    @property
    def curr_hp(self) -> int: return self._curr_hp
    @curr_hp.setter
    def curr_hp(self, value: int): self._curr_hp = value

    @property
    def armor_class(self) -> int: return self._armor_class
    @armor_class.setter
    def armor_class(self, value: int): self._armor_class = value

    @property
    def movement(self) -> int: return self._movement
    @movement.setter
    def movement(self, value: int): self._movement = value

    @property
    def action(self) -> bool: return self._action
    @action.setter
    def action(self, value: bool): self._action = value

    @property
    def bonus_action(self) -> bool: return self._bonus_action
    @bonus_action.setter
    def bonus_action(self, value: bool): self._bonus_action = value

    @property
    def reaction(self) -> bool: return self._reaction
    @reaction.setter
    def reaction(self, value: bool): self._reaction = value

    @property
    def object_interaction(self) -> bool: return self._object_interaction
    @object_interaction.setter
    def object_interaction(self, value: bool): self._object_interaction = value

    @property
    def notes(self) -> str: return self._notes
    @notes.setter
    def notes(self, value: str): self._notes = value

    @property
    def public_notes(self) -> str: return self._public_notes
    @public_notes.setter
    def public_notes(self, value: str): self._public_notes = value

    @property
    def player_visible(self) -> bool: return self._player_visible
    @player_visible.setter
    def player_visible(self, value: bool): self._player_visible = bool(value)

    @property
    def conditions(self) -> List[str]:
        return sorted(set(self._conditions))
    @conditions.setter
    def conditions(self, value):
        if value is None:
            self._conditions = []
            return
        self._conditions = [str(v) for v in value]

    @property
    def status_time(self) -> int: return self._status_time
    @status_time.setter
    def status_time(self, value: int): self._status_time = value

    @property
    def death_successes(self) -> int: return self._death_successes
    @death_successes.setter
    def death_successes(self, v: int): self._death_successes = int(v)

    @property
    def death_failures(self) -> int: return self._death_failures
    @death_failures.setter
    def death_failures(self, v: int): self._death_failures = int(v)

    @property
    def death_stable(self) -> bool: return self._death_stable
    @death_stable.setter
    def death_stable(self, v: bool): self._death_stable = bool(v)

    @property
    def death_saves_prompt(self) -> bool: return self._death_saves_prompt
    @death_saves_prompt.setter
    def death_saves_prompt(self, v: bool): self._death_saves_prompt = bool(v)

    @property
    def active(self) -> bool: return self._active
    @active.setter
    def active(self, value: bool): self._active = value


class Monster(I_Creature):
    def __init__(self, name, init=0, max_hp=0, curr_hp=0, armor_class=0,
                 movement=0, action=False, bonus_action=False, reaction=False,
                 notes='', public_notes='', player_visible=True, conditions=None, status_time='',
                 spell_slots=None, innate_slots=None, spell_slots_used=None,
                 innate_slots_used=None, death_saves_prompt=False, active=True):
        super().__init__(
            _type=CreatureType.MONSTER,
            _name=name,
            _init=init,
            _max_hp=max_hp,
            _curr_hp=curr_hp,
            _armor_class=armor_class,
            _movement=movement,
            _action=action,
            _bonus_action=bonus_action,
            _reaction=reaction,
            _notes=notes,
            _public_notes=public_notes,
            _player_visible=bool(player_visible),
            _conditions=(conditions or []),
            _status_time=status_time,
            _spell_slots=spell_slots or {},
            _innate_slots=innate_slots or {},
            _spell_slots_used=spell_slots_used or {},
            _innate_slots_used=innate_slots_used or {},
            _death_saves_prompt=bool(death_saves_prompt),
            _active=active
        )


class Player(I_Creature):
    def __init__(self, name, init=0, max_hp=0, curr_hp=0, armor_class=0,
                 movement=0, action=False, bonus_action=False, reaction=False,
                 object_interaction=False, notes='', public_notes='', player_visible=True,
                 conditions=None, status_time='',
                 spell_slots=None, innate_slots=None, spell_slots_used=None,
                 innate_slots_used=None, death_successes=0, death_failures=0, death_stable=False, active=True):
        super().__init__(
            _type=CreatureType.PLAYER,
            _name=name,
            _init=init,
            _max_hp=max_hp,
            _curr_hp=curr_hp,
            _armor_class=armor_class,
            _movement=movement,
            _action=action,
            _bonus_action=bonus_action,
            _reaction=reaction,
            _object_interaction=object_interaction,
            _notes=notes,
            _public_notes=public_notes,
            _player_visible=bool(player_visible),
            _conditions=(conditions or []),
            _status_time=status_time,
            _spell_slots=spell_slots or {},
            _innate_slots=innate_slots or {},
            _spell_slots_used=spell_slots_used or {},
            _innate_slots_used=innate_slots_used or {},
            _death_successes=death_successes,
            _death_failures=death_failures,
            _death_stable=death_stable,
            _death_saves_prompt=True,
            _active=active
        )
