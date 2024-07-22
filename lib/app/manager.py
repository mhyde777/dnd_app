from typing import Dict, Union, Iterable

from app.creature import I_Creature


class CreatureManager:
    def __init__(self):
        self.creatures: Dict[str, I_Creature] = {}
        
    def add_creature(self, creature: Union[I_Creature, Iterable[I_Creature]]) -> None:
        if isinstance(creature, list) or isinstance(creature, tuple):
            for c in creature:
                self.creatures[c.name] = c
            return
        self.creatures[creature.name] = creature
    
    def rm_creatures(self, creature_names: Union[str, Iterable[str]]) -> None:
        if isinstance(creature_names, (list, tuple)):
            for c in creature_names:
                if c in self.creatures.keys() and isinstance(c, str):
                    del self.creatures[c]
            return
        if creature_names in self.creatures.keys() and isinstance(creature_names, str):
                del self.creatures[creature_names]

    def sort_creatures(self) -> None:
        self.creatures = dict(sorted(self.creatures.items(), key=lambda item: item[1], reverse=True))

    def set_creature_init(self, creature: str, init: int) -> None:
        self.creatures[creature].initiative = init
    
    def set_creature_max_hp(self, creature: str, max_hp: int) -> None:
        self.creatures[creature].max_hp = max_hp
    
    def set_creature_curr_hp(self, creature: str, curr_hp: int) -> None:
        self.creatures[creature].curr_hp = curr_hp
    
    def set_creature_armor_class(self, creature: str, ac: int) -> None:
        self.creatures[creature].armor_class = ac