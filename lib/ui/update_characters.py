# lib/ui/update_characters.py

import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
    QMessageBox,
)

from app.creature import Player


class UpdateCharactersWindow(QDialog):
    """
    Create/Update Players.
    Reads/writes players.json via Storage API if configured, else local data/players.json.

    File format supported on load:
      1) {"players": [<player dicts>], ...}   (preferred)
      2) [<player dicts>]                      (legacy/simple)
    Save format:
      {"players": [<player dicts>]}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent  # main window (InitiativeTracker), also your Application mixin
        self.setWindowTitle("Create/Update Characters")

        self.layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Max HP", "AC", "Active"])
        self.layout.addWidget(self.table)

        # Buttons row: Add Character (left) + Save/Cancel (right)
        self.controls = QHBoxLayout()

        self.add_btn = QPushButton("Add Character")
        self.add_btn.clicked.connect(self.add_character_row)
        self.controls.addWidget(self.add_btn)

        self.controls.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.save_players)
        self.buttons.rejected.connect(self.reject)
        self.controls.addWidget(self.buttons)

        self.layout.addLayout(self.controls)

        self.load_players()

    # -------------------------
    # IO (Storage API or local)
    # -------------------------
    def _load_players_payload(self) -> Optional[Dict[str, Any]]:
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
                QMessageBox.warning(self, "Load Failed", f"Failed to load from Storage API:\n{e}")
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
            QMessageBox.warning(self, "Load Failed", f"Failed to load local players.json:\n{e}")
            return None

    def _save_players_payload(self, payload: Dict[str, Any]) -> bool:
        filename = "players.json"

        # Prefer Storage API
        storage = getattr(self.app, "storage_api", None)
        if storage is not None:
            try:
                storage.put_json(filename, payload)
                return True
            except Exception as e:
                QMessageBox.warning(self, "Save Failed", f"Failed to save to Storage API:\n{e}")
                return False

        # Local fallback
        try:
            path = self.app.get_data_path(filename) if hasattr(self.app, "get_data_path") else filename
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", f"Failed to save local players.json:\n{e}")
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
        return Player(name=name, max_hp=max_hp, curr_hp=max_hp, armor_class=ac, active=active)

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

    def _init_row(self, row: int):
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.setItem(row, 2, QTableWidgetItem(""))

        active_item = QTableWidgetItem()
        active_item.setFlags(active_item.flags() | Qt.ItemIsUserCheckable)
        active_item.setCheckState(Qt.Checked)
        self.table.setItem(row, 3, active_item)

    def save_players(self):
        players_out: List[Dict[str, Any]] = []

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = (name_item.text().strip() if name_item else "")
            if not name:
                continue

            max_hp_item = self.table.item(row, 1)
            ac_item = self.table.item(row, 2)
            active_item = self.table.item(row, 3)

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

            pl = Player(name=name, max_hp=max_hp, curr_hp=max_hp, armor_class=ac, active=active)
            players_out.append(pl.to_dict())

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

