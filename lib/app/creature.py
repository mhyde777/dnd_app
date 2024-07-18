from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field

from app.exceptions import CreatureTypeError


class CreatureType(Enum):
    BASE = 0
    MONSTER = 1
    PLAYER = 3


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


class Monster(I_Creature):
    def __init__(
        self,
        name,
    ) -> None:
        super().__init__(
            _type=CreatureType.MONSTER,
            _name=name,
            _init=0,
            _max_hp=0,
            _curr_hp=0,
            _armor_class=0,
            _movement=0,
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
    ) -> None:
        super().__init__(
            _type=CreatureType.PLAYER,
            _name=name,
            _init=init,
            _max_hp=max_hp,
            _curr_hp=curr_hp,
            _armor_class=armor_class,
            _movement=movement,
        )