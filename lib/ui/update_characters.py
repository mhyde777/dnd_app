# lib/ui/update_characters.py

import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
    QMessageBox,
)

from app.creature import Player
from ui.notifications import report_error

# Sentinel for the "not a saved group" entry in the roster picker.
DEFAULT_ROSTER = ""


class UpdateCharactersWindow(QDialog):
    """
    Create/Update Players.

    Edits one roster at a time, chosen with the picker at the top:
      - the default roster (players.json), or
      - any saved PC group (pcgroup_*.json).

    Defaults to the group currently loaded in the tracker, so editing characters
    while a group is active writes back to that group rather than the global
    roster. Pass ``group_key`` to target a specific group, and ``new_group=True``
    to start an empty roster for a group that doesn't exist yet.

    File format supported on load:
      1) {"players": [<player dicts>], ...}   (preferred)
      2) [<player dicts>]                      (legacy/simple)
    Save format:
      players.json -> {"players": [<player dicts>]}
      pcgroup_*    -> full GameState dict (via Application.save_pc_group_roster)
    """

    def __init__(self, parent=None, group_key=None, new_group=False):
        super().__init__(parent)
        self.app = parent  # main window (InitiativeTracker), also your Application mixin
        self.setWindowTitle("Create/Update Characters")

        self.new_group = bool(new_group)
        if group_key is None and not new_group:
            group_key = getattr(self.app, "active_pc_group", None)
        self.group_key = group_key or DEFAULT_ROSTER

        self.layout = QVBoxLayout(self)

        title = QLabel("Create/Update Characters")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.layout.addWidget(title)

        # Roster picker — which list of PCs these rows belong to.
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Roster:"))
        self.roster_combo = QComboBox()
        picker_row.addWidget(self.roster_combo, 1)
        self.layout.addLayout(picker_row)
        self._populate_roster_combo()
        self.roster_combo.currentIndexChanged.connect(self._on_roster_changed)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Max HP", "AC", "Active", "Public Notes"])
        self.layout.addWidget(self.table)

        # Buttons row: Add Character (left) + Save/Cancel (right)
        self.controls = QHBoxLayout()

        self.add_btn = QPushButton("Add Character")
        self.add_btn.clicked.connect(self.add_character_row)
        self.controls.addWidget(self.add_btn)

        self.delete_btn = QPushButton("Delete Row")
        self.delete_btn.clicked.connect(self.delete_selected_rows)
        self.controls.addWidget(self.delete_btn)

        self.controls.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.save_players)
        self.buttons.rejected.connect(self.reject)
        self.controls.addWidget(self.buttons)

        self.layout.addLayout(self.controls)

        self.load_players()

    # -------------------------
    # Roster picker
    # -------------------------
    def _roster_label(self, key: str) -> str:
        if not key:
            return "Default Roster (players.json)"
        return f"PC Group: {self.app._pc_group_display(key)}"

    def _populate_roster_combo(self):
        """List the default roster plus every saved group, selecting the target."""
        self.roster_combo.blockSignals(True)
        self.roster_combo.clear()
        self.roster_combo.addItem(self._roster_label(DEFAULT_ROSTER), DEFAULT_ROSTER)

        try:
            keys = [k for _, k in self.app.list_pc_groups()]
        except Exception:
            keys = []
        # A brand-new group isn't in storage yet, but must still be selectable.
        if self.group_key and self.group_key not in keys:
            keys.append(self.group_key)

        for key in keys:
            label = self._roster_label(key)
            if key == self.group_key and self.new_group:
                label += "  (new)"
            self.roster_combo.addItem(label, key)

        idx = self.roster_combo.findData(self.group_key)
        self.roster_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.roster_combo.blockSignals(False)

    def _on_roster_changed(self, _index: int):
        new_key = self.roster_combo.currentData() or DEFAULT_ROSTER
        if new_key == self.group_key:
            return
        if self.table.rowCount() and not self._confirm_discard():
            # Snap back to the roster the rows actually belong to.
            self.roster_combo.blockSignals(True)
            idx = self.roster_combo.findData(self.group_key)
            self.roster_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.roster_combo.blockSignals(False)
            return
        was_new = self.new_group
        self.new_group = False
        self.group_key = new_key
        if was_new:
            # Drop the unsaved new group from the list.
            self._populate_roster_combo()
        self.load_players()

    def _confirm_discard(self) -> bool:
        resp = QMessageBox.question(
            self,
            "Switch Roster",
            "Switch rosters? Any unsaved edits to the current list will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return resp == QMessageBox.Yes

    # -------------------------
    # IO (Storage API or local)
    # -------------------------
    def _load_group_payload(self) -> Optional[Dict[str, Any]]:
        """Payload for the selected PC group, or an empty one for a new group."""
        if self.new_group:
            return {"players": []}
        try:
            players = self.app.get_pc_group_players(self.group_key)
        except Exception as e:
            report_error(self, "Load Failed", "That PC group could not be loaded.", e)
            return None
        return {"players": [p.to_dict() for p in players]}

    def _load_players_payload(self) -> Optional[Dict[str, Any]]:
        if self.group_key:
            return self._load_group_payload()

        filename = "players.json"

        # Prefer Storage API (your app uses it when configured)
        storage = getattr(self.app, "storage_api", None)
        if storage is not None:
            try:
                raw = storage.get_json(filename)
                if raw is None:
                    return {"players": []}
                # raw could already be dict/list
                if isinstance(raw, dict):
                    return raw
                if isinstance(raw, list):
                    return {"players": raw}
                return {"players": []}
            except Exception as e:
                report_error(self, "Load Failed",
                             "Could not reach the storage API. Check the address and "
                             "key under File → Settings.", e)
                return None

        # Local fallback: data/players.json
        try:
            path = self.app.get_data_path(filename) if hasattr(self.app, "get_data_path") else filename
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {"players": raw}
            return {"players": []}
        except FileNotFoundError:
            return {"players": []}
        except Exception as e:
            report_error(self, "Load Failed", "Could not read the local players file.", e)
            return None

    def _save_group_payload(self, players: List[Player]) -> bool:
        try:
            self.app.save_pc_group_roster(self.group_key, players)
            return True
        except Exception as e:
            report_error(self, "Save Failed", "That PC group could not be saved.", e)
            return False

    def _save_players_payload(self, payload: Dict[str, Any]) -> bool:
        filename = "players.json"

        # Prefer Storage API
        storage = getattr(self.app, "storage_api", None)
        if storage is not None:
            try:
                storage.put_json(filename, payload)
                return True
            except Exception as e:
                report_error(self, "Save Failed",
                                 "Could not write to the storage API. Your changes are "
                                 "not saved.", e)
                return False

        # Local fallback
        try:
            path = self.app.get_data_path(filename) if hasattr(self.app, "get_data_path") else filename
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception as e:
            report_error(self, "Save Failed", "Could not write the local players file.", e)
            return False

    # -------------------------
    # Table populate / extract
    # -------------------------
    def load_players(self):
        payload = self._load_players_payload()
        if payload is None:
            self.table.setRowCount(0)
            return

        raw_players = payload.get("players", [])
        players: List[Player] = []

        # Use your app's decoder if available, else build Player directly
        for p in raw_players:
            if not isinstance(p, dict):
                continue
            try:
                if hasattr(self.app, "custom_decoder"):
                    # custom_decoder expects dicts and returns Player/Monster/etc when _type present
                    obj = self.app.custom_decoder(p)
                    if isinstance(obj, Player):
                        players.append(obj)
                    else:
                        # If it decoded into a base creature or dict, try Player constructor
                        players.append(self._player_from_dict(p))
                else:
                    players.append(self._player_from_dict(p))
            except Exception:
                players.append(self._player_from_dict(p))

        # Populate rows (no implicit blank row; use Add Character)
        self.table.setRowCount(len(players))
        for row, pl in enumerate(players):
            self._set_row(row, pl)

        self.table.resizeColumnsToContents()

    def add_character_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._init_row(row)

        # Focus Name cell for immediate typing
        self.table.setCurrentCell(row, 0)
        item = self.table.item(row, 0)
        if item is not None:
            self.table.scrollToItem(item)
            self.table.editItem(item)

    def delete_selected_rows(self):
        rows = sorted(
            {idx.row() for idx in self.table.selectedIndexes()}, reverse=True
        )
        if not rows:
            QMessageBox.information(
                self, "No Selection", "Select one or more character rows to delete."
            )
            return
        for row in rows:
            self.table.removeRow(row)

    def _player_from_dict(self, d: Dict[str, Any]) -> Player:
        name = d.get("_name", "") or d.get("name", "") or ""
        max_hp = d.get("_max_hp", d.get("max_hp", 0)) or 0
        ac = d.get("_armor_class", d.get("armor_class", 0)) or 0
        active = d.get("_active", d.get("active", True))
        try:
            max_hp = int(max_hp)
        except Exception:
            max_hp = 0
        try:
            ac = int(ac)
        except Exception:
            ac = 0
        active = bool(active)
        public_notes = d.get("_public_notes", d.get("public_notes", "")) or ""
        player_visible = d.get("_player_visible", True)
        return Player(
            name=name,
            max_hp=max_hp,
            curr_hp=max_hp,
            armor_class=ac,
            active=active,
            public_notes=public_notes,
            player_visible=player_visible,
        )

    def _set_row(self, row: int, pl: Player):
        # Name
        self.table.setItem(row, 0, QTableWidgetItem(str(getattr(pl, "name", "") or "")))

        # Max HP
        self.table.setItem(row, 1, QTableWidgetItem(str(int(getattr(pl, "max_hp", 0) or 0))))

        # AC
        self.table.setItem(row, 2, QTableWidgetItem(str(int(getattr(pl, "armor_class", 0) or 0))))

        # Active checkbox
        active_item = QTableWidgetItem()
        active_item.setFlags(active_item.flags() | Qt.ItemIsUserCheckable)
        active_item.setCheckState(Qt.Checked if bool(getattr(pl, "active", True)) else Qt.Unchecked)
        self.table.setItem(row, 3, active_item)

        # Public Notes
        self.table.setItem(
            row, 4, QTableWidgetItem(str(getattr(pl, "public_notes", "") or ""))
        )

    def _init_row(self, row: int):
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.setItem(row, 2, QTableWidgetItem(""))

        active_item = QTableWidgetItem()
        active_item.setFlags(active_item.flags() | Qt.ItemIsUserCheckable)
        active_item.setCheckState(Qt.Checked)
        self.table.setItem(row, 3, active_item)

        self.table.setItem(row, 4, QTableWidgetItem(""))

    def save_players(self):
        players_out: List[Dict[str, Any]] = []
        players: List[Player] = []

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = (name_item.text().strip() if name_item else "")
            if not name:
                continue

            max_hp_item = self.table.item(row, 1)
            ac_item = self.table.item(row, 2)
            active_item = self.table.item(row, 3)
            public_notes_item = self.table.item(row, 4)

            try:
                max_hp = int((max_hp_item.text().strip() if max_hp_item else "0") or 0)
            except Exception:
                max_hp = 0
            try:
                ac = int((ac_item.text().strip() if ac_item else "0") or 0)
            except Exception:
                ac = 0

            active = True
            if active_item is not None:
                active = active_item.checkState() == Qt.Checked

            public_notes = (public_notes_item.text().strip() if public_notes_item else "")
            pl = Player(
                name=name,
                max_hp=max_hp,
                curr_hp=max_hp,
                armor_class=ac,
                active=active,
                public_notes=public_notes,
            )
            players.append(pl)
            players_out.append(pl.to_dict())

        if self.group_key:
            if not self._save_group_payload(players):
                return
            self.new_group = False
            # Swap the tracker's party over to the group we just wrote, so the
            # editor and the initiative table never disagree.
            try:
                self.app.load_pc_group(self.group_key)
                if hasattr(self.app, "show_status_message"):
                    self.app.show_status_message(
                        f"Saved PC group: {self.app._pc_group_display(self.group_key)}"
                    )
            except Exception as e:
                QMessageBox.warning(
                    self, "Load Failed", f"Group saved, but loading it failed:\n{e}"
                )
            self.accept()
            return

        payload = {"players": players_out}

        if not self._save_players_payload(payload):
            return

        # Optional: refresh the main app's in-memory players immediately
        try:
            if hasattr(self.app, "init_players"):
                self.app.init_players()
        except Exception:
            pass

        self.accept()
