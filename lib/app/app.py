from typing import Dict, Any, List, Optional
import json, os, re, sys
from dotenv import load_dotenv

from PyQt5.QtWidgets import(
   QDialog, QMessageBox,
    QApplication, QInputDialog, QLineEdit
) 
from PyQt5.QtGui import (
        QPixmap, QFont, QPixmapCache
)
from PyQt5.QtCore import Qt, QTimer
from app.creature import (
    I_Creature, Player, Monster, CreatureType
)
from app.save_json import GameState
from app.manager import CreatureManager
from app.storage_api import StorageAPI
from app.config import get_storage_api_base, use_storage_api_only, get_config_path
from app.player_view_server import PlayerViewServer
from app.bridge_client import BridgeClient
from ui.windows import (
    AddCombatantWindow, RemoveCombatantWindow, BuildEncounterWindow
)
from ui.load_encounter_window import LoadEncounterWindow
from ui.update_characters import UpdateCharactersWindow
from ui.death_saves_dialog import DeathSavesDialog
from ui.enter_initiatives_dialog import EnterInitiativesDialog

load_dotenv(get_config_path(".env"), override=False)
load_dotenv(override=False)

class Application:

    def __init__(self):
        # Legacy counters still used by your save/load flows
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        self.tracking_by_name = True  # use name-based tracking for stability
        self.base_dir = os.path.dirname(__file__)

        # New stable navigation state
        self.turn_order: List[str] = []   # authoritative order (by init desc, name asc)
        self.current_idx: int = 0         # pointer into turn_order
        self.current_creature_name: Optional[str] = None

        # Keep this for compatibility with other methods that reference it,
        # but we will manage it via build_turn_order()
        self.sorted_creatures: List[Any] = []

        self.image_cache: Dict[str, bytes] = {}

        self.boolean_fields = {
            '_action': 'set_creature_action',
            '_bonus_action': 'set_creature_bonus_action',
            '_reaction': 'set_creature_reaction'
            # '_object_interaction': 'set_creature_object_interaction'
        }
        
        self.player_view_live = True
        self.player_view_snapshot: Optional[Dict[str, Any]] = None
        self.player_view_server = PlayerViewServer(self.get_player_view_payload)
        self.player_view_server.start()

        self.bridge_client = BridgeClient.from_env()
        self.bridge_snapshot: Optional[Dict[str, Any]] = None
        self.bridge_timer: Optional[QTimer] = None
        self.bridge_combatants_by_name: Dict[str, List[Dict[str, Any]]] = {}

        self.player_view_live = True
        self.player_view_snapshot: Optional[Dict[str, Any]] = None
        self.player_view_server = PlayerViewServer(self.get_player_view_payload)
        self.player_view_server.start()

        # --- Storage API only mode ---
        self.storage_api: Optional[StorageAPI] = None
        self.storage_api_warning: Optional[str] = None
        if use_storage_api_only():
            base = get_storage_api_base()
            if not base:
                self.storage_api_warning = (
                    "USE_STORAGE_API_ONLY is enabled, but STORAGE_API_BASE is missing.\n\n"
                    "Either set STORAGE_API_BASE (e.g., http://127.0.0.1:8000) or remove "
                    "USE_STORAGE_API_ONLY to use local files"
                )
            else:
                # self._log(f"[INFO] Using Storage API at {base}.")
                self.storage_api = StorageAPI(base)

    def start_bridge_polling(self) -> None:
        if not self.bridge_client.enabled:
            print("[Bridge] BRIDGE_TOKEN is not set; bridge sync is disabled.")
            return
        if self.bridge_timer is None:
            self.bridge_timer = QTimer(self)
            self.bridge_timer.timeout.connect(self.refresh_bridge_state)
            self.bridge_timer.start(5000)
        self.refresh_bridge_state()

    def refresh_bridge_state(self) -> None:
        try:
            snapshot = self.bridge_client.fetch_state()
        except Exception as exc:
            print(f"[Bridge] Failed to fetch state: {exc}")
            return
        if snapshot is None:
            return
        self.bridge_snapshot = snapshot
        combatants = snapshot.get("combatants", []) if isinstance(snapshot, dict) else []
        self.bridge_combatants_by_name = self._index_bridge_combatants(combatants)
        self._apply_bridge_snapshot(snapshot)
        world = snapshot.get("world") if isinstance(snapshot, dict) else None
        print(
            f"[Bridge] Snapshot loaded world={world!r} combatants={len(combatants)}"
        )

    def _apply_bridge_snapshot(self, snapshot: Dict[str, Any]) -> None:
        if not getattr(self, "manager", None) or not getattr(self.manager, "creatures", None):
            return
        if not isinstance(snapshot, dict):
            return
        combatants = snapshot.get("combatants", [])
        if not isinstance(combatants, list):
            return

        added_combatants = self._ensure_foundry_combatants_present(combatants)
        updated_initiative = False
        updated_active = False
        for creature_name, creature in self.manager.creatures.items():
            combatant = self._resolve_bridge_combatant(creature_name)
            if not combatant:
                continue
            initiative = combatant.get("initiative")
            if initiative is not None and initiative != getattr(creature, "initiative", None):
                creature.initiative = initiative
                updated_initiative = True

            setattr(creature, "foundry_combatant_id", combatant.get("combatantId"))
            setattr(creature, "foundry_token_id", combatant.get("tokenId"))
            setattr(creature, "foundry_actor_id", combatant.get("actorId"))

            effects = combatant.get("effects", [])
            if isinstance(effects, list):
                setattr(creature, "foundry_effects", effects)
                labels = [effect.get("label") for effect in effects if effect.get("label")]
                creature.conditions = labels

        combat = snapshot.get("combat", {}) if isinstance(snapshot, dict) else {}
        if isinstance(combat, dict):
            round_value = combat.get("round")
            if isinstance(round_value, int):
                self.round_counter = round_value
            active = combat.get("activeCombatant")
            active_name = None
            if isinstance(active, dict):
                active_id = active.get("combatantId")
                if active_id:
                    for creature in self.manager.creatures.values():
                        if getattr(creature, "foundry_combatant_id", None) == active_id:
                            active_name = creature.name
                            break
                if not active_name:
                    active_label = active.get("name")
                    if active_label:
                        active_name = active_label
            if active_name and active_name != getattr(self, "current_creature_name", None):
                self.current_creature_name = active_name
                updated_active = True

        if added_combatants:
            self.build_turn_order()
            self.update_table()
            self.pop_lists()
        elif updated_initiative or updated_active:
            self.build_turn_order()
        else:
            self.update_active_ui()

    def _ensure_foundry_combatants_present(
        self, combatants: List[Dict[str, Any]]
    ) -> bool:
        if not getattr(self, "manager", None) or not getattr(self.manager, "creatures", None):
            return False

        def _normalize_id(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            return str(value)

        existing_by_combatant_id: Dict[str, I_Creature] = {}
        existing_by_token_id: Dict[str, I_Creature] = {}
        existing_by_actor_id: Dict[str, I_Creature] = {}
        unmapped_by_name: Dict[str, List[I_Creature]] = {}
        for creature in self.manager.creatures.values():
            combatant_id = _normalize_id(
                getattr(creature, "foundry_combatant_id", None)
                or getattr(creature, "combatant_id", None)
            )
            token_id = _normalize_id(
                getattr(creature, "foundry_token_id", None)
                or getattr(creature, "token_id", None)
            )
            actor_id = _normalize_id(
                getattr(creature, "foundry_actor_id", None)
                or getattr(creature, "actor_id", None)
            )
            if combatant_id:
                existing_by_combatant_id[combatant_id] = creature
            if token_id:
                existing_by_token_id[token_id] = creature
            if actor_id:
                existing_by_actor_id[actor_id] = creature
            if not combatant_id and not token_id and not actor_id:
                name_key = self._normalize_bridge_name(getattr(creature, "name", ""))
                if name_key:
                    unmapped_by_name.setdefault(name_key, []).append(creature)

        added = False
        for combatant in combatants:
            if not isinstance(combatant, dict):
                continue
            name = combatant.get("name") or ""
            name_key = self._normalize_bridge_name(str(name))
            combatant_id = _normalize_id(combatant.get("combatantId"))
            token_id = _normalize_id(combatant.get("tokenId"))
            actor_id = _normalize_id(combatant.get("actorId"))

            existing = None
            if combatant_id and combatant_id in existing_by_combatant_id:
                existing = existing_by_combatant_id[combatant_id]
            elif token_id and token_id in existing_by_token_id:
                existing = existing_by_token_id[token_id]
            elif actor_id and actor_id in existing_by_actor_id:
                existing = existing_by_actor_id[actor_id]
            elif name_key and unmapped_by_name.get(name_key):
                existing = unmapped_by_name[name_key].pop(0)

            if existing:
                if combatant_id and not getattr(existing, "foundry_combatant_id", None):
                    setattr(existing, "foundry_combatant_id", combatant_id)
                if token_id and not getattr(existing, "foundry_token_id", None):
                    setattr(existing, "foundry_token_id", token_id)
                if actor_id and not getattr(existing, "foundry_actor_id", None):
                    setattr(existing, "foundry_actor_id", actor_id)
                continue

            if not name:
                continue

            creature = I_Creature(_name=str(name))
            if combatant_id:
                setattr(creature, "foundry_combatant_id", combatant_id)
            if token_id:
                setattr(creature, "foundry_token_id", token_id)
            if actor_id:
                setattr(creature, "foundry_actor_id", actor_id)

            initiative = combatant.get("initiative")
            if initiative is not None:
                creature.initiative = initiative

            hp = combatant.get("hp", {})
            if isinstance(hp, dict):
                curr_hp = hp.get("value")
                max_hp = hp.get("max")
                if curr_hp is not None:
                    try:
                        creature.curr_hp = int(curr_hp)
                    except (TypeError, ValueError):
                        pass
                if max_hp is not None:
                    try:
                        creature.max_hp = int(max_hp)
                    except (TypeError, ValueError):
                        pass

            effects = combatant.get("effects", [])
            if isinstance(effects, list):
                setattr(creature, "foundry_effects", effects)
                labels = [effect.get("label") for effect in effects if effect.get("label")]
                creature.conditions = labels

            base_name = creature.name
            counter = 1
            while creature.name in self.manager.creatures:
                creature.name = f"{base_name}_{counter}"
                counter += 1

            self.manager.add_creature(creature)
            added = True

            if combatant_id:
                existing_by_combatant_id[combatant_id] = creature
            if token_id:
                existing_by_token_id[token_id] = creature
            if actor_id:
                existing_by_actor_id[actor_id] = creature

        return added

    # -----------------------
    # Core ordering utilities
    # -----------------------
    def _creature_list_sorted(self) -> List[Any]:
        """Deterministic order from the manager: initiative DESC, then natural name ASC."""
        if not getattr(self, "manager", None) or not getattr(self.manager, "creatures", None):
            return []

        # Preferred: use the manager’s canonical ordering if available
        if hasattr(self.manager, "ordered_items"):
            try:
                ordered = self.manager.ordered_items()  # List[Tuple[str, I_Creature]]
                return [cr for _, cr in ordered]
            except Exception:
                pass  # fall back below if something unexpected happens

        # Fallback: compute using manager’s _natural_key without duplicating it here
        creatures = list(self.manager.creatures.values())

        def _init(c):
            v = getattr(c, "initiative", 0)
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(v))
                except Exception:
                    return 0

        def _nm_key(c):
            name = getattr(c, "name", "") or ""
            if hasattr(self.manager, "_natural_key"):
                return self.manager._natural_key(name)
            # last-resort basic tie-break (shouldn’t be hit if manager has _natural_key)
            return [name.lower()]

        creatures.sort(key=lambda c: (-_init(c), _nm_key(c)))
        return creatures

    def _normalize_bridge_name(self, name: str) -> str:
        return re.sub(r"\s+", " ", name or "").strip().casefold()

    def _index_bridge_combatants(
        self, combatants: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        indexed: Dict[str, List[Dict[str, Any]]] = {}
        for combatant in combatants:
            if not isinstance(combatant, dict):
                continue
            name = combatant.get("name")
            if not name:
                continue
            key = self._normalize_bridge_name(str(name))
            if not key:
                continue
            indexed.setdefault(key, []).append(combatant)
        return indexed

    def _resolve_bridge_combatant(self, creature_name: str) -> Optional[Dict[str, Any]]:
        if not creature_name:
            return None

        key = self._normalize_bridge_name(creature_name)
        if not key:
            return None

        # 1) Exact key match (current behavior)
        matches = self.bridge_combatants_by_name.get(key, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"[Bridge] Multiple combatants match '{creature_name}', skipping command enqueue.")
            return None

        # 2) Fallback: prefix/contains match against indexed keys
        # Example: "chitra" should match "chitraya" or "chitra-ya" after normalization.
        candidate_lists = []
        for indexed_key, lst in (self.bridge_combatants_by_name or {}).items():
            if not indexed_key:
                continue
            if indexed_key.startswith(key) or key.startswith(indexed_key) or key in indexed_key:
                if lst:
                    candidate_lists.append(lst)

        # Flatten + de-dup by combatantId/tokenId
        flat: List[Dict[str, Any]] = []
        seen = set()
        for lst in candidate_lists:
            for c in lst:
                if not isinstance(c, dict):
                    continue
                uniq = c.get("combatantId") or c.get("tokenId") or c.get("actorId") or id(c)
                if uniq in seen:
                    continue
                seen.add(uniq)
                flat.append(c)

        if len(flat) == 1:
            print(f"[Bridge] Fuzzy matched '{creature_name}' -> '{flat[0].get('name')}'")
            return flat[0]

        if len(flat) > 1:
            print(f"[Bridge] Fuzzy match ambiguous for '{creature_name}' ({len(flat)} candidates), skipping.")
            return None

        return None

    def _enqueue_bridge_set_hp(self, creature_name: str, hp: int) -> None:
        if not self.bridge_client.enabled:
            return
        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)
        token_id = (
            getattr(creature, "token_id", None)
            or getattr(creature, "foundry_token_id", None)
        )
        actor_id = (
            getattr(creature, "actor_id", None)
            or getattr(creature, "foundry_actor_id", None)
        )
        if not token_id:
            combatant = self._resolve_bridge_combatant(creature_name)
            if not combatant:
                print(f"[Bridge] No combatant match for '{creature_name}', skipping.")
                return
            token_id = combatant.get("tokenId")
            actor_id = combatant.get("actorId")
        if not token_id:
            print(f"[Bridge] Missing tokenId for '{creature_name}', skipping.")
            return
        print(f"[Bridge] enqueue set_hp name={creature_name!r} hp={hp}")
        self.bridge_client.enqueue_set_hp(
            token_id=str(token_id), hp=int(hp), actor_id=str(actor_id) if actor_id else None
        )

    def _enqueue_bridge_set_initiative(self, creature_name: str, initiative: int) -> None:
        if not getattr(self, "bridge_client", None):
            print("[Bridge][DBG] bridge_client missing; cannot send set_initiative")
            return

        if not self.bridge_client.enabled:
            print("[Bridge][DBG] bridge_client disabled; skipping set_initiative")
            return

        # 1) Try to get ids from creature first
        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)

        token_id = (
            getattr(creature, "token_id", None)
            or getattr(creature, "foundry_token_id", None)
        )
        actor_id = (
            getattr(creature, "actor_id", None)
            or getattr(creature, "foundry_actor_id", None)
        )
        combatant_id = (
            getattr(creature, "combatant_id", None)
            or getattr(creature, "foundry_combatant_id", None)
        )

        # 2) Fallback to bridge snapshot match (preferred for initiative: combatantId)
        if not combatant_id:
            combatant = self._resolve_bridge_combatant(creature_name)
            if not combatant:
                print(f"[Bridge][DBG] no combatant match for {creature_name!r}; skipping set_initiative")
                return
            combatant_id = combatant.get("combatantId")
            token_id = token_id or combatant.get("tokenId")
            actor_id = actor_id or combatant.get("actorId")

        if not combatant_id and not token_id and not actor_id:
            print(f"[Bridge][DBG] missing all ids for {creature_name!r}; skipping set_initiative")
            return

        # 3) Send command
        print(
            "[Bridge] enqueue set_initiative "
            f"name={creature_name!r} initiative={initiative!r} "
            f"combatant_id={combatant_id!r} token_id={token_id!r} "
            f"actor_id={actor_id!r} post=attempt"
        )
        self.bridge_client.send_set_initiative(
            initiative=int(initiative),
            combatant_id=str(combatant_id) if combatant_id else None,
            token_id=str(token_id) if token_id else None,
            actor_id=str(actor_id) if actor_id else None,
        )

    def _enqueue_bridge_condition_delta(
        self,
        creature: I_Creature,
        added: List[str],
        removed: List[str],
    ) -> None:
        if not self.bridge_client.enabled:
            return
        if not added and not removed:
            return
        token_id = (
            getattr(creature, "foundry_token_id", None)
            or getattr(creature, "token_id", None)
        )
        actor_id = (
            getattr(creature, "foundry_actor_id", None)
            or getattr(creature, "actor_id", None)
        )
        if not token_id and not actor_id:
            combatant = self._resolve_bridge_combatant(getattr(creature, "name", ""))
            if combatant:
                token_id = combatant.get("tokenId")
                actor_id = combatant.get("actorId")
        if not token_id and not actor_id:
            print(
                f"[Bridge] Missing tokenId/actorId for condition sync '{getattr(creature, 'name', '')}'"
            )
            return
        if added:
            print(
                f"[Bridge] enqueue add_condition name={getattr(creature, 'name', '')!r} added={added}"
            )
        if removed:
            print(
                f"[Bridge] enqueue remove_condition name={getattr(creature, 'name', '')!r} removed={removed}"
            )
        effects = getattr(creature, "foundry_effects", []) or []
        effect_ids_by_label = {
            effect.get("label"): effect.get("id")
            for effect in effects
            if isinstance(effect, dict) and effect.get("label") and effect.get("id")
        }
        for label in added:
            self.bridge_client.send_add_condition(
                label=label,
                token_id=str(token_id) if token_id else None,
                actor_id=str(actor_id) if actor_id else None,
            )
        for label in removed:
            effect_id = effect_ids_by_label.get(label)
            self.bridge_client.send_remove_condition(
                # For token-status removal, label is the reliable key. Always include it.
                label=label,
                # Keep effect_id optional for backward compatibility (can be None).
                effect_id=str(effect_id) if effect_id else None,
                token_id=str(token_id) if token_id else None,
                actor_id=str(actor_id) if actor_id else None,
            )

    def _enqueue_bridge_turn_command(self, direction: str) -> None:
        if not getattr(self, "bridge_client", None):
            return
        if not self.bridge_client.enabled:
            return
        if direction == "next":
            self.bridge_client.send_next_turn()
        elif direction == "prev":
            self.bridge_client.send_prev_turn()

    def build_turn_order(self) -> None:
        """
        Rebuild the authoritative turn order when creatures/initiatives change.
        Also refresh self.sorted_creatures for any legacy code that reads it.
        """
        # Prefer manager’s canonical ordering
        if hasattr(self.manager, "ordered_items"):
            ordered = self.manager.ordered_items()  # List[Tuple[str, I_Creature]]
            creatures = [cr for _, cr in ordered]
            names = [nm for nm, _ in ordered]
        else:
            creatures = self._creature_list_sorted()
            names = [getattr(c, "name", "") for c in creatures if getattr(c, "name", "")]

        self.sorted_creatures = creatures[:]  # keep legacy list in sync
        self.turn_order = names

        if not self.turn_order:
            self.current_idx = 0
            self.current_creature_name = None
            self.update_active_ui()
            return

        # Preserve pointer by name if possible
        if getattr(self, "current_creature_name", None) in self.turn_order:
            self.current_idx = self.turn_order.index(self.current_creature_name)
        else:
            if getattr(self, "current_idx", 0) >= len(self.turn_order):
                self.current_idx = max(0, len(self.turn_order) - 1)
            self.current_creature_name = self.turn_order[self.current_idx]

        self.update_active_ui()

    def active_name(self) -> Optional[str]:
        if not getattr(self, "turn_order", None):
            return None
        if not self.turn_order:
            return None
        self.current_idx = max(0, min(getattr(self, "current_idx", 0), len(self.turn_order) - 1))
        return self.turn_order[self.current_idx]

    def get_player_view_payload(self) -> Dict[str, Any]:
        if not self.player_view_live and self.player_view_snapshot is not None:
            return self.player_view_snapshot

        try:
            payload = self._build_player_view_payload()
        except Exception as exc:
            print(f"[PlayerView] Failed to build payload: {exc}")
            payload = {
                "round": self.round_counter,
                "time": self.time_counter,
                "current_name": None,
                "current_hidden": False,
                "combatants": [],
                "live": self.player_view_live,
            }
        if not self.player_view_live:
            self.player_view_snapshot = payload
        return payload

    def set_player_view_paused(self, paused: bool) -> None:
        if paused and self.player_view_live:
            self.player_view_live = False
            self.player_view_snapshot = self.get_player_view_payload()
            return
        if not paused and not self.player_view_live:
            self.player_view_live = True
            self.player_view_snapshot = None

    def _build_player_vew_payload(self) -> Dict[str, Any]:
        return self._build_player_view_payload()

    def _build_player_view_payload(self) -> Dict[str, Any]:
        if not getattr(self, "manager", None) or not getattr(self.manager, "creatures", None):
            return {
                "round": self.round_counter,
                "time": self.time_counter,
                "current_name": None,
                "current_hidden": False,
                "combatants": [],
                "live": self.player_view_live,
            }
        hide_downed = os.getenv("PLAYER_VIEW_HIDE_DOWNED", "0").strip().lower() not in (
            "",
            "0",
            "false",
            "no",
        )
        active_name = self.active_name()
        active_creature = self.manager.creatures.get(active_name) if active_name else None
        active_visible = bool(getattr(active_creature, "player_visible", False)) if active_creature else False
        active_is_monster = isinstance(active_creature, Monster) if active_creature else False
        active_curr_hp = getattr(active_creature, "curr_hp", None) if active_creature else None
        try:
            active_curr_hp_value = int(active_curr_hp)
        except (TypeError, ValueError):
            active_curr_hp_value = None
        active_downed = (
            active_curr_hp_value is not None and active_curr_hp_value >= 0 and active_curr_hp_value <= 0
        )
        active_hidden_by_downed = hide_downed and active_is_monster and active_downed
        current_hidden = bool(active_creature) and (not active_visible or active_hidden_by_downed)

        if hasattr(self.manager, "ordered_items"):
            ordered = self.manager.ordered_items()
        else:
            ordered = sorted(
                self.manager.creatures.items(),
                key=lambda item: getattr(item[1], "initiative", 0),
                reverse=True,
            )

        combatants = []
        for _, creature in ordered:
            if not bool(getattr(creature, "player_visible", False)):
                continue
            is_monster = isinstance(creature, Monster)
            curr_hp = getattr(creature, "curr_hp", None)
            try:
                curr_hp_value = int(curr_hp)
            except (TypeError, ValueError):
                curr_hp_value = None
            downed = curr_hp_value is not None and curr_hp_value >= 0 and curr_hp_value <= 0 
            if hide_downed and is_monster and downed:
                continue
            combatants.append(
                {
                    "name": getattr(creature, "name", ""),
                    "initiative": getattr(creature, "initiative", ""),
                    "conditions": ", ".join(getattr(creature, "conditions", []) or []),
                    "public_notes": getattr(creature, "public_notes", "") or "",
                    "downed": downed,
                }
            )

        return {
            "round": self.round_counter,
            "time": self.time_counter,
            "current_name": active_name if active_visible and not active_hidden_by_downed else None,
            "current_hidden": current_hidden,
            "combatants": combatants,
            "live": self.player_view_live,
        }

    # ----------------
    # JSON Manipulation
    # ----------------
    def init_players(self):
        filename = "players.json"
        try:
            self.load_file_to_manager(filename, self.manager)
            # After loading, refresh the table model and update UI
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            # Rebuild order after data load
            self.build_turn_order()
            self.statblock.clear()
        except Exception as e:
            print(f"[ERROR] Failed to initialize players: {e}")

    def load_state(self):
        filename = "last_state.json"
        self.load_file_to_manager(filename, self.manager)
        if self.manager.creatures:
            self.table_model.set_fields_from_sample()
            self.build_turn_order()

    def save_encounter_to_storage(self, filename: str, description: str = ""):
        if not self.storage_api:
            raise RuntimeError("Storage API not configured.")
        # Prepare state
        state = GameState()
        state.players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
        state.monsters = [c for c in self.manager.creatures.values() if isinstance(c, Monster)]
        state.current_turn = self.current_turn
        state.round_counter = self.round_counter
        state.time_counter = self.time_counter
        payload = state.to_dict()
        # optional: add a description field for your server
        # if description:
            # payload["_meta"] = {"description": description}
        if not filename.endswith(".json"):
            filename += ".json"
        self.storage_api.put_json(filename, payload)
        return {"key": filename}

    def save_as_encounter(self):
        if not getattr(self, "storage_api", None):
            QMessageBox.critical(
                self,
                "Storage Not Configured",
                "Storage API is not configured.\n\nSet USE_STORAGE_API_ONLY=1 and STORAGE_API_BASE in your .env."
            )
            return

        # ----- Ask for filename -----
        filename, ok = QInputDialog.getText(
            self, "Save Encounter As", "Enter filename:", QLineEdit.Normal
        )
        if not ok or not filename.strip():
            return
        filename = filename.strip().replace(" ", "_")
        if not filename.endswith(".json"):
            filename += ".json"

        # ----- Optional description -----
        description, _ = QInputDialog.getText(
            self, "Description", "Optional description:", QLineEdit.Normal
        )

        # ----- Build state payload -----
        try:
            state = GameState()
            state.players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
            state.monsters = [c for c in self.manager.creatures.values() if isinstance(c, Monster)]
            state.current_turn = getattr(self, "current_turn", 0)
            state.round_counter = getattr(self, "round_counter", 1)
            state.time_counter = getattr(self, "time_counter", 0)

            payload = state.to_dict()
            # if description:
                # payload["_meta"] = {"description": description}

            # ----- Save to Storage -----
            self.storage_api.put_json(filename, payload)

            QMessageBox.information(
                self,
                "Saved",
                f"Saved to Storage as key:\n{filename}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def save_state(self):
        # --- Build current game state ---
        state = GameState()
        state.players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
        state.monsters = [c for c in self.manager.creatures.values() if isinstance(c, Monster)]
        state.current_turn = getattr(self, "current_turn", 0)
        state.round_counter = getattr(self, "round_counter", 1)
        state.time_counter = getattr(self, "time_counter", 0)

        save_data = state.to_dict()
        filename = "last_state.json"
        description = "Auto-saved state from initiative tracker"

        try:
            # --- Preferred: save to Storage API ---
            if getattr(self, "storage_api", None):
                # Optional metadata block
                # save_data["_meta"] = {"description": description}
                self.storage_api.put_json(filename, save_data)
                print("[INFO] Saved state to Storage API as last_state.json")
            else:
                # --- Fallback: save to local file ---
                file_path = self.get_data_path(filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                print("[INFO] Saved state locally as last_state.json")
        except Exception as e:
            print(f"[ERROR] Failed to save state: {e}")

    def load_file_to_manager(self, file_name, manager, monsters=False, merge=False, prompt_for_initiatives: bool = False):
        state = None

        try:
            # --- Decide source: Storage key vs local file ---
            file_path = self.get_data_path(file_name)

            if getattr(self, "storage_api", None) and not os.path.exists(file_path):
                # Treat file_name as a Storage key
                raw = self.storage_api.get_json(file_name)
                if raw is None:
                    self._log(f"[WARN] Storage key not found: {file_name}")
                    return
                # Run through your custom decoder
                state = json.loads(json.dumps(raw), object_hook=self.custom_decoder)
            else:
                # Local file fallback (dev/offline)
                if not os.path.exists(file_path):
                    self._log(f"[WARN] Local file not found: {file_path}")
                    return
                with open(file_path, "r", encoding="utf-8") as f:
                    state = json.load(f, object_hook=self.custom_decoder)

        except Exception as e:
            self._log(f"[ERROR] Failed to load '{file_name}': {e}")
            return

        # ----- Extract lists -----
        players = state.get("players", [])
        monsters_list = state.get("monsters", [])

        # ===== Encounter-only add (not merge/replace): only add monsters =====
        if monsters and not merge:
            for creature in monsters_list:
                manager.add_creature(creature)
            manager.sort_creatures()
            self.build_turn_order()
            self.update_table()
            self.pop_lists()
            self._maybe_prompt_enter_initiatives(manager, prompt_for_initiatives and not merge)
            return

        # ===== Merge path: add monsters with unique names; keep counters/active =====
        if merge:
            preserved_active = getattr(self, "current_creature_name", None)

            self.init_tracking_mode(True)
            for creature in monsters_list:
                name = creature.name
                counter = 1
                while name in manager.creatures:
                    name = f"{creature.name}_{counter}"
                    counter += 1
                creature.name = name
                manager.add_creature(creature)

            manager.sort_creatures()
            self.build_turn_order()

            if preserved_active in getattr(self, "turn_order", []):
                self.current_creature_name = preserved_active
                self.current_idx = self.turn_order.index(preserved_active)

            self.update_table()
            self.pop_lists()
            self._maybe_prompt_enter_initiatives(manager, prompt_for_initiatives and not merge)
            return

        # ===== Full replace (default): clear, load players+monsters, apply counters =====
        pending_inits: List[Player] = []
        manager.creatures.clear()
        for creature in players + monsters_list:
            # Skip inactive players on full replace
            if isinstance(creature, Player) and not getattr(creature, "active", True):
                continue
            manager.add_creature(creature)
            if isinstance(creature, Player) and self._player_needs_initiative(creature):
                pending_inits.append(creature)

        if manager is self.manager:
            self.current_turn = state.get("current_turn", 0)
            self.round_counter = state.get("round_counter", 1)
            self.time_counter = state.get("time_counter", 0)

        if pending_inits and prompt_for_initiatives:
            self._prompt_missing_initiatives(pending_inits)

        manager.sort_creatures()

        # Build order and set initial current creature if needed
        self.build_turn_order()
        if self.turn_order:
            self.current_creature_name = self.turn_order[0]
            self.current_idx = 0
        else:
            self.current_creature_name = None
            self.current_idx = 0

        self.update_table()
        self.update_active_init()
        self.pop_lists()
        self._maybe_prompt_enter_initiatives(manager, prompt_for_initiatives and not merge)

    def _maybe_prompt_enter_initiatives(self, manager: CreatureManager, should_prompt: bool) -> None:
        """
        Optionally remind the user to fill in initiatives for a freshly loaded encounter.
        Skipped for merge flows to keep additive behavior intact.
        """
        if not should_prompt:
            return
        try:
            creatures = getattr(manager, "creatures", {}) or {}
        except Exception:
            return

        missing = []
        for name, creature in creatures.items():
            try:
                init_val = getattr(creature, "initiative", 0)
            except Exception:
                continue
            if init_val in (None, "", 0):
                missing.append(name)

        if not missing:
            return

        QMessageBox.information(
            self,
            "Enter initiatives",
            "Enter initiatives for this encounter before starting combat.",
        )

    def _player_needs_initiative(self, player: Player) -> bool:
        value = getattr(player, "initiative", None)
        if value is None:
            return True
        try:
            return int(value) <= 0 
        except Exception:
            return True

    def _prompt_missing_initiatives(self, players: List[Player]) -> None:
        if not players:
            return
        try:
            dialog = EnterInitiativesDialog(players, parent=self)
            if dialog.exec_() == QDialog.Accepted:
                entries = dialog.get_initiatives()
                for player in players:
                    if player.name in entries:
                        player.initiative = entries[player.name]
        except Exception as e:
            self._log(f"[WARN] Initiative prompt failed: {e}")

    def custom_decoder(self, data: Dict[str, Any]) -> Any:
        if '_type' in data:
            return I_Creature.from_dict(data)
        return data

    # ----------------
    # Table / UI setup
    # ----------------
    def update_table(self):
        # 1) Ensure headers/model are ready
        if not self.table_model.fields:
            self.table_model.set_fields_from_sample()
        self.table_model.refresh()
        self.table.setColumnHidden(0, True)

        # Use both the model's internal field names and the *view* model headers
        fields = list(self.table_model.fields)
        view_model = self.table.model()
        column_count = view_model.columnCount() if view_model else len(fields)

        # Helper: map a source column index to the view column index if a proxy is in use
        def to_view_col(src_col: int) -> int:
            try:
                from PyQt5.QtCore import QModelIndex, QAbstractProxyModel  # safe local import
            except Exception:
                QAbstractProxyModel = None  # type: ignore
            if view_model and QAbstractProxyModel and isinstance(view_model, QAbstractProxyModel):
                src_model = view_model.sourceModel()
                if src_model is not None:
                    try:
                        idx = src_model.index(0, src_col)
                        mapped = view_model.mapFromSource(idx)
                        if mapped.isValid():
                            return mapped.column()
                    except Exception:
                        pass
            return src_col  # assume direct view

        # 2) Hide Max HP column if present
        if "_max_hp" in fields:
            self.table.setColumnHidden(to_view_col(fields.index("_max_hp")), True)

        # 3) Always hide Movement ("M") and Object Interaction ("OI") columns
        hide_aliases = {
            "_movement", "movement", "M",
            "_object_interaction", "object_interaction", "OI"
        }
        for alias in hide_aliases:
            if alias in fields:
                self.table.setColumnHidden(to_view_col(fields.index(alias)), True)

        # 4) Detect spellcasting columns robustly (aliases + header substring "spell")
        spell_aliases = {
            "_spellbook", "spellbook", "Spellbook",
            "_spellcasting", "spellcasting", "Spellcasting",
            "_spells", "spells", "Spells"
        }

        # Collect candidate columns from fields
        spell_cols_view = set()
        for alias in spell_aliases:
            if alias in fields:
                spell_cols_view.add(to_view_col(fields.index(alias)))

        # Also scan the *view's* headers for any "spell" label (case-insensitive)
        try:
            from PyQt5.QtCore import Qt
            for c in range(column_count):
                header_text = view_model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
                if isinstance(header_text, str) and ("spell" in header_text.lower()):
                    spell_cols_view.add(c)
        except Exception:
            pass

        # 5) Decide visibility: only show if there is at least one MONSTER caster
        has_npc_spellcasters = any(
            (getattr(creature, "_type", None) == CreatureType.MONSTER) and
            bool(getattr(creature, "_spell_slots", {}) or getattr(creature, "_innate_slots", {}))
            for creature in self.manager.creatures.values()
        )

        # Apply hide/show for all detected spellcasting columns
        for c in spell_cols_view:
            self.table.setColumnHidden(c, not has_npc_spellcasters)

        # If visible, size the first spell column reasonably
        if has_npc_spellcasters and spell_cols_view:
            first = min(spell_cols_view)
            self.table.resizeColumnToContents(first)
            self.table.setColumnWidth(first, max(40, self.table.columnWidth(first)))

        # 6) Usual sizing + list refresh; do NOT reorder here
        self.adjust_table_size()
        self.pop_lists()
        self.update_active_ui()
    # Backwards-compat shim: existing code calls this frequently.
    # Now it only updates labels/highlight; it no longer resorts or changes indices.
    def update_active_init(self):
        self.update_active_ui()

    # ----------------------------
    # Active UI (no re-sorting here)
    # ----------------------------
    def update_active_ui(self) -> None:
        """
        Refresh labels/highlights only. No sorting or pointer changes here.
        Also disables the Prev button when we're at the absolute start:
        Round = 1, Time = 0, and the active index is 0 (top of the list).
        """
        name = self.active_name()  # uses self.turn_order/self.current_idx; no resorting

        # Keep current name in sync for other code paths that read it
        self.current_creature_name = name

        if hasattr(self, "_sync_conditions_panel_from_selection"):
            try:
                self._sync_conditions_panel_from_selection()
            except Exception:
                pass

        # Labels
        if hasattr(self, "active_init_label") and self.active_init_label:
            self.active_init_label.setText(f"Active: {name if name else 'None'}")

        if hasattr(self, "round_counter_label") and self.round_counter_label:
            self.round_counter_label.setText(f"Round: {self.round_counter}")

        if hasattr(self, "time_counter_label") and self.time_counter_label:
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")

        # Highlight active row in the table via the model hook (no re-sorting)
        if hasattr(self, "table_model") and self.table_model:
            if hasattr(self.table_model, "set_active_creature"):
                try:
                    self.table_model.set_active_creature(name or "")
                except Exception:
                    pass
            if hasattr(self.table_model, "refresh"):
                try:
                    self.table_model.refresh()
                except Exception:
                    pass

        # 🔒 Disable Prev at the absolute start of combat
        at_absolute_start = (
            (self.round_counter <= 1) and
            (self.time_counter <= 0) and
            (getattr(self, "current_idx", 0) == 0)
        )
        if hasattr(self, "prev_btn") and self.prev_btn:
            # Only enable Prev if we can actually go back
            self.prev_btn.setEnabled(not at_absolute_start)

    def handle_initiative_update(self):
        """
        Auto-apply initiative edits and ensure the active UI/statblock reflect the latest turn order.
        """
        if getattr(self, "_initiative_dialog_open", False):
            return
        
        self._initiative_dialog_open = True
        try:
            self.manager.sort_creatures()
            self.build_turn_order()
            if hasattr(self, "table_model") and self.table_model:
                self.table_model.refresh()
            self.update_table()
        finally:
            self._initiative_dialog_open = False

        self.update_active_init()
        active_name = self.active_name()
        if active_name:
            cr = self.manager.creatures.get(active_name)
            if cr and getattr(cr, "_type", None) == CreatureType.MONSTER:
                self.active_statblock_image(cr)

    def init_tracking_mode(self, by_name):
        self.tracking_by_name = by_name

    def adjust_table_size(self):
        screen_geometry = QApplication.desktop().availableGeometry(self)
        screen_height = screen_geometry.height()

        font_size = max(int(screen_height * 0.012), 10) if screen_height < 1440 else 18
        self.table.setFont(QFont('Arial', font_size))

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

        total_width = self.table.verticalHeader().width()
        model = self.table.model()
        if model:
            for column in range(model.columnCount()):
                self.table.resizeColumnToContents(column)
                if not self.table.isColumnHidden(column):
                    total_width += self.table.columnWidth(column)

        total_height = self.table.horizontalHeader().height()
        for row in range(model.rowCount() if model else 0):
            total_height += self.table.rowHeight(row)

        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFixedSize(total_width + 2, total_height + 2)  # ✅ extra padding for gutter

    # ============== Populate Lists ====================
    def pop_lists(self):
        self.populate_creature_list()
        self.populate_monster_list()

    def populate_creature_list(self):
        self.creature_list.clear()
        for row in range(self.table_model.rowCount()):
            creature_name = self.table_model.creature_names[row]  # Adjust based on your model's data
            self.creature_list.addItem(creature_name)

        list_height = self.creature_list.count() * self.creature_list.sizeHintForRow(0)
        list_height += self.creature_list.frameWidth() * 2
        self.creature_list.setFixedHeight(list_height)

    def populate_monster_list(self):
        self.monster_list.clear()
        unique_monster_names = set()

        for row in range(self.table_model.rowCount()):
            creature_name = self.table_model.creature_names[row]
            creature = self.manager.creatures.get(creature_name)
            
            if creature and creature._type == CreatureType.MONSTER:
                base_name = re.sub(r'\s*\d+$', '', creature_name)
                unique_monster_names.add(base_name)

        for name in unique_monster_names:
            self.monster_list.addItem(name)

        list_height = self.monster_list.count() * self.monster_list.sizeHintForRow(0)
        list_height += self.monster_list.frameWidth() * 2
        self.monster_list.setFixedHeight(list_height)

        if self.monster_list.count() == 0:
            self.hide_img.hide()
            self.show_img.hide()
            self.monster_list.hide()
        else:
            self.hide_img.show()
            self.show_img.show()
            self.monster_list.show()

    def get_base_name(self, creature):
        non_num_name = re.sub(r'\d+$', '', creature.name)
        base_name = non_num_name.strip()
        return base_name

    # ================== Edit Menu Actions =====================
    def add_combatant(self):
        self.init_tracking_mode(True)
        dialog = AddCombatantWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            for creature_data in data:
                creature = Monster(
                    name=creature_data['Name'],
                    init=creature_data['Init'],
                    max_hp=creature_data['HP'],
                    curr_hp=creature_data['HP'],
                    armor_class=creature_data['AC'],
                    spell_slots=creature_data.get("_spell_slots", {}),
                    innate_slots=creature_data.get("_innate_slots", {})
                )
                self.manager.add_creature(creature)

            # ✅ Ensure sorting + fields + stable order
            self.manager.sort_creatures()
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            self.build_turn_order()
            self.update_table()

        self.init_tracking_mode(False)
        for c in self.manager.creatures.values():
            print(c.name, c._type, c._spell_slots, c._innate_slots)

    def remove_combatant(self):
        self.init_tracking_mode(True)
        dialog = RemoveCombatantWindow(self.manager, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_creatures = dialog.get_selected_creatures()
            for name in selected_creatures:
                self.manager.rm_creatures(name)
            # Rebuild order and refresh
            self.manager.sort_creatures()
            self.build_turn_order()
            self.update_table()

            # Use current active creature for statblock (if any)
            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)
                else:
                    self.statblock.clear()
            else:
                self.statblock.clear()
        self.init_tracking_mode(False)

    # ====================== Button Logic ======================
    def next_turn(self):
        # 1) Ensure we have an order
        if not getattr(self, "turn_order", None):
            self.build_turn_order()
            if not self.turn_order:
                print("[WARNING] No creatures in encounter. Cannot advance turn.")
                return
        else:
            # 2) Keep it in sync with the manager's canonical order
            try:
                manager_names = [nm for nm, _ in self.manager.ordered_items()]
            except AttributeError:
                # Fallback if ordered_items() isn't present for some reason
                manager_names = [getattr(c, "name", "") for c in self._creature_list_sorted() if getattr(c, "name", "")]
            if self.turn_order != manager_names:
                prev = getattr(self, "current_creature_name", None)
                self.turn_order = manager_names
                if prev in self.turn_order:
                    self.current_idx = self.turn_order.index(prev)
                else:
                    self.current_idx = 0
                    self.current_creature_name = self.turn_order[0] if self.turn_order else None

        # 3) Advance pointer
        self.current_idx += 1
        wrapped = False
        if self.current_idx >= len(self.turn_order):
            self.current_idx = 0
            wrapped = True

# 4) On wrap: advance round/time and tick only existing numeric timers
        if wrapped:
            self.round_counter += 1
            self.time_counter += 6

            any_tick = False
            for cr in self.manager.creatures.values():
                st = getattr(cr, "status_time", None)
                # be robust if the table stored a string like "3"
                try:
                    st_int = int(st) if st is not None else None
                except (ValueError, TypeError):
                    st_int = None

                if st_int is not None and st_int > 0:
                    # choose one semantics; most DMs prefer "rounds remaining":
                    cr.status_time = max(0, st_int - 6)  # seconds (if that's your unit)
                    any_tick = True

            # ⬇️ make sure the table reflects the new values
            if any_tick:
                # call whichever refresh you have available
                if hasattr(self, "update_table") and callable(self.update_table):
                    self.update_table()
                elif getattr(self, "ui", None) and hasattr(self.ui, "update_table"):
                    self.ui.update_table()
                elif hasattr(self, "refresh") and callable(self.refresh):
                    self.refresh()

        # 5) Update active
        self.current_creature_name = self.active_name()
        if not self.current_creature_name:
            self.update_active_ui()
            return

        # Reset ONLY active creature's economy at THEIR turn start
        cr = self.manager.creatures[self.current_creature_name]
        if hasattr(cr, "action"):
            cr.action = False
        if hasattr(cr, "bonus_action"):
            cr.bonus_action = False
        if hasattr(cr, "object_interaction"):
            cr.object_interaction = False
        if hasattr(cr, "reaction"):
            cr.reaction = False  # False = unused in your semantics

        self.update_active_ui()
        self._maybe_prompt_death_saves(cr)

        # Monster statblock
        if getattr(cr, "_type", None) == CreatureType.MONSTER:
            self.active_statblock_image(cr)

        self._enqueue_bridge_turn_command("next")

    def prev_turn(self):
        # 1) Ensure we have an order and keep it in sync with the manager
        if not getattr(self, "turn_order", None):
            self.build_turn_order()
            if not self.turn_order:
                print("[WARNING] No creatures in encounter. Cannot go back.")
                return
        else:
            try:
                manager_names = [nm for nm, _ in self.manager.ordered_items()]
            except AttributeError:
                manager_names = [getattr(c, "name", "") for c in self._creature_list_sorted() if getattr(c, "name", "")]
            if self.turn_order != manager_names:
                prev = getattr(self, "current_creature_name", None)
                self.turn_order = manager_names
                if prev in self.turn_order:
                    self.current_idx = self.turn_order.index(prev)
                else:
                    self.current_idx = 0
                    self.current_creature_name = self.turn_order[0] if self.turn_order else None

        # 2) Hard stop at the absolute beginning of combat
        at_abs_start = (self.round_counter <= 1 and self.time_counter <= 0 and self.current_idx == 0)
        if at_abs_start:
            return

        # 3) Move pointer backward (with wrap detection)
        wrapped = False
        if self.current_idx == 0:
            self.current_idx = len(self.turn_order) - 1
            wrapped = True
        else:
            self.current_idx -= 1

        # 4) On wrap: revert round/time AND un-tick status timers
        if wrapped:
            self.round_counter = max(1, self.round_counter - 1)
            self.time_counter = max(0, self.time_counter - 6)

            any_tick = False
            for cr in self.manager.creatures.values():
                st = getattr(cr, "status_time", None)
                # Coerce robustly in case UI stored a string
                try:
                    st_int = int(st) if st is not None else None
                except (ValueError, TypeError):
                    st_int = None

                if st_int is not None and st_int >= 0:
                    cr.status_time = st_int + 6

                    any_tick = True

            # Ensure table reflects reverted values
            if any_tick:
                if hasattr(self, "update_table") and callable(self.update_table):
                    self.update_table()
                elif getattr(self, "ui", None) and hasattr(self.ui, "update_table"):
                    self.ui.update_table()
                elif hasattr(self, "refresh") and callable(self.refresh):
                    self.refresh()

        # 5) Update active selection and UI
        self.current_creature_name = self.active_name()
        self.update_active_ui()

        cr = self.manager.creatures.get(self.current_creature_name) if self.current_creature_name else None
        if cr and getattr(cr, "_type", None) == CreatureType.MONSTER:
            self.active_statblock_image(cr)

        self._enqueue_bridge_turn_command("prev")
    # ----------------
    # Path Functions
    # ----------------
    def get_image_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'images', filename)

    def get_data_path(self, filename):
        return os.path.join(self.get_data_dir(), filename)

    def get_data_dir(self):
        if getattr(sys, "frozen", False):
            data_dir = get_config_path("data")
        else:
            data_dir = os.path.join(self.get_parent_dir(), 'data')
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def get_parent_dir(self):
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.abspath(os.path.join(self.base_dir, '../../'))

    def get_extensions(self):
        return ('png', 'jpg', 'jpeg', 'gif')

    def get_image_bytes(self, filename: str) -> Optional[bytes]:
        if filename in self.image_cache:
            return self.image_cache[filename]
        if not getattr(self, "storage_api", None):
            return None
        try:
            data = self.storage_api.get_image_bytes(filename)
        except Exception as e:
            self._log(f"[WARN] Failed to fetch image '{filename}' from storage: {e}")
            return None
        if data:
            self.image_cache[filename] = data
            return data

    # -------------------------------
    # Change Manager with Table Edits
    # -------------------------------
    def manipulate_manager(self, item):
        row = item.row()
        col = item.column()
        
        try:
            creature_name = self.table.item(row, 1).data(0)  # Get creature name based on the row
        except:
            return

        # Map columns to methods
        self.column_method_mapping = {
            2: (self.manager.set_creature_init, int),
            3: (self.manager.set_creature_max_hp, int),
            4: (self.manager.set_creature_curr_hp, int),
            5: (self.manager.set_creature_armor_class, int),
            # 6: (self.manager.set_creature_movement, int),
            7: (self.manager.set_creature_action, bool),
            8: (self.manager.set_creature_bonus_action, bool),
            9: (self.manager.set_creature_reaction, bool),
            # 10: (self.manager.set_creature_object_interaction, bool),
            11: (self.manager.set_creature_notes, str),
            12: (self.manager.set_creature_status_time, int)
        }

        # Handle value change
        if creature_name in self.manager.creatures:
            if col in self.column_method_mapping:
                method, data_type = self.column_method_mapping[col]
                try:
                    if col == 12 and (item.text().strip() == "" or item.text() is None):
                        value = ""
                    else:
                        value = self.get_value(item, data_type)
                    method(creature_name, value)  # Update the creature's data
                    if col == 4:
                        print(f"[DBG] HP edit detected name={creature_name!r} raw={item.text()!r} parsed={value!r} type={type(value)}")
                        if isinstance(value, int):
                            print(f"[DBG] calling _enqueue_bridge_set_hp name={creature_name!r} hp={value}")
                            self._enqueue_bridge_set_hp(creature_name, value)
                        else:
                            print("[DBG] not int; skipping bridge hp enqueue")
                except ValueError:
                    return
        
        # Re-sort the creatures after updating any value
        self.manager.sort_creatures()
        # Rebuild stable order to reflect any initiative/name change
        self.build_turn_order()

        # Refresh the model and table view
        self.table_model.refresh()
        self.update_table()

    def get_value(self, item, data_type):
        text = item.text()
        if data_type == bool:
            return text.lower() in ['true', '1', 'yes']
        return data_type(text)
    
    # -----------
    # Image Label
    # -----------
    def update_statblock_image(self):
        selected_items = self.monster_list.selectedItems()
        if selected_items:
            monster_name = selected_items[0].text()
            self.resize_to_fit_screen(monster_name)
        else:
            self.statblock.clear()

    def active_statblock_image(self, creature_name_or_obj):
        # Backward compatibility: accept either name string or creature object
        if isinstance(creature_name_or_obj, str):
            base_name = self.get_base_name(self.manager.creatures[creature_name_or_obj])
        else:
            base_name = self.get_base_name(creature_name_or_obj)
        self.resize_to_fit_screen(base_name)

    def resize_to_fit_screen(self, base_name):
        screen_geometry = QApplication.desktop().availableGeometry(self)
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        max_width = int(screen_width * 0.4)
        max_height = int(screen_height * 0.9)

        extensions = self.get_extensions()
        for ext in extensions:
            filename = f"{base_name}.{ext}"
            image_path = self.get_image_path(filename)
            pixmap = None

            # 1) Prefer server (prevents stale local cache)
            data = self.get_image_bytes(filename)
            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data)

                # Keep local cache in sync (overwrite)
                try:
                    os.makedirs(os.path.dirname(image_path), exist_ok=True)
                    with open(image_path, "wb") as f:
                        f.write(data)
                except Exception:
                    pass

            # 2) Fallback to local file if server didn't return anything
            if (pixmap is None or pixmap.isNull()) and os.path.exists(image_path):
                pixmap = QPixmap(image_path)

            if pixmap and not pixmap.isNull():
                self.pixmap = pixmap
                scaled_pixmap = self.pixmap.scaled(
                    max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )

                # Clear Qt pixmap cache before updating display
                QPixmapCache.clear()

                self.statblock.setPixmap(scaled_pixmap)
                break

    def hide_statblock(self):
        self.statblock.hide()

    def show_statblock(self):
        self.statblock.show()

# ================= Damage/Healing ======================
    def heal_selected_creatures(self):
        self.apply_to_selected_creatures(positive=True)

    def damage_selected_creatures(self):
        self.apply_to_selected_creatures(positive=False)

    def _prompt_concentration(self, creature_name: str, damage: int) -> bool:
        """
        Ask the user if the concentration check succeeded.
        Returns True if 'Yes' was clicked, False if 'No'.
        """
        dc = max(10, damage // 2)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Concentration Check")
        msg.setText(
            f"{creature_name} took {damage} damage.\n"
            f"Concentration Save DC: {dc}\n\n"
            "Did they SUCCEED the concentration save?"
        )
        yes = msg.addButton("Yes (Succeeded)", QMessageBox.YesRole)
        no  = msg.addButton("No (Failed)", QMessageBox.NoRole)
        msg.setDefaultButton(yes)
        msg.exec_()
        return msg.clickedButton() is yes

    def _break_concentration(self, creature):
        """
        Remove the 'Concentrating' condition from the creature.
        Optionally also clear _status_time if you were using it to track a timer.
        """
        conds = set(getattr(creature, "conditions", []) or [])
        conds = {c for c in conds if str(c).strip().lower() != "concentrating"}
        creature.conditions = sorted(conds)
        
        try:
            creature.status_time = ""
        except Exception:
            setattr(creature, "_status_time", "")
 
    def _is_concentrating(self, creature) -> bool:
        conds = getattr(creature, "conditions", []) or []
        return any(str(c).strip().lower() == "concentrating" for c in conds)

    def apply_to_selected_creatures(self, positive: bool):
        try:
            value = int(self.value_input.text())
        except ValueError:
            QMessageBox.warning(self, 'Invalid Input', 'Please enter a valid number')
            return

        selected_items = self.creature_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            creature_name = item.text()
            creature = self.manager.creatures.get(creature_name)
            if not creature:
                continue

            # Snapshot pre-damage HP and concentration state
            pre_hp = creature.curr_hp

            if positive:
                creature.curr_hp += value
            else:
                creature.curr_hp -= value
                if creature.curr_hp < 0:
                    creature.curr_hp = 0

                damage_taken = max(0, pre_hp - creature.curr_hp)

                if damage_taken > 0 and self._is_concentrating(creature):
                    if creature.curr_hp <= 0:
                        self._break_concentration(creature)
                    else:
                        succeeded = self._prompt_concentration(creature_name, damage_taken)
                        if not succeeded:
                            self._break_concentration(creature)
            if creature.curr_hp != pre_hp:
                self._enqueue_bridge_set_hp(creature_name, creature.curr_hp)

        self.value_input.clear()
        self.update_table()

    # ================= Encounter Builder =====================
    def save_encounter(self):
        dialog = BuildEncounterWindow(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        data = dialog.get_data()
        metadata = dialog.get_metadata()

        filename = metadata["filename"].replace(" ", "_")
        if not filename.endswith(".json"):
            filename += ".json"
        description = metadata.get("description", "")

        # Build encounter manager with player + added monster data
        encounter_manager = CreatureManager()
        self.load_players_to_manager(encounter_manager)

        for creature_data in data:
            creature = Monster(
                name=creature_data["_name"],
                init=creature_data["_init"],
                max_hp=creature_data["_max_hp"],
                curr_hp=creature_data["_curr_hp"],
                armor_class=creature_data["_armor_class"],
                death_saves_prompt=creature_data.get("_death_saves_prompt", False),
                spell_slots=creature_data.get("_spell_slots", {}),
                innate_slots=creature_data.get("_innate_slots", {})
            )
            encounter_manager.add_creature(creature)

        # Save state
        state = GameState()
        state.players = [c for c in encounter_manager.creatures.values() if isinstance(c, Player)]
        state.monsters = [c for c in encounter_manager.creatures.values() if isinstance(c, Monster)]
        state.current_turn = 0
        state.round_counter = 1
        state.time_counter = 0
        payload = state.to_dict()
        # if description:
            # payload["_meta"] = {"description": description}

        try:
            if not getattr(self, "storage_api", None):
                raise RuntimeError("Storage API is not configured.")
            self.storage_api.put_json(filename, payload)
            QMessageBox.information(self, "Saved", f"Saved encounter to Storage as:\n{filename}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save encounter:\n{e}")

    def load_players_to_manager(self, manager):
        filename = "players.json"
        self.load_file_to_manager(filename, manager, monsters=False)

    # ================== Secondary Windows ======================
    def load_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file:
            self.load_file_to_manager(dialog.selected_file, self.manager, prompt_for_initiatives=True)
            # After load, use the active creature from stable order
            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)

    def merge_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file:
            self.load_file_to_manager(dialog.selected_file, self.manager, merge=True, prompt_for_initiatives=False)

            if not self.current_creature_name and self.turn_order:
                self.current_creature_name = self.turn_order[0]

            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)

    def manage_encounter_statuses(self):
        from ui.storage_status import StorageStatusWindow
        if not getattr(self, "storage_api", None):
            QMessageBox.information(self, "Unavailable", "Storage API not configured.")
            return
        dlg = StorageStatusWindow(self.storage_api, self)
        dlg.exec_()

    def delete_encounters(self):
        from ui.delete_storage import DeleteStorageWindow
        if not getattr(self, "storage_api", None):
            QMessageBox.information(self, "Unavailable", "Storage API not configured.")
            return
        dlg = DeleteStorageWindow(self.storage_api, self)
        if dlg.exec_() == QDialog.Accepted:
            # Optional: refresh any open pickers or cached lists here
            pass
    
    def manage_images(self):
        from ui.manage_images import ManageImagesWindow
        if not getattr(self, "storage_api", None):
            QMessageBox.information(self, "Unavailable", "Storage API not configured.")
            return
        dlg = ManageImagesWindow(self.storage_api, self)
        if dlg.exec_() == QDialog.Accepted and getattr(dlg, "updated", False):
            self.image_cache.clear()

    def create_or_update_characters(self):
        dialog = UpdateCharactersWindow(self)
        dialog.exec_()

    def on_commit_data(self, editor):
        # Defer until after the delegate commits into the model (setData has run).
        QTimer.singleShot(0, self._after_commit_data)

    def _after_commit_data(self):
        self.manager.sort_creatures()
        # Keep stable order in sync after edits
        self.build_turn_order()
        self.table_model.refresh()
        self.update_table()
        self.update_active_ui()
        self.table.clearSelection()

    def _maybe_prompt_death_saves(self, creature):
        """
        Prompt for Players at 0 HP (always) and Monsters when enabled.
        """
        try:
            from app.creature import CreatureType
            creature_type = getattr(creature, "_type", None)
            if creature_type == CreatureType.PLAYER:
                pass
            elif creature_type == CreatureType.MONSTER:
                if not bool(getattr(creature, "_death_saves_prompt", False)):
                    return
        except Exception:
            return

        try:
            if int(getattr(creature, "curr_hp", -1)) != 0:
                return
        except Exception:
            return

        # Already stable or dead? Then don't pop.
        succ = int(getattr(creature, "_death_successes", 0) or 0)
        fail = int(getattr(creature, "_death_failures", 0) or 0)
        stable = bool(getattr(creature, "_death_stable", False))

        if stable or fail >= 3:
            return

        dlg = DeathSavesDialog(creature, parent=self)
        dlg.exec_()

        # If they became stable or dead, you may want to refresh the table
        try:
            if hasattr(self, "update_table"):
                self.update_table()
            elif hasattr(self, "table_model"):
                self.table_model.refresh()
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        """Lightweight logger used throughout the app."""
        print(msg)
