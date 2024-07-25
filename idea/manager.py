import os
import json
from app.manager import CreatureManager
from app.creature import Player, I_Creature

if __name__ == "__main__":
    chitra = Player(
        name="Chitra",
        init=16,
        max_hp=27,
        curr_hp=27,
        armor_class=16
    )
    echo = Player(
        name="Echo",
        init=20,
        max_hp=21,
        curr_hp=21,
        armor_class=17
    )
    jorji = Player(
        name="Jorji",
        init=8,
        max_hp=21,
        curr_hp=21,
        armor_class=15
    )
    surina = Player(
        name="Surina",
        init=4,
        max_hp=28,
        curr_hp=28,
        armor_class=16
    )
    val = Player(
        name="Val",
        init=12,
        max_hp=25,
        curr_hp=25,
        armor_class=16
    )
    
    manager = CreatureManager()
    manager.add_creature([chitra, echo, jorji, surina, val])
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, 'data', 'players.json')
    # state = {
    #     'creatures': {name: creature.__dict__ for name, creature in manager.creatures.items()}
    # } 
    # with open(file_path, 'w') as file:
    #     json.dump(state, file, indent=4)
        


    # for k, v in manager.creatures.items():
    #     print(f"{k}: {v}")
    # print("\n\n") 
    # manager.sort_creatures()
    # for k, v in manager.creatures.items():
    #     print(f"{k}: {v}")
    #
    # manager.rm_creatures(['Chitra', 'Surina'])
    # print("\n\n")
    # for k, v in manager.creatures.items():
    #     print(f"{k}: {v}")
    # print("\n\n") 
