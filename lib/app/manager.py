from typing import Dict, Union, Iterable, Any, List, Tuple, Optional
from app.creature import I_Creature
import re


class CreatureManager:
    def __init__(self):
        self.creatures: Dict[str, I_Creature] = {}

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
        Canonical order:
        - WITH initiative (positive integer) first, initiative DESC
        - WITHOUT initiative (None, empty, 0, or -1) after, name (natural/human) ASC
        """
        def _normalized_initiative(c: I_Creature) -> Optional[int]:
            init = getattr(c, "initiative", None)
            if init in (None, "", -1):
                return None
            try:
                init_value = int(init)
            except (TypeError, ValueError):
                return None
            if init_value <= 0:
                return None
            return init_value

        def _sort_key(kv: Tuple[str, I_Creature]) -> Tuple[int, int, List[Any]]:
            init_value = _normalized_initiative(kv[1])
            return (
                0 if init_value is not None else 1,  # bucket
                -(init_value or 0),                  # init DESC
                self._natural_key(kv[0]),            # name ASC
            )

        return sorted(self.creatures.items(), key=_sort_key)

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
