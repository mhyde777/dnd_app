from typing import Dict, Union, Iterable, Any, List, Tuple, Optional
from app.creature import I_Creature
import re


class CreatureManager:
    def __init__(self):
        self.creatures: Dict[str, I_Creature] = {}
        self._join_seq = 0  # kept for compatibility; not required for natural-sort tiebreaks

    @staticmethod
    def _natural_key(s: str) -> List[Any]:
        """
        Natural sort key so 'Guard 9' < 'Guard 10' (human-friendly).
        Splits digits into ints and lowercases text.
        """
        parts = re.findall(r"\d+|\D+", s or "")
        return [int(p) if p.isdigit() else p.lower() for p in parts]

    # ---------- Core mutation ----------

    def add_creature(self, creature: Union[I_Creature, Iterable[I_Creature]]) -> None:
        if isinstance(creature, (list, tuple)):
            for c in creature:
                self.creatures[c.name] = c
            return
        self.creatures[creature.name] = creature

    def rm_creatures(self, creature_names: Union[str, Iterable[str]]) -> None:
        if isinstance(creature_names, (list, tuple)):
            for name in creature_names:
                if isinstance(name, str) and name in self.creatures:
                    del self.creatures[name]
            return
        if isinstance(creature_names, str) and creature_names in self.creatures:
            del self.creatures[creature_names]

    # ---------- Canonical ordering ----------

    def ordered_items(self) -> List[Tuple[str, I_Creature]]:
        """
        Return a *canonical* ordered list of (name, creature) pairs:
        - initiative DESC
        - name (natural/human) ASC for ties
        """
        return sorted(
            self.creatures.items(),
            key=lambda kv: (
                -(getattr(kv[1], "initiative", 0) or 0),
                self._natural_key(kv[0]),
            ),
        )

    def ordered_names(self) -> List[str]:
        """Convenience: just the names in canonical turn order."""
        return [name for name, _ in self.ordered_items()]

    def sort_creatures(self) -> None:
        """
        Rebuild internal dict in canonical order so any dict-iteration
        elsewhere also reflects the turn order.
        """
        sorted_items = self.ordered_items()
        self.creatures.clear()
        self.creatures.update(sorted_items)

    # ---------- Turn-walking helpers (use these in your Next/Prev) ----------

    def next_name(self, current_name: Optional[str]) -> Optional[str]:
        """
        Given the current creature name, return the *next* name in canonical order.
        Wraps around to the first entry. If current is None or not found,
        returns the first entry (or None if empty).
        """
        names = self.ordered_names()
        if not names:
            return None
        try:
            idx = names.index(current_name) if current_name in names else -1
        except ValueError:
            idx = -1
        return names[(idx + 1) % len(names)]

    def prev_name(self, current_name: Optional[str]) -> Optional[str]:
        """
        Given the current creature name, return the *previous* name in canonical order.
        Wraps around to the last entry. If current is None or not found,
        returns the last entry (or None if empty).
        """
        names = self.ordered_names()
        if not names:
            return None
        try:
            idx = names.index(current_name) if current_name in names else 0
        except ValueError:
            idx = 0
        return names[(idx - 1) % len(names)]

    # ---------- Setters ----------

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
