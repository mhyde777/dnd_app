import json
from typing import Dict, List

from app.creature import Player

# EXAMPLE EXAMPLE EXAMPLE
class GameState:
    players: List[Player]
    current_turn: int
    round_counter: int
    time_counter: int

    def to_dict(self) -> Dict:
        return {
            "players": [p.to_dict() for p in self.players],
            "current_turn": self.current_turn,
            "round_counter": self.round_counter,
            "time_counter": self.time_counter
        }

g = GameState()
g.players = [
    Player(
        name="Chitra",
        init=16,
        max_hp=27,
        curr_hp=27,
        armor_class=16
    ),
    Player(
        name="Echo",
        init=20,
        max_hp=21,
        curr_hp=21,
        armor_class=17
    ),
    Player(
        name="Jorji",
        init=8,
        max_hp=21,
        curr_hp=21,
        armor_class=15
    )
]
g.current_turn = 100
g.round_counter = 1
g.time_counter = 7

payload = g.to_dict()
with open("test.json", "w") as f:
    json.dump(payload, f, indent=4)
