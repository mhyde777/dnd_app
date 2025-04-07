from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt
import os, json

from app.creature import Player
from app.gist_utils import load_gist_index, load_gist_content, create_or_update_gist


class UpdateCharactersWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create/Update Characters")

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Name", "Max HP", "AC"])
        self.layout.addWidget(self.table)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.save_players)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        self.filename = "players.json"
        self.index = load_gist_index()

        self.populate_from_gist()

    def populate_from_gist(self):
        try:
            if self.filename in self.index:
                raw_url = f"https://gist.githubusercontent.com/{self.get_github_username()}/{self.index[self.filename]}/raw/{self.filename}"
                content = load_gist_content(raw_url)
                # print(f"[DEBUG] Loaded content: {content}")

                players = content.get("players", [])

                if not players:
                    QMessageBox.information(self, "No Players", "No characters found. Please enter new player data.")
                    self.table.setRowCount(1)
                    return

                self.table.setRowCount(len(players))

                for row, player in enumerate(players):
                    name = player.get("_name", "")
                    hp = player.get("_max_hp", "")
                    ac = player.get("_armor_class", "")

                    self.table.setItem(row, 0, QTableWidgetItem(str(name)))
                    self.table.setItem(row, 1, QTableWidgetItem(str(hp)))
                    self.table.setItem(row, 2, QTableWidgetItem(str(ac)))

                # Resize table to fit contents
                self.table.resizeColumnsToContents()
                self.table.resizeRowsToContents()

                # === Fit calculation ===
                total_width = self.table.verticalHeader().width()
                for col in range(self.table.columnCount()):
                    total_width += self.table.columnWidth(col)
                total_width += self.table.frameWidth() * 2 + 15  # padded slightly wider

                total_height = self.table.horizontalHeader().height()
                for row in range(self.table.rowCount()):
                    total_height += self.table.rowHeight(row)
                total_height += self.table.frameWidth() * 2 # padded slightly taller

                self.table.setFixedSize(total_width, total_height)

                # Dialog frame around it
                margins = self.layout.contentsMargins()
                dialog_width = total_width + margins.left() + margins.right()
                dialog_height = (
                    total_height +
                    self.buttons.sizeHint().height() +
                    margins.top() + margins.bottom() +
                    12  # final top/bottom spacing buffer
                )

                self.setFixedSize(dialog_width, dialog_height)

            else:
                QMessageBox.information(self, "Create New", "No players.json found. Please enter your characters.")
                self.table.setRowCount(1)
                self.table.resizeColumnsToContents()
                self.table.resizeRowsToContents()
                self.setFixedSize(self.sizeHint())

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load players.json:\n{e}")
            self.table.setRowCount(1)
            self.table.resizeColumnsToContents()
            self.table.resizeRowsToContents()
            self.setFixedSize(self.sizeHint())

    def get_github_username(self):
        return os.getenv("GITHUB_USERNAME", "mhyde777")  # fallback

    def save_players(self):
        players = []

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            hp_item = self.table.item(row, 1)
            ac_item = self.table.item(row, 2)

            if name_item and hp_item and ac_item:
                name = name_item.text().strip()
                if name:
                    try:
                        hp = int(hp_item.text())
                        ac = int(ac_item.text())
                        players.append(Player(name=name, max_hp=hp, curr_hp=hp, armor_class=ac)._asdict())
                    except ValueError:
                        QMessageBox.warning(self, "Invalid Input", f"Non-numeric HP or AC in row {row + 1}")
                        return

        if not players:
            QMessageBox.warning(self, "Empty", "No players provided.")
            return

        try:
            payload = {"players": players}
            create_or_update_gist(self.filename, payload, description="Player stat definitions")
            QMessageBox.information(self, "Success", "players.json has been saved to Gist.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save players.json:\n{e}")
