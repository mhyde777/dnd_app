from __future__ import annotations
# from _typeshed import OptExcInfo

from typing import Any, Dict
import json
from enum import Enum
from typing import Any, Dict
from dataclasses import dataclass, field

from app.exceptions import CreatureTypeError

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return json.JSONEncoder.default(self, obj)


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return json.JSONEncoder.default(self, obj)


class CreatureType(Enum):
    BASE = 0
    MONSTER = 1
    PLAYER = 2

    def __repr__(self) -> str:
        return str(self.name)

class MonsterType(Enum):
    pass


class PlayerType(Enum):
    pass


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
    _status_time: int = field(default=-1)

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
            "_status_time": self.status_time
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> I_Creature:
        match CreatureType(data["_type"]):
            case CreatureType.PLAYER:
                return Player(
                    name=data["_name"],
                    init=data["_init"],
                    max_hp=data["_max_hp"],
                    curr_hp=data["_curr_hp"],
                    armor_class=data["_armor_class"],
                    movement=data["_movement"],
                    action=data["_action"],
                    bonus_action=data["_bonus_action"],
                    object_interaction=data["_object_interaction"],
                    notes=data["_notes"],
                    status_time=data["_status_time"]
                )
            case CreatureType.MONSTER:
                return Monster(
                    name=data["_name"],
                    init=data["_init"],
                    max_hp=data["_max_hp"],
                    curr_hp=data["_curr_hp"],
                    armor_class=data["_armor_class"],
                    movement=data["_movement"],
                    action=data["_action"],
                    bonus_action=data["_bonus_action"],
                    notes=data["_notes"],
                    status_time=data["_status_time"]
                )

    @property
    def name(self) -> str:
        return self._name
    
    @name.setter
    def name(self, name: str) -> None:
        self._name = name
    
    @property
    def initiative(self) -> int:
        return self._init
    
    @initiative.setter
    def initiative(self, init: int) -> None:
        self._init = init
    
    @property
    def max_hp(self) -> int:
        return self._max_hp
    
    @max_hp.setter
    def max_hp(self, hp: int) -> None:
        self._max_hp = hp
    
    @property
    def curr_hp(self) -> int:
        return self._curr_hp
    
    @curr_hp.setter
    def curr_hp(self, hp: int) -> None:
        self._curr_hp = hp
    
    @property
    def armor_class(self) -> int:
        return self._armor_class
    
    @armor_class.setter
    def armor_class(self, ac: int) -> None:
        self._armor_class = ac
    
    @property
    def movement(self) -> int:
        return self._movement
    
    @movement.setter
    def movement(self, distance: int) -> None:
        self._movement = distance
    
    @property
    def action(self) -> bool:
        return self._action
    
    @action.setter
    def action(self, action_done: bool) -> None:
        self._action = action_done
    
    @property
    def bonus_action(self) -> bool:
        return self._bonus_action
    
    @bonus_action.setter
    def bonus_action(self, bonus_action_done: bool) -> None:
        self._bonus_action = bonus_action_done
    
    @property
    def reaction(self) -> bool:
        return self._reaction
    
    @reaction.setter
    def reaction(self, reaction_done: bool) -> None:
        self._reaction = reaction_done
    
    @property
    def object_interaction(self) -> bool:
        return self._object_interaction
    
    @object_interaction.setter
    def object_interaction(self, obj_int_done: bool) -> None:
        self._object_interaction = obj_int_done
    
    @property
    def notes(self) -> str:
        return self._notes
    
    @notes.setter
    def notes(self, notes: str) -> None:
        self._notes = notes

    @property
    def status_time(self) -> int:
        return self._status_time
    
    @status_time.setter
    def status_time(self, status_time: int) -> None:
        self._status_time = status_time


class Monster(I_Creature):
    def __init__(
        self,
        name,
        init=0,
        max_hp=0,
        curr_hp=0,
        armor_class=0,
        movement=0,
        action=False,
        bonus_action=False,
        reaction=False,
        notes='',
        status_time=''
    ) -> None:
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
            _status_time=status_time
        )


class Player(I_Creature):
    def __init__(
        self,
        name,
        init=0,
        max_hp=0,
        curr_hp=0,
        armor_class=0,
        movement=0,
        action=False,
        bonus_action=False,
        reaction=False,
        object_interaction=False,
        notes='',
        status_time=''
    ) -> None:
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
            _status_time=status_time
        )
