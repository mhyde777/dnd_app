import json
from typing import Dict, List

from app.creature import Player, Monster, I_Creature

class GameState:
    players: List[Player]
    # monsters: List[Monster]
    current_turn: int
    round_counter: int
    time_counter: int

    def to_dict(self) -> Dict:
        return{
            "players": [p.to_dict() for p in self.players],
            # "monsters": [m.to_dict() for m in self.monsters],
            "current_turn": self.current_turn,
            "round_counter": self.round_counter,
            "time_counter": self.time_counter
        }
