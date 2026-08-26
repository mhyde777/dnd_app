from typing import Dict, Any, List, Optional
import fnmatch, json, os, re, sys, threading
from dotenv import load_dotenv

from PyQt5.QtWidgets import (
    QDialog, QMessageBox, QApplication, QInputDialog, QLineEdit, QHeaderView,
    QListWidgetItem,
)
from PyQt5.QtGui import (
        QPixmap, QFont
)
from PyQt5.QtCore import Qt, QTimer
from app.creature import (
    I_Creature, Player, Monster, CreatureType
)
from app.save_json import GameState
from app.manager import CreatureManager
from app.storage_api import StorageAPI
from app import settings as app_settings
from app.config import (
    bridge_stream_enabled,
    get_storage_api_base,
    get_config_path,
    get_local_data_dir,
    foundry_bridge_enabled,
    local_bridge_enabled,
    use_storage_api_only,
)
from app.app_log import get_logger
from app.bridge_client import BridgeClient
from app.local_bridge_server import LocalBridgeServer
from ui.notifications import report_error, report_warning, toast
from ui.windows import (
    AddCombatantWindow, RemoveCombatantWindow, BuildEncounterWindow
)
from ui.load_encounter_window import LoadEncounterWindow
from ui.update_characters import UpdateCharactersWindow
from ui.death_saves_dialog import DeathSavesDialog
from ui.enter_initiatives_dialog import EnterInitiativesDialog

load_dotenv(get_config_path(".env"), override=False)

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

        # Key of the PC group currently loaded, or None when the party came from
        # the default players.json roster. The character editor saves back here,
        # and Initialize reloads it. Persisted so switching campaigns survives a
        # restart instead of silently reverting to the default roster.
        restored_group = app_settings.get(self.ACTIVE_PC_GROUP_SETTING)
        self.active_pc_group: Optional[str] = (
            restored_group if isinstance(restored_group, str) and restored_group else None
        )

        # PC-group-vs-Foundry mismatch prompt state. Snapshots arrive every few
        # seconds, so the check is keyed on the set of Foundry PC names and each
        # distinct party is only ever evaluated (and prompted about) once.
        self._pc_group_check_seen: set = set()
        self._pc_group_check_dismissed: set = set()
        self._pc_group_prompt_open: bool = False
        self._pc_group_roster_cache: Dict[str, set] = {}

        # Foundry combatants to skip (summons, familiars, effect tokens...).
        self._foundry_ignore: Dict[str, List[str]] = app_settings.get_foundry_ignore()
        self._ignore_logged: set = set()  # keeps the log to one line per name
        self._last_raw_combatants: List[Dict[str, Any]] = []


        self.boolean_fields = {
            '_action': 'set_creature_action',
            '_bonus_action': 'set_creature_bonus_action',
            '_reaction': 'set_creature_reaction'
            # '_object_interaction': 'set_creature_object_interaction'
        }
        
        self.local_bridge: Optional[LocalBridgeServer] = None
        if local_bridge_enabled():
            if not os.getenv("BRIDGE_TOKEN"):
                os.environ["BRIDGE_TOKEN"] = "local-dev"
                self._log("[Bridge] BRIDGE_TOKEN not set; defaulting to 'local-dev'.")
            if not os.getenv("BRIDGE_INGEST_SECRET"):
                os.environ["BRIDGE_INGEST_SECRET"] = os.environ["BRIDGE_TOKEN"]
                self._log("[Bridge] BRIDGE_INGEST_SECRET not set; using BRIDGE_TOKEN for local bridge.")
            self.local_bridge = LocalBridgeServer.from_env()
            self.local_bridge.start()

        self.bridge_client = BridgeClient.from_env()
        self.bridge_snapshot: Optional[Dict[str, Any]] = None
        self.bridge_timer: Optional[QTimer] = None
        self.bridge_stream_thread: Optional[threading.Thread] = None
        self.bridge_stream_stop: Optional[threading.Event] = None
        self.bridge_combatants_by_name: Dict[str, List[Dict[str, Any]]] = {}
        self._pending_bridge_snapshot: Optional[Dict[str, Any]] = None
        self._initiative_reset_pending = False

        # --- Storage backend ---
        self.storage_api: Optional[StorageAPI] = None
        self.storage_api_warning: Optional[str] = None
        if use_storage_api_only():
            base = get_storage_api_base()
            if not base:
                self.storage_api_warning = (
                    "Remote API mode is enabled, but no API URL is configured.\n\n"
                    "Go to File → Settings to set your API URL, or switch to Local Files mode."
                )
            else:
                self.storage_api = StorageAPI(base)
        else:
            from app.local_storage import LocalStorage
            data_dir = get_local_data_dir() or get_config_path("data")
            self.storage_api = LocalStorage(data_dir)

    def stop_bridge_sync(self) -> None:
        """Tear down whichever transport is running, leaving neither active."""
        if self.bridge_timer is not None:
            self.bridge_timer.stop()
            self.bridge_timer.deleteLater()
            self.bridge_timer = None
        if self.bridge_stream_stop is not None:
            self.bridge_stream_stop.set()
        thread = self.bridge_stream_thread
        if thread is not None and thread.is_alive():
            # The reader blocks on the socket, so it exits at the next event or
            # read timeout rather than instantly. It is a daemon and checks the
            # stop event before doing anything, so a short wait is enough --
            # blocking the GUI until a 65s read timeout expires would not be.
            thread.join(timeout=1.0)
        self.bridge_stream_thread = None
        self.bridge_stream_stop = None

    def restart_bridge_sync(self) -> None:
        """Re-read bridge settings and switch transport without a restart.

        Called after the settings dialog saves. The client caches its URL and
        token from construction, so it is rebuilt too -- otherwise changing the
        bridge address in the UI would appear to do nothing until relaunch.
        """
        self.stop_bridge_sync()
        try:
            self.bridge_client = BridgeClient.from_env()
        except Exception as exc:
            self._log(f"[WARN] Could not rebuild bridge client: {exc}")
        self.bridge_snapshot = None
        self.start_bridge_polling()
        self._log(
            "[Bridge] Sync restarted "
            f"({'stream' if bridge_stream_enabled() else 'polling'})."
        )

    def start_bridge_polling(self) -> None:
        if not foundry_bridge_enabled():
            if hasattr(self, "set_bridge_status"):
                self.set_bridge_status("disabled")
            return
        if not self.bridge_client.enabled:
            self._log("[Bridge] BRIDGE_TOKEN is not set; bridge sync is disabled.")
            if hasattr(self, "set_bridge_status"):
                self.set_bridge_status("disabled")
            return
        if bridge_stream_enabled():
            self.start_bridge_stream()
            return
        if self.bridge_timer is None:
            self.bridge_timer = QTimer(self)
            self.bridge_timer.timeout.connect(self.refresh_bridge_state)
            self.bridge_timer.start(5000)
        self.refresh_bridge_state()

    def start_bridge_stream(self) -> None:
        if self.bridge_stream_thread and self.bridge_stream_thread.is_alive():
            return
        if not self.bridge_client.enabled:
            self._log("[Bridge] BRIDGE_TOKEN is not set; bridge stream is disabled.")
            return
        if self.bridge_stream_stop is None:
            self.bridge_stream_stop = threading.Event()

        # These three run on the SSE reader thread. Everything they touch is a
        # widget, so the hand-off has to be a queued signal: QTimer.singleShot()
        # creates its timer in the calling thread, and this one has no event
        # loop, so nothing it scheduled ever ran.
        def on_snapshot(snapshot: Dict[str, Any]) -> None:
            self.bridge_snapshot_received.emit(snapshot)

        def on_stream_connect() -> None:
            self.bridge_status_changed.emit("connected")

        def on_stream_disconnect() -> None:
            self.bridge_status_changed.emit("error")

        self.bridge_stream_thread = threading.Thread(
            target=self.bridge_client.stream_state,
            args=(on_snapshot, self.bridge_stream_stop),
            kwargs={"on_connect": on_stream_connect, "on_disconnect": on_stream_disconnect},
            daemon=True,
        )
        self.bridge_stream_thread.start()
        self._log("[Bridge] Using SSE stream for snapshots.")

    def refresh_bridge_state(self) -> None:
        """Fetch a snapshot without blocking the UI.

        This ran inline on the QTimer, i.e. on the Qt GUI thread, so every
        poll froze the window for the length of a round trip to the bridge --
        ~420ms every 5 seconds against a remote one. The fetch goes to a worker
        and comes back through the same queued signal the SSE path already
        uses.
        """
        if getattr(self, "_bridge_poll_in_flight", False):
            # A bridge slower than the poll interval would otherwise stack up a
            # thread per tick, and the answers would arrive out of order.
            return
        self._bridge_poll_in_flight = True

        def run() -> None:
            try:
                snapshot = self.bridge_client.fetch_state()
            except Exception as exc:
                self._log(f"[Bridge] Failed to fetch state: {exc}")
                snapshot = None
            finally:
                self._bridge_poll_in_flight = False
            self._deliver_bridge_snapshot(snapshot)

        threading.Thread(target=run, name="bridge-poll", daemon=True).start()

    def _deliver_bridge_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> None:
        """Hand a snapshot from a worker thread to the GUI thread.

        Signals, not a direct call: everything downstream touches widgets.
        Falls back to calling straight through when there is no UI attached,
        which is how the headless tests drive this.
        """
        signal = getattr(self, "bridge_snapshot_received", None)
        status = getattr(self, "bridge_status_changed", None)
        if snapshot is None:
            if status is not None:
                status.emit("error")
            elif hasattr(self, "set_bridge_status"):
                self.set_bridge_status("error")
            return
        if signal is not None:
            signal.emit(snapshot)
        else:
            self._set_bridge_snapshot(snapshot)

    def _set_bridge_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> None:
        if snapshot is None or not isinstance(snapshot, dict):
            return
        # If the user is mid-edit in a table cell (e.g. typing a note), applying
        # the snapshot now fires layoutChanged and Qt discards the uncommitted
        # editor text. Stash the latest snapshot and replay it once editing ends.
        if self._is_table_editing():
            self._pending_bridge_snapshot = snapshot
            return
        combatants = snapshot.get("combatants", [])
        if not isinstance(combatants, list):
            combatants = []
        # Keep the unfiltered feed so the ignore dialog can still show (and
        # un-ignore) the things being dropped.
        self._last_raw_combatants = list(combatants)

        # Drop ignored combatants once, here, so nothing downstream ever sees
        # them: they can't be added to initiative, can't be matched by name, and
        # can't sync HP/conditions. Filtering summons out also un-confuses name
        # resolution for the PCs they're named after ("Surina's Echo" vs "Echo").
        combatants, ignored = self._filter_ignored_combatants(combatants)
        if ignored:
            snapshot = dict(snapshot)
            snapshot["combatants"] = combatants

        self.bridge_snapshot = snapshot
        self.bridge_combatants_by_name = self._index_bridge_combatants(combatants)

        # Anything already in the tracker that the rules now cover (added before
        # a rule existed, or restored from a saved state) goes too.
        for name in self.prune_ignored_creatures():
            self._log(f"[Bridge] Dropped ignored '{name}' from initiative")

        self._apply_bridge_snapshot(snapshot)
        world = snapshot.get("world")
        suffix = f" (ignored {len(ignored)})" if ignored else ""
        self._log(f"[Bridge] Snapshot loaded world={world!r} combatants={len(combatants)}{suffix}")
        if hasattr(self, "set_bridge_status"):
            self.set_bridge_status("connected")
        self._check_pc_group_matches_foundry(combatants)

    def _is_table_editing(self) -> bool:
        """True if a table cell editor is currently open (mid-edit)."""
        table = getattr(self, "table", None)
        if table is None:
            return False
        try:
            from PyQt5.QtWidgets import QAbstractItemView
            return table.state() == QAbstractItemView.EditingState
        except Exception:
            return False

    def _flush_pending_bridge_snapshot(self, *args) -> None:
        """Apply a snapshot that was deferred while a cell was being edited.

        Wired to the table delegate's closeEditor signal so it runs right after
        the user commits or cancels an edit.
        """
        snapshot = getattr(self, "_pending_bridge_snapshot", None)
        if snapshot is None:
            return
        self._pending_bridge_snapshot = None
        # Defer to the next event loop tick so the editor is fully torn down
        # before we fire layoutChanged again.
        QTimer.singleShot(0, lambda payload=snapshot: self._set_bridge_snapshot(payload))

    def _has_missing_initiatives(self) -> bool:
        if not getattr(self, "manager", None) or not getattr(self.manager, "creatures", None):
            return False
        for creature in self.manager.creatures.values():
            value = getattr(creature, "initiative", None)
            if value in (None, "", -1, 0):
                return True
            try:
                if int(value) <= 0:
                    return True
            except Exception:
                return True
        return False

    def _mark_initiative_reset_pending(self) -> None:
        if self._initiative_reset_pending:
            return
        if self._has_missing_initiatives():
            self._initiative_reset_pending = True

    def _maybe_reset_initiative_turn(self) -> bool:
        if not self._initiative_reset_pending:
            return False
        if self.round_counter > 1 or self.time_counter > 0:
            self._initiative_reset_pending = False
            return False
        if self._has_missing_initiatives():
            return False
        if not getattr(self, "turn_order", None):
            return False
        if not self.turn_order:
            return False
        self.round_counter = 1
        self.time_counter = 0
        self.current_idx = 0
        self.current_creature_name = self.turn_order[0]
        self._initiative_reset_pending = False
        return True

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
            if getattr(creature, "_is_lair_action", False):
                continue
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

            # Auto-set statblock override from actor name if not already set by user
            actor_name = (combatant.get("actorName") or "").strip()
            if actor_name and not creature.statblock_override:
                base_name = self.get_base_name(creature)
                if actor_name != base_name:
                    creature.statblock_override = actor_name

            resolved_type = self._resolve_foundry_creature_type(combatant)
            if resolved_type and getattr(creature, "_type", None) == CreatureType.BASE:
                creature._type = resolved_type
                if resolved_type == CreatureType.PLAYER:
                    creature.death_saves_prompt = True

            # Populate spell slots / innate spells / X-per-day abilities from the
            # statblock library for bridge-sourced creatures whose resources are
            # still empty. Only monsters/NPCs — players don't have statblocks.
            if getattr(creature, "_type", None) == CreatureType.MONSTER and not (
                creature._spell_slots or creature._innate_slots or creature._ability_uses
            ):
                sb_name = (
                    creature.statblock_override
                    or actor_name
                    or self.get_base_name(creature)
                )
                if sb_name:
                    self.apply_statblock_slots(creature, sb_name)

            effects = combatant.get("effects", [])
            if isinstance(effects, list):
                setattr(creature, "foundry_effects", effects)
                labels = [effect.get("label") for effect in effects if effect.get("label")]
                creature.conditions = labels

            # Sync HP from Foundry snapshot (covers player-initiated HP changes)
            hp_data = combatant.get("hp", {})
            if isinstance(hp_data, dict):
                hp_value = hp_data.get("value")
                hp_max = hp_data.get("max")
                hp_temp = hp_data.get("temp")
                hp_tempmax = hp_data.get("tempmax")
                self._log(f"[Bridge][HP] {creature_name!r}: value={hp_value} max={hp_max} temp={hp_temp} tempmax={hp_tempmax}")
                if hp_value is not None:
                    try:
                        new_hp = int(hp_value)
                        if new_hp != getattr(creature, "curr_hp", None):
                            creature.curr_hp = new_hp
                    except (TypeError, ValueError):
                        pass
                if hp_max is not None:
                    try:
                        new_max = int(hp_max)
                        if new_max != getattr(creature, "max_hp", None):
                            creature.max_hp = new_max
                    except (TypeError, ValueError):
                        pass
                if hp_temp is not None:
                    try:
                        new_temp = max(0, int(hp_temp))
                        if new_temp != creature.temp_hp:
                            creature.temp_hp = new_temp
                    except (TypeError, ValueError):
                        pass
                if hp_tempmax is not None:
                    try:
                        new_bonus = int(hp_tempmax)
                        if new_bonus != creature.max_hp_bonus:
                            creature.max_hp_bonus = new_bonus
                    except (TypeError, ValueError):
                        pass

            ac_value = self._extract_combatant_ac(combatant)
            if ac_value is not None:
                try:
                    creature.armor_class = int(ac_value)
                except Exception:
                    setattr(creature, "_armor_class", ac_value)

        old_round = getattr(self, "round_counter", 1)

        combat = snapshot.get("combat", {})
        if isinstance(combat, dict):
            round_value = combat.get("round")
            # Foundry is only authoritative about the round while it actually
            # has a combat running. With Foundry closed the bridge keeps
            # serving its last snapshot -- active:false, round:0 -- and
            # max(1, 0) silently rewound the tracker to round 1 on every poll.
            if (
                isinstance(round_value, int)
                and round_value >= 1
                and combat.get("active")
            ):
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

                active_label = None
                if not active_name:
                    active_label = active.get("name")
                if active_label:
                    active_name = active_label

            current_cr = self.manager.creatures.get(
                getattr(self, "current_creature_name", None) or ""
            )
            if (
                active_name
                and active_name != getattr(self, "current_creature_name", None)
                and not getattr(current_cr, "_is_lair_action", False)
            ):
                self.current_creature_name = active_name
                updated_active = True

        self._mark_initiative_reset_pending()

        if added_combatants:
            self.build_turn_order()
            reset_active = self._maybe_reset_initiative_turn()
            self.update_table()
            self.pop_lists()
            if reset_active:
                self.update_active_ui()
        elif updated_initiative or updated_active:
            self.build_turn_order()
            if self._maybe_reset_initiative_turn():
                self.update_active_ui()
        else:
            self.update_active_ui()

        # --- Turn-change side effects (mirror what next_turn() does) ---

        round_advanced = (self.round_counter > old_round)

        if round_advanced:
            # Reset action/bonus_action/object_interaction for ALL creatures at top of round
            for cr in self.manager.creatures.values():
                if hasattr(cr, "action"):
                    cr.action = False
                if hasattr(cr, "bonus_action"):
                    cr.bonus_action = False
                if hasattr(cr, "object_interaction"):
                    cr.object_interaction = False

            # Tick status timers
            any_tick = False
            for cr in self.manager.creatures.values():
                st = getattr(cr, "status_time", None)
                try:
                    st_int = int(st) if st is not None else None
                except (ValueError, TypeError):
                    st_int = None
                if st_int is not None and st_int > 0:
                    cr.status_time = max(0, st_int - 6)
                    any_tick = True
            if any_tick:
                if hasattr(self, "update_table") and callable(self.update_table):
                    self.update_table()

        if updated_active and self.current_creature_name:
            cr = self.manager.creatures.get(self.current_creature_name)
            if cr:
                # Reset reaction on creature's own turn
                if hasattr(cr, "reaction"):
                    cr.reaction = False
                # Show statblock for monsters
                if getattr(cr, "_type", None) == CreatureType.MONSTER:
                    self.active_statblock_image(cr)
                # Prompt death saves
                self._maybe_prompt_death_saves(cr)

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

        # Build indexes for creatures already in the app (dedupe keys).
        # IMPORTANT: do NOT dedupe by actorId. Multiple tokens/combatants can share the same actorId.
        existing_by_combatant_id: Dict[str, I_Creature] = {}
        existing_by_token_id: Dict[str, I_Creature] = {}
        matched_keys: set[str] = set()

        for creature in self.manager.creatures.values():
            cid = _normalize_id(
                getattr(creature, "foundry_combatant_id", None)
                or getattr(creature, "combatant_id", None)
            )
            tid = _normalize_id(
                getattr(creature, "foundry_token_id", None)
                or getattr(creature, "token_id", None)
            )

            if cid:
                existing_by_combatant_id[cid] = creature
                matched_keys.add(cid)
            if tid:
                existing_by_token_id[tid] = creature
                matched_keys.add(tid)

        # For creatures that have no IDs yet, try to resolve and attach IDs (no new creatures created here).
        for creature in self.manager.creatures.values():
            if getattr(creature, "_is_lair_action", False):
                continue
            has_any_id = bool(
                getattr(creature, "foundry_combatant_id", None)
                or getattr(creature, "foundry_token_id", None)
                or getattr(creature, "combatant_id", None)
                or getattr(creature, "token_id", None)
            )
            if has_any_id:
                continue

            resolved = self._resolve_bridge_combatant(getattr(creature, "name", ""))
            if not resolved:
                continue

            rcid = _normalize_id(resolved.get("combatantId"))
            rtid = _normalize_id(resolved.get("tokenId"))
            raid = _normalize_id(resolved.get("actorId"))

            if rcid:
                setattr(creature, "foundry_combatant_id", rcid)
                existing_by_combatant_id[rcid] = creature
                matched_keys.add(rcid)
            if rtid:
                setattr(creature, "foundry_token_id", rtid)
                existing_by_token_id[rtid] = creature
                matched_keys.add(rtid)
            if raid:
                setattr(creature, "foundry_actor_id", raid)  # keep as metadata only

        # Build sets of IDs currently present in the snapshot (for cross-scene orphan detection).
        snapshot_combatant_ids = {
            _normalize_id(c.get("combatantId"))
            for c in combatants
            if isinstance(c, dict) and _normalize_id(c.get("combatantId"))
        }
        snapshot_token_ids = {
            _normalize_id(c.get("tokenId"))
            for c in combatants
            if isinstance(c, dict) and _normalize_id(c.get("tokenId"))
        }

        # Build actorId index for orphaned creatures (scene-transition fallback).
        # Only include creatures whose stored combatantId/tokenId are absent from the current snapshot.
        existing_by_actor_id: Dict[str, I_Creature] = {}
        for creature in self.manager.creatures.values():
            if getattr(creature, "_is_lair_action", False):
                continue
            aid = _normalize_id(getattr(creature, "foundry_actor_id", None))
            if not aid:
                continue
            old_cid = _normalize_id(getattr(creature, "foundry_combatant_id", None))
            old_tid = _normalize_id(getattr(creature, "foundry_token_id", None))
            # Only eligible if old IDs are gone from snapshot (scene transition)
            if old_cid in snapshot_combatant_ids or old_tid in snapshot_token_ids:
                continue
            existing_by_actor_id[aid] = creature

        # Add missing Foundry combatants into the app (membership add-only).
        added = False
        for combatant in combatants:
            if not isinstance(combatant, dict):
                continue
            if combatant.get("excludeFromSync"):
                continue

            name = (combatant.get("name") or "").strip()
            if not name:
                continue

            cid = _normalize_id(combatant.get("combatantId"))
            tid = _normalize_id(combatant.get("tokenId"))
            aid = _normalize_id(combatant.get("actorId"))

            # Skip if we've already matched this combatant by combatantId or tokenId.
            if (cid and cid in matched_keys) or (tid and tid in matched_keys):
                continue

            # If an existing creature has matching IDs, attach missing metadata and skip creation.
            existing = None
            if cid and cid in existing_by_combatant_id:
                existing = existing_by_combatant_id[cid]
            elif tid and tid in existing_by_token_id:
                existing = existing_by_token_id[tid]

            if existing:
                if cid and not getattr(existing, "foundry_combatant_id", None):
                    setattr(existing, "foundry_combatant_id", cid)
                    existing_by_combatant_id[cid] = existing
                    matched_keys.add(cid)
                if tid and not getattr(existing, "foundry_token_id", None):
                    setattr(existing, "foundry_token_id", tid)
                    existing_by_token_id[tid] = existing
                    matched_keys.add(tid)
                if aid and not getattr(existing, "foundry_actor_id", None):
                    setattr(existing, "foundry_actor_id", aid)
                resolved_type = self._resolve_foundry_creature_type(combatant)
                if resolved_type and getattr(existing, "_type", None) == CreatureType.BASE:
                    existing._type = resolved_type
                    if resolved_type == CreatureType.PLAYER:
                        existing.death_saves_prompt = True
                continue

            # Fallback: match by actorId for scene-transition orphans (old IDs gone from snapshot)
            if aid and aid in existing_by_actor_id:
                existing = existing_by_actor_id[aid]
                if cid:
                    setattr(existing, "foundry_combatant_id", cid)
                    existing_by_combatant_id[cid] = existing
                    matched_keys.add(cid)
                if tid:
                    setattr(existing, "foundry_token_id", tid)
                    existing_by_token_id[tid] = existing
                    matched_keys.add(tid)
                del existing_by_actor_id[aid]
                continue  # don't create new creature

            # Create a new creature for this Foundry combatant using the proper subclass
            # so it is included in save_state (which filters by isinstance(c, Monster/Player))
            resolved_type = self._resolve_foundry_creature_type(combatant)
            if resolved_type == CreatureType.PLAYER:
                creature = Player(name=str(name))
            elif resolved_type == CreatureType.MONSTER:
                creature = Monster(name=str(name))
            else:
                creature = I_Creature(_name=str(name))

            if cid:
                setattr(creature, "foundry_combatant_id", cid)
            if tid:
                setattr(creature, "foundry_token_id", tid)
            if aid:
                setattr(creature, "foundry_actor_id", aid)

            initiative = combatant.get("initiative")
            if initiative is not None:
                try:
                    creature.initiative = int(initiative)
                except (TypeError, ValueError):
                    pass

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

            # AC (Foundry schema can vary; support common shapes)
            ac_value = self._extract_combatant_ac(combatant)
            if ac_value is not None:
                try:
                    creature.armor_class = int(ac_value)
                except Exception:
                    setattr(creature, "_armor_class", ac_value)

            effects = combatant.get("effects", [])
            if isinstance(effects, list):
                setattr(creature, "foundry_effects", effects)
                labels = [e.get("label") for e in effects if isinstance(e, dict) and e.get("label")]
                creature.conditions = labels

            # Auto-set statblock override from actor name when token name differs
            actor_name = (combatant.get("actorName") or "").strip()
            if actor_name and actor_name != name:
                creature.statblock_override = actor_name
                self.apply_statblock_slots(creature, actor_name)

            # Ensure unique name in manager
            base_name = creature.name
            counter = 1
            while creature.name in self.manager.creatures:
                creature.name = f"{base_name}_{counter}"
                counter += 1

            self.manager.add_creature(creature)
            added = True

            # Update indexes + matched keys
            if cid:
                existing_by_combatant_id[cid] = creature
                matched_keys.add(cid)
            if tid:
                existing_by_token_id[tid] = creature
                matched_keys.add(tid)

        return added

    def _extract_combatant_ac(self, combatant: Dict[str, Any]) -> Optional[int]:
        ac_val = None
        try:
            # common: {"ac": {"value": 15}} or {"ac": 15}
            ac_field = combatant.get("ac")
            if isinstance(ac_field, dict):
                ac_val = ac_field.get("value")
            elif ac_field is not None:
                ac_val = ac_field

            # fallback shapes
            if ac_val is None:
                ac_val = combatant.get("armorClass")

            if ac_val is None:
                attrs = combatant.get("attributes", {})
                if isinstance(attrs, dict):
                    ac_obj = attrs.get("ac", {})
                    if isinstance(ac_obj, dict):
                        ac_val = ac_obj.get("value")
        except Exception:
            ac_val = None

        if ac_val is None:
            return None
        try:
            return int(ac_val)
        except (TypeError, ValueError):
            return None

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

    # ================== Foundry ignore list ======================
    # Summons, familiars, effect tokens and the like clutter initiative. Anything
    # matching this list is stripped from the snapshot on arrival.

    def reload_foundry_ignore(self) -> None:
        self._foundry_ignore = app_settings.get_foundry_ignore()

    @property
    def foundry_ignore_patterns(self) -> List[str]:
        return list(self._foundry_ignore.get("patterns", []))

    @property
    def foundry_ignore_actor_ids(self) -> List[str]:
        return list(self._foundry_ignore.get("actor_ids", []))

    @property
    def ignore_player_owned_npcs(self) -> bool:
        return bool(self._foundry_ignore.get("player_owned_npcs", True))

    def set_foundry_ignore(
        self, patterns: List[str], actor_ids: List[str], player_owned_npcs: bool = None
    ) -> None:
        app_settings.set_foundry_ignore(patterns, actor_ids, player_owned_npcs)
        self.reload_foundry_ignore()
        self._ignore_logged.clear()

    def add_foundry_ignore(self, pattern: str = "", actor_id: str = "") -> None:
        """Add a name pattern and/or actor id to the ignore list."""
        patterns = self.foundry_ignore_patterns
        actor_ids = self.foundry_ignore_actor_ids
        if pattern and pattern not in patterns:
            patterns.append(pattern)
        if actor_id and actor_id not in actor_ids:
            actor_ids.append(actor_id)
        self.set_foundry_ignore(patterns, actor_ids)

    def _name_matches_ignore(self, name: str) -> Optional[str]:
        """Return the pattern that matches this name, if any.

        A pattern with no wildcard is an exact (case-insensitive) match, so
        ignoring "Echo" never silently swallows "Echo Talonshade". Use globs
        like "*Echo" or "Summon*" when you want a family of tokens.
        """
        if not name:
            return None
        candidate = self._normalize_bridge_name(name)
        for pattern in self.foundry_ignore_patterns:
            norm = self._normalize_bridge_name(pattern)
            if not norm:
                continue
            if any(ch in norm for ch in "*?["):
                if fnmatch.fnmatchcase(candidate, norm):
                    return pattern
            elif candidate == norm:
                return pattern
        return None

    def combatant_ignore_reason(self, combatant: Dict[str, Any]) -> Optional[str]:
        """Why this Foundry combatant should be skipped, or None to track it."""
        if not isinstance(combatant, dict):
            return None
        if combatant.get("excludeFromSync"):
            return "excluded in Foundry"
        actor_id = combatant.get("actorId")
        if actor_id and str(actor_id) in self.foundry_ignore_actor_ids:
            return "ignored actor"
        if self.ignore_player_owned_npcs:
            actor_type = (combatant.get("actorType") or "").lower()
            if actor_type == "npc" and combatant.get("actorHasPlayerOwner") is True:
                return "player-owned NPC (summon/companion)"
        for key in ("name", "actorName"):
            matched = self._name_matches_ignore((combatant.get(key) or "").strip())
            if matched:
                return f"matches '{matched}'"
        return None

    def _filter_ignored_combatants(
        self, combatants: List[Dict[str, Any]]
    ) -> tuple:
        """Split a snapshot's combatants into (kept, ignored)."""
        kept: List[Dict[str, Any]] = []
        ignored: List[Dict[str, Any]] = []
        for combatant in combatants:
            reason = self.combatant_ignore_reason(combatant)
            if reason:
                ignored.append(combatant)
                if combatant.get("name") not in self._ignore_logged:
                    self._ignore_logged.add(combatant.get("name"))
                    self._log(f"[Bridge] Ignoring '{combatant.get('name')}' ({reason})")
            else:
                kept.append(combatant)
        return kept, ignored

    def _raw_combatant_for_creature(self, creature: I_Creature) -> Optional[Dict[str, Any]]:
        """Find the unfiltered snapshot entry a tracked creature came from."""
        cid = getattr(creature, "foundry_combatant_id", None)
        tid = getattr(creature, "foundry_token_id", None)
        aid = getattr(creature, "foundry_actor_id", None)
        name = self._normalize_bridge_name(getattr(creature, "name", "") or "")
        for combatant in self._last_raw_combatants:
            if not isinstance(combatant, dict):
                continue
            if cid and str(combatant.get("combatantId")) == str(cid):
                return combatant
            if tid and str(combatant.get("tokenId")) == str(tid):
                return combatant
            if aid and str(combatant.get("actorId")) == str(aid):
                return combatant
            if name and self._normalize_bridge_name(combatant.get("name") or "") == name:
                return combatant
        return None

    def creature_ignore_reason(self, creature: I_Creature) -> Optional[str]:
        """Same check, for a creature already sitting in the tracker.

        Prefers the creature's snapshot entry, since rules like the summon one
        key off Foundry fields (actorType) the creature itself doesn't carry.
        """
        raw = self._raw_combatant_for_creature(creature)
        if raw is not None:
            return self.combatant_ignore_reason(raw)
        actor_id = getattr(creature, "foundry_actor_id", None)
        if actor_id and str(actor_id) in self.foundry_ignore_actor_ids:
            return "ignored actor"
        for name in (getattr(creature, "name", ""), getattr(creature, "statblock_override", "")):
            matched = self._name_matches_ignore((name or "").strip())
            if matched:
                return f"matches '{matched}'"
        return None

    def prune_ignored_creatures(self) -> List[str]:
        """Drop creatures already in the tracker that the ignore list now covers."""
        if not getattr(self, "manager", None):
            return []
        doomed = [
            name for name, creature in self.manager.creatures.items()
            if not getattr(creature, "_is_lair_action", False)
            and self.creature_ignore_reason(creature)
        ]
        if not doomed:
            return []
        self.manager.rm_creatures(doomed)
        self.manager.sort_creatures()
        self.table_model.refresh()
        self.build_turn_order()
        self.update_table()
        self.pop_lists()
        return doomed

    def _normalize_bridge_name(self, name: str) -> str:
        cleaned = re.sub(r"\s*#\s*(\d+)\s*$", r" \1", name or "")
        return re.sub(r"\s+", " ", cleaned).strip().casefold()

    def _resolve_foundry_creature_type(self, combatant: Dict[str, Any]) -> Optional[CreatureType]:
        if not isinstance(combatant, dict):
            return None
        actor_type = combatant.get("actorType")
        has_player_owner = combatant.get("actorHasPlayerOwner")
        # actorType wins over ownership: a player-owned "npc" is a summon or
        # companion, not a PC, and typing it as one gives it death saves.
        if isinstance(actor_type, str) and actor_type.lower() == "character":
            return CreatureType.PLAYER
        if actor_type:
            return CreatureType.MONSTER
        if has_player_owner is True:
            return CreatureType.PLAYER
        return None

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
            self._log(f"[Bridge] Multiple combatants match '{creature_name}', skipping command enqueue.")
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
            self._log(f"[Bridge] Fuzzy matched '{creature_name}' -> '{flat[0].get('name')}'")
            return flat[0]

        if len(flat) > 1:
            self._log(f"[Bridge] Fuzzy match ambiguous for '{creature_name}' ({len(flat)} candidates), skipping.")
            return None

        return None

    def _enqueue_bridge_set_hp(self, creature_name: str, hp: int) -> None:
        if not self.bridge_client.enabled:
            return
        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)
        if creature and getattr(creature, "_is_lair_action", False):
            return
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
                self._log(f"[Bridge] No combatant match for '{creature_name}', skipping.")
                return
            token_id = combatant.get("tokenId")
            actor_id = combatant.get("actorId")
        if not token_id:
            self._log(f"[Bridge] Missing tokenId for '{creature_name}', skipping.")
            return
        self._log(f"[Bridge] enqueue set_hp name={creature_name!r} hp={hp}")
        self.bridge_client.enqueue_set_hp(
            token_id=str(token_id), hp=int(hp), actor_id=str(actor_id) if actor_id else None
        )

    def _enqueue_bridge_set_temp_hp(self, creature_name: str, temp_hp: int) -> None:
        if not self.bridge_client.enabled:
            return
        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)
        if creature and getattr(creature, "_is_lair_action", False):
            return
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
                return
            token_id = combatant.get("tokenId")
            actor_id = combatant.get("actorId")
        if not token_id:
            return
        self._log(f"[Bridge] enqueue set_temp_hp name={creature_name!r} temp={temp_hp}")
        self.bridge_client.enqueue_set_temp_hp(
            token_id=str(token_id),
            temp_hp=int(temp_hp),
            actor_id=str(actor_id) if actor_id else None,
        )

    def _enqueue_bridge_set_max_hp_bonus(self, creature_name: str, max_hp_bonus: int) -> None:
        if not self.bridge_client.enabled:
            return
        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)
        if creature and getattr(creature, "_is_lair_action", False):
            return
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
                return
            token_id = combatant.get("tokenId")
            actor_id = combatant.get("actorId")
        if not token_id:
            return
        self._log(f"[Bridge] enqueue set_max_hp_bonus name={creature_name!r} bonus={max_hp_bonus}")
        self.bridge_client.enqueue_set_max_hp_bonus(
            token_id=str(token_id),
            max_hp_bonus=int(max_hp_bonus),
            actor_id=str(actor_id) if actor_id else None,
        )

    def _enqueue_bridge_set_initiative(self, creature_name: str, initiative: int) -> None:
        if not getattr(self, "bridge_client", None):
            self._log("[Bridge][DBG] bridge_client missing; cannot send set_initiative")
            return

        if not self.bridge_client.enabled:
            self._log("[Bridge][DBG] bridge_client disabled; skipping set_initiative")
            return

        creature = None
        if getattr(self, "manager", None):
            creature = self.manager.creatures.get(creature_name)
        if creature and getattr(creature, "_is_lair_action", False):
            return

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

        combatant = None

        # Prefer combatantId for initiative updates; resolve from snapshot if missing
        if not combatant_id:
            combatant = self._resolve_bridge_combatant(creature_name)

            # If resolve fails, snapshot may be stale/empty at startup: refresh once and retry
            if not combatant:
                try:
                    snapshot = self.bridge_client.fetch_state()
                except Exception:
                    snapshot = None
                if isinstance(snapshot, dict):
                    combatants = snapshot.get("combatants", [])
                    if isinstance(combatants, list):
                        self.bridge_snapshot = snapshot
                        self.bridge_combatants_by_name = self._index_bridge_combatants(combatants)
                combatant = self._resolve_bridge_combatant(creature_name)

            if not combatant:
                self._log(f"[Bridge][DBG] no combatant match for {creature_name!r}; skipping set_initiative")
                return

            combatant_id = combatant.get("combatantId") or combatant_id
            token_id = combatant.get("tokenId") or token_id
            actor_id = combatant.get("actorId") or actor_id

        if not combatant_id and not token_id and not actor_id:
            self._log(f"[Bridge][DBG] missing all ids for {creature_name!r}; skipping set_initiative")
            return

        self._log(
            "[Bridge] enqueue set_initiative "
            f"name={creature_name!r} initiative={initiative!r} "
            f"combatant_id={combatant_id!r} token_id={token_id!r} actor_id={actor_id!r}"
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
            self._log(
                f"[Bridge] Missing tokenId/actorId for condition sync '{getattr(creature, 'name', '')}'"
            )
            return
        if added:
            self._log(
                f"[Bridge] enqueue add_condition name={getattr(creature, 'name', '')!r} added={added}"
            )
        if removed:
            self._log(
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
        """
        # Prefer manager's canonical ordering
        if hasattr(self.manager, "ordered_items"):
            ordered = self.manager.ordered_items()  # List[Tuple[str, I_Creature]]
            names = [nm for nm, _ in ordered]
        else:
            creatures = self._creature_list_sorted()
            names = [getattr(c, "name", "") for c in creatures if getattr(c, "name", "")]

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

    # ----------------
    # JSON Manipulation
    # ----------------
    def init_players(self):
        """Reset the table to the active PC group, or the default roster.

        Whichever group was last loaded or saved is the one Initialize brings
        back, so switching campaigns doesn't drop you onto the default party.
        """
        try:
            group_key = self.active_pc_group
            if group_key and self.load_file_to_manager(group_key, self.manager):
                self._log(f"[Groups] Initialized from '{self._pc_group_display(group_key)}'")
            else:
                if group_key:
                    # Group is gone (deleted elsewhere?) — don't leave the table
                    # untouched and look like the button did nothing.
                    self._log(f"[Groups] '{group_key}' unavailable; using default roster")
                self.load_file_to_manager("players.json", self.manager)
                # Party now comes from the default roster, not a saved group.
                self._set_active_pc_group(None)
            # After loading, refresh the table model and update UI
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            # Rebuild order after data load
            self.build_turn_order()
            self._clear_statblock()
        except Exception as e:
            report_error(
                self, "Initialize Failed",
                "Could not load the player roster.", e,
            )

    def load_state(self):
        filename = "last_state.json"
        self.load_file_to_manager(filename, self.manager)
        if self.manager.creatures:
            self.table_model.set_fields_from_sample()
            self.build_turn_order()

    def save_encounter_to_storage(self, filename: str, description: str = ""):
        if not self.storage_api:
            raise RuntimeError("Storage is not configured. Go to File → Settings.")
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
                "Storage is not configured.\n\nGo to File → Settings to configure storage."
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
            if getattr(self, "storage_api", None):
                self.storage_api.put_json(filename, save_data)
            else:
                file_path = self.get_data_path(filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
            self.notify("State saved", "success")
        except Exception as e:
            report_error(
                self, "Save Failed",
                "Your combat state could not be saved. Recent changes are still "
                "in the app but are not written to disk.", e,
            )

    def load_file_to_manager(self, file_name, manager, monsters=False, merge=False, prompt_for_initiatives: bool = False) -> bool:
        """Load a saved state into `manager`. Returns False if nothing loaded."""
        state = None

        try:
            # --- Decide source: Storage key vs local file ---
            file_path = self.get_data_path(file_name)

            if getattr(self, "storage_api", None) and not os.path.exists(file_path):
                # Treat file_name as a Storage key
                raw = self.storage_api.get_json(file_name)
                if raw is None:
                    self._log(f"[WARN] Storage key not found: {file_name}")
                    return False
                # Run through your custom decoder
                state = json.loads(json.dumps(raw), object_hook=self.custom_decoder)
            else:
                # Local file fallback (dev/offline)
                if not os.path.exists(file_path):
                    self._log(f"[WARN] Local file not found: {file_path}")
                    return False
                with open(file_path, "r", encoding="utf-8") as f:
                    state = json.load(f, object_hook=self.custom_decoder)

        except Exception as e:
            self._log(f"[ERROR] Failed to load '{file_name}': {e}")
            return False

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
            return True

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
            return True

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
            self.round_counter = max(1, state.get("round_counter", 1))
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
        return True

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
            "_object_interaction", "object_interaction", "OI",
            "_temp_hp", "temp_hp",
            "_max_hp_bonus", "max_hp_bonus",
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
            except Exception as exc:
                self._log(f"[WARN] Condition panel sync failed: {exc}")

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
                except Exception as exc:
                    self._log(f"[WARN] set_active_creature failed: {exc}")
        if hasattr(self, "table_delegate") and self.table_delegate:
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
        if hasattr(self, "prev_button") and self.prev_button:
            # Only enable Prev if we can actually go back
            self.prev_button.setEnabled(not at_absolute_start)

    def handle_initiative_update(self):
        """
        Auto-apply initiative edits and ensure the active UI/statblock reflect the latest turn order.
        """
        if getattr(self, "_initiative_dialog_open", False):
            return
        
        self._mark_initiative_reset_pending()
        self._initiative_dialog_open = True
        try:
            self.manager.sort_creatures()
            self.build_turn_order()
            if hasattr(self, "table_model") and self.table_model:
                self.table_model.refresh()
            self.update_table()
        finally:
            self._initiative_dialog_open = False

        if self._maybe_reset_initiative_turn():
            self.update_active_ui()
        else:
            self.update_active_init()
        active_name = self.active_name()
        if active_name:
            cr = self.manager.creatures.get(active_name)
            if cr and getattr(cr, "_type", None) == CreatureType.MONSTER:
                self.active_statblock_image(cr)

    def init_tracking_mode(self, by_name):
        self.tracking_by_name = by_name

    # Caps for automatic, content-based sizing only. Dragging a header past
    # one of these is honoured and remembered — they bound what the app
    # chooses on its own, not what the user chooses.
    _COL_MAX_WIDTHS = {
        "_name":       200,
        "_notes":      180,
        "_conditions": 160,
    }
    _NOTES_MIN_WIDTH = 180

    def adjust_table_size(self):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        screen_height = screen_geometry.height()

        font_size = max(int(screen_height * 0.012), 10) if screen_height < 1440 else 18
        self.table.setFont(QFont('Arial', font_size))

        self.table.resizeRowsToContents()

        model = self.table.model()
        source_fields = getattr(self, "table_model", None)
        source_fields = getattr(source_fields, "fields", []) if source_fields else []
        header = self.table.horizontalHeader()
        # Nothing is Stretch: a stretched section cannot be dragged, and Qt
        # dumps every spare pixel into it. Widths are set explicitly instead.
        header.setStretchLastSection(False)

        saved = getattr(self, "_user_column_widths", None) or {}
        # Suppress the sectionResized bookkeeping while we are the one resizing,
        # or the app's own sizing would be recorded as the user's choice.
        self._sizing_columns = True
        try:
            if model:
                for column in range(model.columnCount()):
                    if self.table.isColumnHidden(column):
                        continue
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
                    field = source_fields[column] if column < len(source_fields) else ""
                    width = saved.get(field)
                    if width:
                        self.table.setColumnWidth(column, width)
                        continue
                    self.table.resizeColumnToContents(column)
                    cap = self._COL_MAX_WIDTHS.get(field)
                    if cap is not None and self.table.columnWidth(column) > cap:
                        self.table.setColumnWidth(column, cap)
            self._stretch_notes_column()
        finally:
            self._sizing_columns = False

        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._fit_table_width()
        self._fit_table_height()

    def _fit_table_height(self):
        """Stop the table at its last row instead of at the bottom of the window.

        A table with room to spare used to paint a tall block of empty rows
        under the initiative order. Capping its height to the rows it actually
        holds ends it at the last combatant, and it grows as more are added.
        This is a maximum, never a minimum -- the window stays free to shrink
        below it, and the table scrolls once it runs out of room, as before.
        """
        table = getattr(self, "table", None)
        model = table.model() if table is not None else None
        if model is None:
            return

        rows = model.rowCount()
        used = sum(self.table.rowHeight(r) for r in range(rows))
        # An empty table still shows one row's worth, so it reads as a table
        # waiting for combatants rather than a stray header strip.
        if rows == 0:
            used = self.table.verticalHeader().defaultSectionSize()

        height = used + self.table.horizontalHeader().height() + 2 * self.table.frameWidth()
        if self._needs_horizontal_scroll():
            height += self.table.horizontalScrollBar().sizeHint().height()

        if self.table.maximumHeight() == height:
            return
        self.table.setMaximumHeight(height)

    def _needs_horizontal_scroll(self) -> bool:
        """Whether the columns overflow the width the layout can give them.

        Derived from the widths rather than from horizontalScrollBar().
        isVisible(): Qt updates that only on the next layout pass, so just
        after a column resize or a row removal it still reports the *previous*
        state -- which left the table holding a scrollbar's worth of height it
        no longer needed, as a blank strip under the last row.
        """
        model = self.table.model()
        if model is None:
            return False

        columns = sum(
            self.table.columnWidth(c)
            for c in range(model.columnCount())
            if not self.table.isColumnHidden(c)
        )
        available = self._available_table_width()
        return available > 0 and columns > available

    def _stretch_notes_column(self):
        """Fit Notes to whatever width the other columns leave over.

        Name used to be the stretch section, which made it both enormous and
        undraggable. Notes takes the slack instead -- growing when there is
        room, giving it back when the window shrinks, and never dropping below
        a readable minimum. Once the user drags Notes themselves, their width
        stands and this steps aside.
        """
        table = getattr(self, "table", None)
        model = table.model() if table is not None else None
        source_fields = getattr(self, "table_model", None)
        source_fields = getattr(source_fields, "fields", []) if source_fields else []
        if model is None or "_notes" not in source_fields:
            return
        if "_notes" in (getattr(self, "_user_column_widths", None) or {}):
            return

        column = source_fields.index("_notes")
        if column >= model.columnCount() or self.table.isColumnHidden(column):
            return

        others = sum(
            self.table.columnWidth(c)
            for c in range(model.columnCount())
            if c != column and not self.table.isColumnHidden(c)
        )
        target = max(self._NOTES_MIN_WIDTH, self._available_table_width() - others)
        if target == self.table.columnWidth(column):
            return

        was_sizing = getattr(self, "_sizing_columns", False)
        self._sizing_columns = True
        try:
            self.table.setColumnWidth(column, target)
        finally:
            self._sizing_columns = was_sizing

    def _available_table_width(self) -> int:
        """Column width the central layout can offer, chrome already deducted.

        Measured from the container rather than from the table's own viewport:
        the table's width is capped to its columns (_fit_table_width), so asking
        the viewport how much room there is would only ever echo back the width
        the columns already have, and a widened window would never be filled.
        """
        table = getattr(self, "table", None)
        layout = getattr(self, "mainlayout", None)
        central = getattr(self, "central_widget", None)
        if table is None or layout is None or central is None:
            return 0

        margins = layout.contentsMargins()
        available = central.width() - margins.left() - margins.right()
        return available - self._table_chrome_width()

    def _table_chrome_width(self) -> int:
        """Everything inside the table's frame that isn't a column."""
        width = 2 * self.table.frameWidth()
        header = self.table.verticalHeader()
        if header is not None and header.isVisible():
            width += header.width()
        scrollbar = self.table.verticalScrollBar()
        if scrollbar is not None and scrollbar.isVisible():
            width += scrollbar.width()
        return width

    def _fit_table_width(self):
        """End the table at its last column, the way it ends at its last row.

        Dragging a column narrower used to leave a strip of empty table body on
        the right. Capping the widget's width to the columns it holds turns
        that strip back into window background. A maximum only, so the window
        is still free to be narrower and scroll.
        """
        table = getattr(self, "table", None)
        model = table.model() if table is not None else None
        if model is None:
            return

        columns = sum(
            self.table.columnWidth(c)
            for c in range(model.columnCount())
            if not self.table.isColumnHidden(c)
        )
        width = columns + self._table_chrome_width()
        if self.table.maximumWidth() == width:
            return
        self.table.setMaximumWidth(width)

    def refit_table(self):
        """Re-fit the table to its contents in both directions."""
        if getattr(self, "table", None) is None:
            return
        self._stretch_notes_column()
        self._fit_table_width()
        self._fit_table_height()

    # ============== Populate Lists ====================
    def pop_lists(self):
        self.populate_creature_list()
        self.populate_monster_list()

    def populate_creature_list(self):
        # Rebuilding the list used to drop the selection, and update_table()
        # runs after every HP change -- so damaging a group meant re-picking it
        # before you could touch it again. Carry the names across the rebuild.
        previously_selected = set(self.selected_creature_names())

        self._syncing_selection = True
        try:
            self.creature_list.clear()
            for row in range(self.table_model.rowCount()):
                creature_name = self.table_model.creature_names[row]
                item = QListWidgetItem(creature_name)
                self.creature_list.addItem(item)
                item.setSelected(creature_name in previously_selected)
        finally:
            self._syncing_selection = False

        # Sized to the combatants actually in the fight, so the HP controls stay
        # directly under the list instead of at the bottom of the window.
        if hasattr(self, "_filter_creature_list"):
            self._filter_creature_list(self.creature_filter.text())
        elif hasattr(self, "_fit_creature_list_height"):
            self._fit_creature_list_height()

        # The rows moved if initiative changed; put the highlight back on them.
        if hasattr(self, "_mirror_list_selection_to_table"):
            self._mirror_list_selection_to_table()

    def populate_monster_list(self):
        prev_selection = (
            self.monster_list.selectedItems()[0].text()
            if self.monster_list.selectedItems() else None
        )

        self.monster_list.blockSignals(True)
        try:
            self.monster_list.clear()
            unique_monster_names = set()

            for row in range(self.table_model.rowCount()):
                creature_name = self.table_model.creature_names[row]
                creature = self.manager.creatures.get(creature_name)

                if creature and creature._type == CreatureType.MONSTER:
                    base_name = creature.statblock_override or re.sub(r'\s*(?:#\s*)?\d+\s*$', '', creature_name)
                    unique_monster_names.add(base_name)

            for name in unique_monster_names:
                self.monster_list.addItem(name)

            # Restore prior selection silently so the statblock isn't spuriously hidden
            if prev_selection:
                for i in range(self.monster_list.count()):
                    if self.monster_list.item(i).text() == prev_selection:
                        self.monster_list.setCurrentRow(i)
                        break
        finally:
            self.monster_list.blockSignals(False)

        # Fitted to the monsters present, then scrolls. Raising the *minimum*
        # here (as this used to) never shrank it: the widget's own size hint
        # kept it at its maximum whatever the content was.
        if self.monster_list.count():
            self._fit_monster_list_height()
            self.monster_list.show()
        else:
            self.monster_list.hide()

    def get_base_name(self, creature):
        non_num_name = re.sub(r'\s*(?:#\s*)?\d+\s*$', '', creature.name)
        base_name = non_num_name.strip()
        return base_name

    # ================== Edit Menu Actions =====================
    def fetch_statblock_for_creature(self, name: str) -> dict | None:
        """Look up a statblock JSON by creature name. Returns dict or None."""
        if not self.storage_api:
            return None
        try:
            from app.statblock_parser import statblock_key
            return self.storage_api.get_statblock(statblock_key(name))
        except Exception:
            return None

    def apply_statblock_slots(self, creature, statblock_name: str) -> bool:
        """Pull spell/innate slots from a statblock onto the creature.

        Only populates if the creature has no slots configured yet.
        Returns True if any slots were applied.
        """
        data = self.fetch_statblock_for_creature(statblock_name)
        if not data:
            return False
        applied = False

        # Limited-use martial abilities (X/Day, Recharge, Legendary Actions).
        # Independent of spellcasting so pure-martial statblocks populate too.
        if not creature._ability_uses:
            from app.statblock_parser import extract_limited_abilities
            ability_uses = extract_limited_abilities(data)
            if ability_uses:
                creature._ability_uses = ability_uses
                creature._ability_uses_used = {k: 0 for k in ability_uses}
                applied = True

        sc = data.get("spellcasting")
        if not sc:
            return applied
        if not creature._spell_slots:
            slots = {
                int(k): v
                for k, v in sc.get("slots", {}).items()
                if v
            }
            if slots:
                creature._spell_slots = slots
                creature._spell_slots_used = {k: 0 for k in slots}
                applied = True
        if not creature._innate_slots:
            innate: dict[str, int] = {}
            for key, spells in sc.get("innate", {}).items():
                import re as _re
                if key == "at_will":
                    uses = -1
                elif m := _re.match(r'(\d+)_per_day', key):
                    uses = int(m.group(1))
                else:
                    uses = 1
                for spell in spells:
                    innate[spell.title()] = uses
            if innate:
                creature._innate_slots = innate
                creature._innate_slots_used = {}
                applied = True
        return applied

    def add_combatant(self):
        self.init_tracking_mode(True)
        dialog = AddCombatantWindow(self, statblock_lookup=self.fetch_statblock_for_creature)
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
                    innate_slots=creature_data.get("_innate_slots", {}),
                    ability_uses=creature_data.get("_ability_uses", {}),
                )
                # If the dialog didn't pick up spell slots (e.g. editingFinished didn't fire),
                # fall back to pulling them from the statblock library.
                if not creature._spell_slots and not creature._innate_slots:
                    self.apply_statblock_slots(creature, creature.name)
                self.manager.add_creature(creature)

            # ✅ Ensure sorting + fields + stable order
            self.manager.sort_creatures()
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            self.build_turn_order()
            self.update_table()

        self.init_tracking_mode(False)

    def add_lair_action_combatant(self):
        from ui.windows import LairActionDialog
        from PyQt5.QtWidgets import QDialog
        dlg = LairActionDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name, init, notes = dlg.get_values()
        creature = Monster(
            name=name,
            init=int(init),
            is_lair_action=True,
            lair_action_notes=notes,
        )
        # Ensure unique name
        base = creature.name
        counter = 1
        while creature.name in self.manager.creatures:
            creature.name = f"{base}_{counter}"
            counter += 1
        self.manager.add_creature(creature)
        self.manager.sort_creatures()
        self.table_model.set_fields_from_sample()
        self.table_model.refresh()
        self.build_turn_order()
        self.update_table()
        self.pop_lists()

    def _show_lair_action_popup(self, creature) -> None:
        from PyQt5.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle(creature.name)
        msg.setIcon(QMessageBox.Information)
        notes = getattr(creature, "_lair_action_notes", "").strip()
        msg.setText(notes if notes else "Lair Action! The lair acts on initiative count.")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

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
                    self._clear_statblock()
            else:
                self._clear_statblock()
        self.init_tracking_mode(False)

    # ====================== Button Logic ======================
    def next_turn(self):
        # 1) Ensure we have an order
        if not getattr(self, "turn_order", None):
            self.build_turn_order()
            if not self.turn_order:
                self._log("[WARNING] No creatures in encounter. Cannot advance turn.")
                toast(self, "No combatants in the encounter", "warning")
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

# 4) On wrap: advance round/time, reset economy, and tick only existing numeric timers
        if wrapped:
            self.round_counter += 1
            self.time_counter += 6

            # Reset action/bonus_action/object_interaction for ALL creatures at top of round
            for cr in self.manager.creatures.values():
                if hasattr(cr, "action"):
                    cr.action = False
                if hasattr(cr, "bonus_action"):
                    cr.bonus_action = False
                if hasattr(cr, "object_interaction"):
                    cr.object_interaction = False

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

        # Reset ONLY reaction on creature's own turn start
        cr = self.manager.creatures[self.current_creature_name]
        if hasattr(cr, "reaction"):
            cr.reaction = False

        self.update_active_ui()

        if getattr(cr, "_is_lair_action", False):
            self._show_lair_action_popup(cr)
            return  # skip Foundry turn command + death saves

        if hasattr(self, "show_status_message"):
            self.show_status_message(f"Turn: {self.current_creature_name}")
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
                self._log("[WARNING] No creatures in encounter. Cannot go back.")
                toast(self, "No combatants in the encounter", "warning")
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

        if cr and getattr(cr, "_is_lair_action", False):
            self._show_lair_action_popup(cr)
            return  # skip Foundry turn command

        self._enqueue_bridge_turn_command("prev")
    # ----------------
    # Path Functions
    # ----------------
    def get_data_path(self, filename):
        return os.path.join(self.get_data_dir(), filename)

    def get_data_dir(self):
        custom = get_local_data_dir()
        if custom:
            data_dir = custom
        elif getattr(sys, "frozen", False):
            data_dir = get_config_path("data")
        else:
            data_dir = os.path.join(self.get_parent_dir(), 'data')
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def get_parent_dir(self):
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.abspath(os.path.join(self.base_dir, '../../'))

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
                        if isinstance(value, int):
                            self._enqueue_bridge_set_hp(creature_name, value)
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
            self._clear_statblock()

    def active_statblock_image(self, creature_name_or_obj):
        # Backward compatibility: accept either name string or creature object
        if isinstance(creature_name_or_obj, str):
            creature = self.manager.creatures[creature_name_or_obj]
        else:
            creature = creature_name_or_obj
        base_name = creature.statblock_override or self.get_base_name(creature)
        self.resize_to_fit_screen(base_name)

    def resize_to_fit_screen(self, base_name):
        if self.storage_api:
            try:
                from app.statblock_parser import statblock_key
                data = self.storage_api.get_statblock(statblock_key(base_name))
                if data:
                    self.statblock_widget.set_storage_api(self.storage_api)
                    self.statblock_widget.load_statblock(data)
                    self.statblock_widget.show()
                    return
                self._log(f"[WARN] No statblock stored for '{base_name}'")
            except Exception as exc:
                self._log(f"[ERROR] Statblock lookup failed for '{base_name}': {exc}")
                toast(self, f"Couldn't load statblock for {base_name}", "warning")
        self._clear_statblock()

    def _clear_statblock(self):
        self.statblock_widget.clear_statblock()
        self.statblock_widget.hide()

    def open_import_statblock_dialog(self):
        from ui.statblock_import_dialog import StatblockImportDialog
        dlg = StatblockImportDialog(storage_api=self.storage_api, parent=self)
        dlg.exec_()

    def open_import_spell_dialog(self):
        from ui.spell_import_dialog import SpellImportDialog
        dlg = SpellImportDialog(storage_api=self.storage_api, parent=self)
        dlg.exec_()

    def open_bulk_item_import_dialog(self):
        from ui.bulk_item_import_dialog import BulkItemImportDialog
        dlg = BulkItemImportDialog(storage_api=self.storage_api, parent=self)
        dlg.exec_()

    def open_shop_generator_dialog(self):
        from ui.shop_generator_dialog import ShopGeneratorDialog
        dlg = ShopGeneratorDialog(storage_api=self.storage_api, bridge_client=getattr(self, 'bridge_client', None), parent=self)
        dlg.exec_()

    def open_lookup_dialog(self):
        from ui.lookup_dialog import LookupDialog
        if not hasattr(self, "_lookup_dialog") or self._lookup_dialog is None:
            self._lookup_dialog = LookupDialog(storage_api=self.storage_api, parent=self)
        self._lookup_dialog.show()
        self._lookup_dialog.raise_()
        self._lookup_dialog.activateWindow()
        self._lookup_dialog.focus_search()

    def hide_statblock(self):
        dock = getattr(self, "statblock_dock", None)
        if dock is not None:
            # Remember how wide it was, so re-showing doesn't snap it back to
            # whatever the config said at startup.
            remember = getattr(self, "remember_dock_width", None)
            if remember is not None:
                remember(dock)
            dock.hide()
        else:
            self.statblock_widget.hide()

    def show_statblock(self):
        dock = getattr(self, "statblock_dock", None)
        if dock is not None:
            dock.show()
            dock.raise_()
            # A dock that was hidden has no width until it is laid out again.
            reapply = getattr(self, "_apply_dock_widths", None)
            if reapply is not None:
                QTimer.singleShot(0, reapply)
        else:
            self.statblock_widget.show()

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

    def apply_hp_delta(self, creature_name: str, value: int, positive: bool) -> bool:
        """Damage or heal one creature. Returns False if the name is unknown.

        The single place HP actually changes, so the dock's bulk controls and
        the per-creature popup on the HP cell can't drift apart on
        concentration checks or bridge sync.
        """
        creature = self.manager.creatures.get(creature_name)
        if not creature:
            return False

        # Snapshot pre-change HP for bridge sync and concentration checks
        pre_hp = int(getattr(creature, "curr_hp", 0) or 0)

        if positive:
            if hasattr(creature, "apply_healing"):
                creature.apply_healing(value)
            else:
                creature.curr_hp += value
        else:
            if hasattr(creature, "apply_damage"):
                damage_taken = creature.apply_damage(value)
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
        return True

    def apply_to_selected_creatures(self, positive: bool):
        try:
            value = int(self.value_input.text())
        except ValueError:
            QMessageBox.warning(self, 'Invalid Input', 'Please enter a valid number')
            return

        selected_names = self.selected_creature_names()
        if not selected_names:
            self.notify("Select a combatant first", "warning")
            return

        for creature_name in selected_names:
            self.apply_hp_delta(creature_name, value, positive)

        self.value_input.clear()
        self.update_table()

        if hasattr(self, "show_status_message") and selected_names:
            names = ", ".join(selected_names)
            action = "Healed" if positive else "Damaged"
            self.show_status_message(f"{action} {names} by {value}")

    def selected_creature_names(self) -> list:
        """The combatants the HP controls act on.

        The list is the authority: the table mirrors its selection into it, so
        rows picked in either place end up here.
        """
        items = self.creature_list.selectedItems()
        return [item.text() for item in items if item and item.text()]

    def apply_hp_mods_to_selected(self, clear: bool = False) -> None:
        selected_names = self.selected_creature_names()
        if not selected_names:
            self.notify("Select a combatant first", "warning")
            return

        temp_hp = 0 if clear else int(getattr(self, "temp_hp_spin", None) and self.temp_hp_spin.value() or 0)
        max_bonus = 0 if clear else int(getattr(self, "max_hp_bonus_spin", None) and self.max_hp_bonus_spin.value() or 0)

        for creature_name in selected_names:
            creature = self.manager.creatures.get(creature_name)
            if creature:
                self._commit_hp_overrides(creature, temp_hp, max_bonus)

        if not clear:
            if hasattr(self, "temp_hp_spin"):
                self.temp_hp_spin.setValue(0)
            if hasattr(self, "max_hp_bonus_spin"):
                self.max_hp_bonus_spin.setValue(0)

        if hasattr(self, "show_status_message") and selected_names:
            if clear:
                self.show_status_message(f"HP mods cleared for {', '.join(selected_names)}")
            else:
                self.show_status_message(f"HP mods applied to {', '.join(selected_names)}")

    # ================= Encounter Builder =====================
    def save_encounter(self):
        dialog = BuildEncounterWindow(self, storage_api=self.storage_api)
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
                innate_slots=creature_data.get("_innate_slots", {}),
                ability_uses=creature_data.get("_ability_uses", {}),
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

    # ================== PC Groups ======================
    # A "PC group" is a saved, named roster of player characters. Handy for
    # switching between a standing campaign party and rotating one-shot groups.
    # Stored in the same backend as encounters, namespaced with a prefix so the
    # two never collide in pickers.
    PC_GROUP_PREFIX = "pcgroup_"
    ACTIVE_PC_GROUP_SETTING = "active_pc_group"

    def _set_active_pc_group(self, key: Optional[str]) -> None:
        """Point the app at a PC group (or None for the default roster).

        Written through to settings.json so Initialize still reloads the right
        party after a restart.
        """
        self.active_pc_group = key
        # Changing the party by hand re-opens the question of whether it matches
        # Foundry; an explicit "Keep Current" dismissal still stands.
        self._pc_group_check_seen.clear()
        self._pc_group_roster_cache.clear()
        try:
            app_settings.set(self.ACTIVE_PC_GROUP_SETTING, key)
        except Exception as e:
            self._log(f"[Groups] Failed to persist active group: {e}")

    def _pc_group_slug(self, name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_").lower()
        return slug or "group"

    def _pc_group_key(self, name: str) -> str:
        return f"{self.PC_GROUP_PREFIX}{self._pc_group_slug(name)}.json"

    def _pc_group_display(self, key: str) -> str:
        base = key[len(self.PC_GROUP_PREFIX):] if key.startswith(self.PC_GROUP_PREFIX) else key
        if base.endswith(".json"):
            base = base[: -len(".json")]
        return base.replace("_", " ").title()

    def list_pc_groups(self) -> List[tuple]:
        """Return sorted list of (display_name, key) for saved PC groups."""
        if not getattr(self, "storage_api", None):
            return []
        out: List[tuple] = []
        try:
            for key in self.storage_api.list():
                if (
                    isinstance(key, str)
                    and key.startswith(self.PC_GROUP_PREFIX)
                    and key.endswith(".json")
                ):
                    out.append((self._pc_group_display(key), key))
        except Exception as e:
            self._log(f"[Groups] list failed: {e}")
        return sorted(out, key=lambda t: t[0].lower())

    def pc_group_exists(self, key: str) -> bool:
        return key in {k for _, k in self.list_pc_groups()}

    # ---- Foundry party vs loaded group ----
    # Running the wrong group is easy to miss: the bridge adds Foundry's PCs to
    # the table alongside whatever roster is loaded, so instead of an obvious
    # error you quietly end up running two parties at once.

    def _foundry_pc_names(self, combatants: List[Dict[str, Any]]) -> Dict[str, str]:
        """Map normalized -> display name for snapshot combatants Foundry calls PCs."""
        names: Dict[str, str] = {}
        for combatant in combatants or []:
            if not isinstance(combatant, dict):
                continue
            if self._resolve_foundry_creature_type(combatant) != CreatureType.PLAYER:
                continue
            display = (combatant.get("actorName") or combatant.get("name") or "").strip()
            key = self._normalize_bridge_name(display)
            if key:
                names.setdefault(key, display)
        return names

    def _pc_group_roster_names(self, key: str) -> set:
        """Normalized PC names in a saved group. Cached — this hits storage."""
        if key in self._pc_group_roster_cache:
            return self._pc_group_roster_cache[key]
        try:
            players = self.get_pc_group_players(key)
        except Exception as e:
            self._log(f"[Groups] Could not read '{key}': {e}")
            return set()
        names = {
            self._normalize_bridge_name(getattr(p, "name", "") or "")
            for p in players
        }
        names.discard("")
        self._pc_group_roster_cache[key] = names
        return names

    def _current_pc_names(self) -> set:
        """Normalized names of the PCs sitting in the table right now."""
        names = {
            self._normalize_bridge_name(self.get_base_name(c))
            for c in self.manager.creatures.values()
            if isinstance(c, Player)
        }
        names.discard("")
        return names

    def _check_pc_group_matches_foundry(self, combatants: List[Dict[str, Any]]) -> None:
        """Warn when Foundry's party isn't the group loaded here, and offer a fix."""
        if self._pc_group_prompt_open:
            return

        foundry_pcs = self._foundry_pc_names(combatants)
        if not foundry_pcs:
            return
        fingerprint = frozenset(foundry_pcs)

        # One evaluation per distinct party, so this doesn't re-run every
        # snapshot. A dismissal also covers any party it's a subset of, so
        # adding a late-arriving PC doesn't re-open a prompt already declined.
        if fingerprint in self._pc_group_check_seen:
            return
        self._pc_group_check_seen.add(fingerprint)
        if any(d <= fingerprint for d in self._pc_group_check_dismissed):
            return

        active_key = self.active_pc_group
        # With no group loaded, the table itself is the roster to compare.
        loaded_names = (
            self._pc_group_roster_names(active_key) if active_key else self._current_pc_names()
        )
        missing = fingerprint - loaded_names
        if not missing:
            return

        # Only suggest a group that accounts for more of Foundry's party than
        # what's loaded; otherwise switching would be a lateral move.
        self._pc_group_roster_cache.clear()
        best_cover = len(fingerprint & loaded_names)
        best_key: Optional[str] = None
        for _display, key in self.list_pc_groups():
            if key == active_key:
                continue
            cover = len(fingerprint & self._pc_group_roster_names(key))
            if cover > best_cover:
                best_cover, best_key = cover, key

        missing_display = ", ".join(sorted(foundry_pcs[k] for k in missing))
        if not best_key:
            msg = f"Foundry PCs not in your roster: {missing_display}"
            self._log(f"[Groups] {msg}")
            if hasattr(self, "show_status_message"):
                self.show_status_message(msg, 8000)
            return

        loaded_label = (
            f"'{self._pc_group_display(active_key)}'" if active_key else "the current table"
        )
        best_label = self._pc_group_display(best_key)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("PC Group Mismatch")
        box.setText("Foundry's party doesn't match the PCs loaded here.")
        box.setInformativeText(
            f"In Foundry but not in {loaded_label}:\n    {missing_display}\n\n"
            f"The saved group '{best_label}' matches Foundry's party more closely.\n"
            "Switch to it? Monsters already in the tracker are kept."
        )
        switch_btn = box.addButton(f"Switch to {best_label}", QMessageBox.AcceptRole)
        box.addButton("Keep Current", QMessageBox.RejectRole)

        self._pc_group_prompt_open = True
        try:
            box.exec_()
        finally:
            self._pc_group_prompt_open = False

        if box.clickedButton() is not switch_btn:
            self._pc_group_check_dismissed.add(fingerprint)
            return
        try:
            self.load_pc_group(best_key)
        except Exception as e:
            report_error(self, "Load Group Failed",
                         "Could not load that PC group.", e)
            return
        if hasattr(self, "show_status_message"):
            self.notify(f"Loaded PC group: {best_label}", "success")

    def save_pc_group_roster(self, key: str, players: List[Player]) -> str:
        """Write an explicit roster to a group key. Returns the key.

        An empty roster is allowed here: the character editor needs to be able
        to create a group and fill it in, and saving a party down to zero PCs is
        a legitimate edit.
        """
        if not getattr(self, "storage_api", None):
            raise RuntimeError("Storage is not configured. Go to File → Settings.")
        state = GameState()
        state.players = list(players)
        state.monsters = []
        state.current_turn = 0
        state.round_counter = 1
        state.time_counter = 0
        self.storage_api.put_json(key, state.to_dict())
        return key

    def save_pc_group(self, name: str) -> str:
        """Save the current player characters as a named group. Returns its key."""
        players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
        if not players:
            raise RuntimeError("There are no player characters to save.")
        key = self.save_pc_group_roster(self._pc_group_key(name), players)
        self._set_active_pc_group(key)
        return key

    def get_pc_group_players(self, key: str) -> List[Player]:
        """Return the saved roster for a group without touching the live table."""
        if not getattr(self, "storage_api", None):
            raise RuntimeError("Storage is not configured.")
        raw = self.storage_api.get_json(key)
        if raw is None:
            raise RuntimeError(f"Group not found: {key}")
        state = json.loads(json.dumps(raw), object_hook=self.custom_decoder)
        return [c for c in (state.get("players", []) or []) if isinstance(c, Player)]

    def delete_pc_group(self, key: str) -> None:
        if not getattr(self, "storage_api", None):
            raise RuntimeError("Storage is not configured.")
        self.storage_api.delete(key)
        if self.active_pc_group == key:
            self._set_active_pc_group(None)

    def load_pc_group(self, key: str) -> None:
        """Swap the current PC roster for the saved group; monsters are kept.

        Loading a group into the app also establishes those names as the
        recognized PCs: when a Foundry snapshot matches them by name they map to
        these Player creatures, so the bridge treats them as party members.
        """
        new_players = self.get_pc_group_players(key)

        preserved_active = getattr(self, "current_creature_name", None)

        # Drop the existing player roster, keep monsters/lair actions intact.
        existing_players = [
            n for n, c in self.manager.creatures.items() if isinstance(c, Player)
        ]
        if existing_players:
            self.manager.rm_creatures(existing_players)

        for creature in new_players:
            name = creature.name
            counter = 1
            while name in self.manager.creatures:
                name = f"{creature.name}_{counter}"
                counter += 1
            creature.name = name
            self.manager.add_creature(creature)

        self._set_active_pc_group(key)
        self.manager.sort_creatures()
        self.table_model.set_fields_from_sample()
        self.table_model.refresh()
        self.build_turn_order()
        if preserved_active in getattr(self, "turn_order", []):
            self.current_creature_name = preserved_active
            self.current_idx = self.turn_order.index(preserved_active)
        self.update_table()
        self.pop_lists()

    # ================== Secondary Windows ======================
    def load_encounter(self):
        dialog = LoadEncounterWindow(self, storage=self.storage_api)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file:
            self.load_file_to_manager(dialog.selected_file, self.manager, prompt_for_initiatives=True)
            # After load, use the active creature from stable order
            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)
            if hasattr(self, "show_status_message"):
                self.notify(f"Loaded encounter: {dialog.selected_file}", "success")

    def merge_encounter(self):
        dialog = LoadEncounterWindow(self, storage=self.storage_api)
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
    
    def open_settings(self):
        """Settings. The dialog offers a restart itself if one is needed.

        This used to end in an unconditional "restart for storage changes to
        take effect" box -- shown even when nothing had changed, and offering
        nothing but an OK button and a manual relaunch.
        """
        from ui.setup_wizard import SetupWizard
        SetupWizard(self).exec_()

    def open_customize_toolbar(self):
        from ui.toolbar_customize_dialog import ToolbarCustomizeDialog
        from PyQt5.QtWidgets import QDialog
        dlg = ToolbarCustomizeDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._apply_toolbar_config()

    def _apply_toolbar_config(self):
        from ui.toolbar_customize_dialog import load_toolbar_items
        self.filetool_bar.clear()
        for action_id in load_toolbar_items():
            if action_id == "separator":
                self.filetool_bar.addSeparator()
                continue
            action = self._toolbar_action_map.get(action_id)
            if action:
                self.filetool_bar.addAction(action)
        # An empty toolbar reads as a broken app, so hide the strip entirely.
        self.filetool_bar.setVisible(bool(self.filetool_bar.actions()))

    def _toolbar_context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Customize Toolbar…", self.open_customize_toolbar)
        menu.addSeparator()
        menu.addAction("Hide Toolbar", lambda: self.filetool_bar.setVisible(False))
        menu.exec_(self.filetool_bar.mapToGlobal(pos))

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

    def notify(self, message: str, level: str = "info") -> None:
        """
        Transient user feedback. Overridden by InitiativeTracker to also raise an
        in-window toast; this base version keeps the app usable headless.
        """
        self._log(message)
        if hasattr(self, "show_status_message"):
            self.show_status_message(message)

    def _log(self, msg: str) -> None:
        """Central logger. Goes to the log file and Help → Show Log."""
        text = str(msg)
        logger = get_logger()
        # Existing call sites tag severity in the message prefix.
        if "[DBG]" in text:
            logger.debug(text)
        elif text.startswith("[ERROR]"):
            logger.error(text)
        elif text.startswith(("[WARN]", "[WARNING]")):
            logger.warning(text)
        else:
            logger.info(text)
