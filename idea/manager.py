from app.manager import CreatureManager
from app.creature import Player

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
    
    for k, v in manager.creatures.items():
        print(f"{k}: {v}")
    print("\n\n") 
    manager.sort_creatures()
    for k, v in manager.creatures.items():
        print(f"{k}: {v}")

    manager.rm_creatures([jorji])

    for k, v in manager.creatures.items():
        print(f"{k}: {v}")
    print("\n\n") 
    manager.sort_creatures()
    for k, v in manager.creatures.items():
        print(f"{k}: {v}")
        
