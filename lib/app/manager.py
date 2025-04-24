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
        sorted_creatures = sorted(self.creatures.items(), key=lambda item: item[1].initiative, reverse=True)
        new_dict = {k: v for k, v in sorted_creatures}

        # print("[SORT] New order:", list(new_dict.keys()))

        # Force reference replacement
        self.creatures.clear()
        self.creatures.update(new_dict)

    def set_creature_init(self, creature: str, init: int) -> None:
        self.creatures[creature].initiative = init

    def set_creature_max_hp(self, creature: str, max_hp: int) -> None:
        self.creatures[creature].max_hp = max_hp
    
    def set_creature_curr_hp(self, creature: str, curr_hp: int) -> None:
        self.creatures[creature].curr_hp = curr_hp
    
    def set_creature_armor_class(self, creature: str, ac: int) -> None:
        self.creatures[creature].armor_class = ac

    def set_creature_movement(self, creature: str, movement: int) -> None:
        self.creatures[creature].movement = movement

    def set_creature_action(self, creature: str, action: bool) -> None:
        self.creatures[creature].action = action

    def set_creature_bonus_action(self, creature: str, bonus_action: bool) -> None:
        self.creatures[creature].bonus_action = bonus_action

    def set_creature_reaction(self, creature: str, reaction: bool) -> None:
        self.creatures[creature].reaction = reaction

    def set_creature_object_interaction(self, creature: str, object_interaction: bool) -> None:
        self.creatures[creature].object_interaction = object_interaction
    
    def set_creature_notes(self, creature: str, notes: str) -> None:
        self.creatures[creature].notes = notes

    def set_creature_status_time(self, creature: str, status_time: int) -> None:
        self.creatures[creature].status_time = status_time

