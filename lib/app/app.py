import pprint
from typing import Dict, Any, List, Optional
import json, os, re

from PyQt5.QtWidgets import(
   QDialog, QMessageBox,
    QApplication, QFileDialog
) 
from PyQt5.QtGui import (
        QPixmap, QFont
)
from PyQt5.QtCore import (
    Qt, QSize
)
from app.creature import (
    I_Creature, Player, Monster, CustomEncoder, CreatureType
)
from app.save_json import GameState
from app.manager import CreatureManager
from app.gist_utils import load_gist_content, create_or_update_gist, load_gist_index, ensure_index_is_complete
from app.config import get_github_token
from ui.windows import (
    AddCombatantWindow, RemoveCombatantWindow, BuildEncounterWindow, UpdatePlayerWindow
)
from ui.load_encounter_window import LoadEncounterWindow
from ui.gist_status import GistStatusWindow
from ui.delete_gist import DeleteGistWindow
from ui.update_characters import UpdateCharactersWindow
from ui.token_prompt import TokenPromptWindow


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

        self.boolean_fields = {
            '_action': 'set_creature_action',
            '_bonus_action': 'set_creature_bonus_action',
            '_reaction': 'set_creature_reaction'
            # '_object_interaction': 'set_creature_object_interaction'
        }

        if not get_github_token():
            prompt = TokenPromptWindow()
            if prompt.exec_() != QDialog.Accepted:
                raise RuntimeError("GitHub token required to run the app.")

        ensure_index_is_complete()

    # -----------------------
    # Core ordering utilities
    # -----------------------
    def _creature_list_sorted(self) -> List[Any]:
        """Deterministic order: initiative DESC, then name ASC."""
        if not hasattr(self, "manager") or not getattr(self.manager, "creatures", None):
            return []
        creatures = list(self.manager.creatures.values())

        def _init(c):
            try:
                return int(getattr(c, "initiative", 0) or 0)
            except Exception:
                return 0

        def _nm(c):
            try:
                return str(getattr(c, "name", "")).lower()
            except Exception:
                return ""

        creatures.sort(key=lambda c: (-_init(c), _nm(c)))
        return creatures

    def build_turn_order(self) -> None:
        """
        Rebuild the authoritative turn order when creatures/initiatives change.
        Also refresh self.sorted_creatures for legacy code paths that read it.
        """
        creatures = self._creature_list_sorted()
        self.sorted_creatures = creatures[:]  # keep legacy list in sync (sorted)
        self.turn_order = [getattr(c, "name", "") for c in creatures if getattr(c, "name", "")]
        if not self.turn_order:
            self.current_idx = 0
            self.current_creature_name = None
            self.update_active_ui()
            return

        # Preserve pointer by name if possible
        if self.current_creature_name in self.turn_order:
            self.current_idx = self.turn_order.index(self.current_creature_name)
        else:
            if self.current_idx >= len(self.turn_order):
                self.current_idx = max(0, len(self.turn_order) - 1)
            self.current_creature_name = self.turn_order[self.current_idx]

        self.update_active_ui()

    def active_name(self) -> Optional[str]:
        if not self.turn_order:
            return None
        self.current_idx = max(0, min(self.current_idx, len(self.turn_order) - 1))
        return self.turn_order[self.current_idx]

    # ----------------
    # JSON Manipulation
    # ----------------
    def init_players(self):
        from app.gist_utils import load_gist_index

        filename = "players.json"
        
        try:
            index = load_gist_index()
            gist_id = index.get(filename)
            if gist_id:
                raw_url = f"https://gist.githubusercontent.com/{self.get_github_username()}/{gist_id}/raw/{filename}"
                self.load_file_to_manager(raw_url, self.manager)
            else:
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
        from app.gist_utils import load_gist_index

        filename = "last_state.json"
        index = load_gist_index()
        gist_id = index.get(filename)

        if gist_id:
            raw_url = f"https://gist.githubusercontent.com/{self.get_github_username()}/{gist_id}/raw/{filename}"
            self.load_file_to_manager(raw_url, self.manager)
        else:
            self.load_file_to_manager(filename, self.manager)

        if self.manager.creatures:
            self.table_model.set_fields_from_sample()
            # Ensure stable order after load
            self.build_turn_order()

    def save_encounter_to_gist(self, filename: str, description: str = ""):
        from app.gist_utils import create_or_update_gist

        # Prepare state from current encounter
        state = GameState()
        state.players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
        state.monsters = [c for c in self.manager.creatures.values() if isinstance(c, Monster)]
        # Retain legacy counters
        state.current_turn = self.current_turn
        state.round_counter = self.round_counter
        state.time_counter = self.time_counter
        data = state.to_dict()

        # Ensure proper extension
        if not filename.endswith(".json"):
            filename += ".json"

        # Save to Gist
        try:
            response = create_or_update_gist(filename, data, description)
            return response  # you can optionally return the Gist URL or metadata
        except Exception as e:
            raise RuntimeError(f"Failed to save to Gist: {e}")

    def save_as_encounter(self):
        from PyQt5.QtWidgets import QInputDialog, QLineEdit, QMessageBox

        filename, ok = QInputDialog.getText(self, "Save Encounter As", "Enter filename:", QLineEdit.Normal)
        if not ok or not filename.strip():
            return

        filename = filename.strip().replace(" ", "_")

        description, _ = QInputDialog.getText(self, "Description", "Optional description:", QLineEdit.Normal)

        try:
            result = self.save_encounter_to_gist(filename, description)
            gist_url = result["html_url"]
            QMessageBox.information(self, "Saved", f"Gist created:\n{gist_url}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def save_state(self):
        from app.gist_utils import create_or_update_gist

        # Build current game state
        state = GameState()
        state.players = [c for c in self.manager.creatures.values() if isinstance(c, Player)]
        state.monsters = [c for c in self.manager.creatures.values() if isinstance(c, Monster)]
        state.current_turn = self.current_turn
        state.round_counter = self.round_counter
        state.time_counter = self.time_counter

        save = state.to_dict()

        filename = "last_state.json"
        description = "Auto-saved state from initiative tracker"

        try:
            gist_response = create_or_update_gist(filename, save, description=description)
        except Exception as e:
            print(f"[ERROR] Failed to save state to Gist: {e}")

    def load_file_to_manager(self, file_name, manager, monsters=False, merge=False):
        if file_name.startswith("http"):
            raw = load_gist_content(file_name)
            state = json.loads(json.dumps(raw), object_hook=self.custom_decoder)
        else:
            file_path = self.get_data_path(file_name)
            if not os.path.exists(file_path):
                return
            with open(file_path, 'r') as file:
                state = json.load(file, object_hook=self.custom_decoder)

        players = state.get('players', [])
        monsters_list = state.get('monsters', [])

        if monsters and not merge:
            # Only add monsters for encounter loading (not merging or replacing)
            for creature in monsters_list:
                manager.add_creature(creature)
            manager.sort_creatures()
            # Rebuild stable order and UI
            self.build_turn_order()
            self.update_table()
            self.pop_lists()
            return

        if merge:
            # Preserve current active creature name & counters on merge
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

            # No counter resets here
            manager.sort_creatures()
            self.build_turn_order()

            # Try to keep pointer on previously active name
            if preserved_active in self.turn_order:
                self.current_creature_name = preserved_active
                self.current_idx = self.turn_order.index(preserved_active)

            self.update_table()
            self.pop_lists()
            return

        # -------- Full replace path (NOT merge) --------
        manager.creatures.clear()
        for creature in players + monsters_list:
            if isinstance(creature, Player) and not getattr(creature, "active", True):
                continue
            manager.add_creature(creature)

        # Only assign turn/counter values on full replace
        if manager is self.manager:
            self.current_turn = state.get('current_turn', 0)
            self.round_counter = state.get('round_counter', 1)
            self.time_counter = state.get('time_counter', 0)

        manager.sort_creatures()

        # Build stable order and set initial current creature
        self.build_turn_order()
        if self.turn_order and not self.current_creature_name:
            self.current_creature_name = self.turn_order[0]

        self.update_table()
        self.pop_lists()

    def custom_decoder(self, data: Dict[str, Any]) -> Any:
        if '_type' in data:
            return I_Creature.from_dict(data)
        return data

    def get_github_username(self):
        from app.config import get_github_token
        import requests

        token = get_github_token()
        headers = {"Authorization": f"token {token}"}
        response = requests.get("https://api.github.com/user", headers=headers)
        response.raise_for_status()
        return response.json()["login"]

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
        self.table.setFixedSize(total_width + 19, total_height + 2)  # ✅ extra padding for gutter

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
        # Make sure we have a stable order
        if not self.turn_order:
            self.build_turn_order()
            if not self.turn_order:
                print("[WARNING] No creatures in encounter. Cannot advance turn.")
                return

        # Advance pointer
        self.current_idx += 1
        wrapped = False
        if self.current_idx >= len(self.turn_order):
            self.current_idx = 0
            wrapped = True

        if wrapped:
            self.round_counter += 1
            self.time_counter += 6
            # Tick timed statuses down (clamped to 0)
# Tick only existing numeric timers down; do not create new values
        for cr in self.manager.creatures.values():
            st = getattr(cr, "status_time", None)
            if isinstance(st, int) and st > 0:
                cr.status_time = max(0, st - 6)

        # Set active by name
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

        # Monster statblock
        if getattr(cr, "_type", None) == CreatureType.MONSTER:
            self.active_statblock_image(cr)

    def prev_turn(self):
        # Ensure order exists
        if not self.turn_order:
            self.build_turn_order()
            if not self.turn_order:
                print("[WARNING] No creatures in encounter. Cannot go back.")
                return

        # Hard stop at the beginning of combat
        at_absolute_start = (self.round_counter <= 1 and self.time_counter <= 0 and self.current_idx == 0)
        if at_absolute_start:
            # optional: beep or show a tiny status message
            # QApplication.beep()
            return

        wrapped = False
        if self.current_idx == 0:
            self.current_idx = len(self.turn_order) - 1
            wrapped = True
        else:
            self.current_idx -= 1

        if wrapped:
            self.round_counter = max(1, self.round_counter - 1)
            self.time_counter = max(0, self.time_counter - 6)
            # (Recommended) no timer rollback; if you do, guard with isinstance(st, int)

        self.current_creature_name = self.active_name()
        self.update_active_ui()

        cr = self.manager.creatures.get(self.current_creature_name) if self.current_creature_name else None
        if cr and getattr(cr, "_type", None) == CreatureType.MONSTER:
            self.active_statblock_image(cr)

    # ----------------
    # Path Functions
    # ----------------
    def get_image_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'images', filename)

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)

    def get_data_dir(self):
        return os.path.join(self.get_parent_dir(), 'data')
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(self.base_dir, '../../'))

    def get_extensions(self):
        return ('png', 'jpg', 'jpeg', 'gif')

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

        max_width = int(screen_width * 0.4)   # 40% of screen width
        max_height = int(screen_height * 0.9) # 90% of screen height

        extensions = self.get_extensions()
        for ext in extensions:
            image_path = self.get_image_path(f'{base_name}.{ext}')
            if os.path.exists(image_path):
                self.pixmap = QPixmap(image_path)
                scaled_pixmap = self.pixmap.scaled(
                    max_width,
                    max_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
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
            creature = self.manager.creatures[creature_name]
            if creature:
                if positive:
                    creature.curr_hp += value
                else:
                    creature.curr_hp -= value
                    creature.curr_hp = max(0, creature.curr_hp)
        self.value_input.clear()
        self.update_table()

    # ================= Encounter Builder =====================
    def save_encounter(self):
        dialog = BuildEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            metadata = dialog.get_metadata()

            filename = metadata["filename"].replace(" ", "_")
            if not filename.endswith(".json"):
                filename += ".json"
            description = metadata["description"]

            # Build encounter manager with player + added monster data
            encounter_manager = CreatureManager()
            self.load_players_to_manager(encounter_manager)

            for creature_data in data:
                creature=Monster(
                    name=creature_data["_name"],
                    init=creature_data["_init"],
                    max_hp=creature_data["_max_hp"],
                    curr_hp=creature_data["_curr_hp"],
                    armor_class=creature_data["_armor_class"],
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
            save = state.to_dict()

            # Save to Gist
            try:
                gist_response = create_or_update_gist(filename, save, description=description)
                gist_url = gist_response["html_url"]
                raw_url = list(gist_response["files"].values())[0]["raw_url"]
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save gist:\n{e}")

    def load_players_to_manager(self, manager):
        filename = "players.json"
        index = load_gist_index()
        gist_id = index.get(filename)

        if gist_id:
            raw_url = f"https://gist.githubusercontent.com/{self.get_github_username()}/{gist_id}/raw/{filename}"
            self.load_file_to_manager(raw_url, manager, monsters=False)
        else:
            self.load_file_to_manager(filename, manager, monsters=False)

    # ================== Secondary Windows ======================
    def load_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file:
            self.load_file_to_manager(dialog.selected_file, self.manager)
            # After load, use the active creature from stable order
            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)

    def merge_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file:
            self.load_file_to_manager(dialog.selected_file, self.manager, merge=True)

            if not self.current_creature_name and self.turn_order:
                self.current_creature_name = self.turn_order[0]

            name = self.active_name()
            if name:
                cr = self.manager.creatures.get(name)
                if cr and cr._type == CreatureType.MONSTER:
                    self.active_statblock_image(cr)

    def manage_gist_statuses(self):
        dialog = GistStatusWindow(self)
        dialog.exec_()

    def delete_gists(self):
        dialog = DeleteGistWindow(self)
        dialog.exec_()

    def create_or_update_characters(self):
        dialog = UpdateCharactersWindow(self)
        dialog.exec_()

    def on_commit_data(self, editor):
        # print("[COMMIT] Value committed from editor")
        self.manager.sort_creatures()
        # Keep stable order in sync after edits
        self.build_turn_order()
        self.table_model.refresh()
        self.update_table()
        self.update_active_ui()
        self.table.clearSelection()
