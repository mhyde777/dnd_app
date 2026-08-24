# ui/shop_generator_dialog.py
from __future__ import annotations

from typing import Optional

from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QStatusBar, QApplication,
)

from app.shop_generator import generate_shop, BUILTIN_PROFILES


_RARITY_COLORS: dict[str, str] = {
    "common":     "#FFFFFF",
    "uncommon":   "#C8F7C5",
    "rare":       "#C5D9F7",
    "very_rare":  "#E8C5F7",
    "legendary":  "#F7E4C5",
    "artifact":   "#F7C5C5",
}


def _format_shop_html(shop_result: dict) -> str:
    lines: list[str] = []
    lines.append(
        '<html><body style="font-family:sans-serif;">'
        f'<h2>{shop_result["profile_name"]}</h2>'
    )

    for slot in shop_result.get("slots", []):
        if not slot["items"]:
            continue
        lines.append(f'<h3>{slot["label"]}</h3>')
        lines.append(
            '<table border="1" cellpadding="4" cellspacing="0" '
            'style="border-collapse:collapse;width:100%;">'
        )
        lines.append(
            '<tr style="background:#EEEEEE;">'
            '<th>Item</th><th>Qty</th><th>Type</th>'
            '<th>Rarity</th><th>Unit Cost</th><th>Total Value</th>'
            '</tr>'
        )
        for entry in slot["items"]:
            item = entry["item"]
            qty = entry["quantity"]
            cost_gp = item.get("cost_gp", 0.0) or 0.0
            total = cost_gp * qty
            rarity = item.get("rarity", "")
            bg = _RARITY_COLORS.get(rarity, "#FFFFFF")
            lines.append(
                f'<tr style="background:{bg};">'
                f'<td>{item.get("name", "")}</td>'
                f'<td>{qty}</td>'
                f'<td>{item.get("item_type", "")}</td>'
                f'<td>{rarity or "—"}</td>'
                f'<td>{item.get("cost", "") or "—"}</td>'
                f'<td>{total:.2f} gp</td>'
                '</tr>'
            )
        lines.append('</table>')

    total_gp = shop_result.get("total_value_gp", 0.0)
    lines.append(f'<p><strong>Total estimated value: {total_gp:.2f} gp</strong></p>')
    lines.append('</body></html>')
    return "\n".join(lines)


class ShopGeneratorDialog(QDialog):
    """Dialog for generating random shop inventories from the item library."""

    def __init__(self, storage_api=None, bridge_client=None, parent=None):
        super().__init__(parent)
        self.storage_api = storage_api
        self.bridge_client = bridge_client

        self._shop_result: Optional[dict] = None
        self._items: list[dict] = []

        self.setWindowTitle("Shop Generator")
        self.resize(860, 560)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._build_ui()
        self._load_items()

    # ── Layout ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 4)

        # ---- Top controls ----
        controls = QHBoxLayout()
        controls.setSpacing(8)

        controls.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        for key, profile in BUILTIN_PROFILES.items():
            self._profile_combo.addItem(profile["name"], userData=key)
        controls.addWidget(self._profile_combo)

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._on_generate)
        controls.addWidget(self._generate_btn)

        controls.addWidget(QLabel("Seed:"))
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 999_999)
        self._seed_spin.setFixedWidth(90)
        controls.addWidget(self._seed_spin)

        self._use_seed_check = QCheckBox("Use Seed")
        controls.addWidget(self._use_seed_check)

        controls.addStretch()

        # Hidden, not just disabled, when there is no bridge: a greyed-out
        # "Send to Foundry" invites someone who does not use Foundry to wonder
        # what they are missing and how to switch it on.
        self._foundry_btn = QPushButton("Send to Foundry")
        self._foundry_btn.setEnabled(False)
        self._foundry_btn.clicked.connect(self._on_send_to_foundry)
        controls.addWidget(self._foundry_btn)
        self._foundry_btn.setVisible(self._foundry_available())

        layout.addLayout(controls)

        # ---- Results table ----
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Item Name", "Qty", "Type", "Rarity", "Unit Cost", "Total Value", "Tags"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        for col in (1, 2, 3, 4, 5):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._table, stretch=1)

        # ---- Status bar ----
        self._status = QStatusBar()
        self._status.setSizeGripEnabled(False)
        self._status.showMessage("No shop generated yet.")
        layout.addWidget(self._status)

    # ── Item loading ─────────────────────────────────────────────────

    # The library is fetched one item per HTTP request -- there is no bulk
    # endpoint -- so 500 items serially is ten seconds of frozen window at
    # best, and much worse on a slow link. Fetching them concurrently turns
    # that into about a second. Kept at 8 because requests' default connection
    # pool holds 10; going wider just queues and logs pool-full warnings.
    _FETCH_WORKERS = 8

    def _load_items(self, force: bool = False) -> None:
        """Populate self._items, fetching concurrently and caching the result."""
        if self.storage_api is None:
            self._status.showMessage("No storage configured.")
            return
        if self._items and not force:
            return  # already loaded; refetching on every click was the old bug

        try:
            keys = self.storage_api.list_item_keys()
        except Exception as exc:
            self._status.showMessage(f"Failed to load items: {exc}")
            return

        self._status.showMessage(f"Loading {len(keys)} items…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        items: list[dict] = []
        try:
            with ThreadPoolExecutor(max_workers=self._FETCH_WORKERS) as pool:
                for item in pool.map(self._fetch_item, keys):
                    if item:
                        items.append(item)
        finally:
            QApplication.restoreOverrideCursor()

        self._items = items
        self._status.showMessage(f"{len(items)} items loaded.")

    def _fetch_item(self, key: str):
        try:
            return self.storage_api.get_item(key)
        except Exception:
            return None

    # ── Generate ─────────────────────────────────────────────────────

    def _on_generate(self) -> None:
        self._load_items()

        if self.storage_api is None:
            self._status.showMessage("No storage configured.")
            return

        profile_key = self._profile_combo.currentData()
        seed = self._seed_spin.value() if self._use_seed_check.isChecked() else None

        try:
            result = generate_shop(profile_key, self._items, seed=seed)
        except Exception as exc:
            self._status.showMessage(f"Generation failed: {exc}")
            return

        self._shop_result = result

        if not self._use_seed_check.isChecked():
            self._seed_spin.setValue(result["seed"])

        self._populate_table(result)
        self._foundry_btn.setEnabled(bool(result["all_items"]))

        total_gp = result.get("total_value_gp", 0.0)
        item_count = len(result.get("all_items", []))
        self._status.showMessage(
            f"{item_count} items, total value: {total_gp:.2f} gp (estimated)"
        )

    def _populate_table(self, result: dict) -> None:
        self._table.setRowCount(0)

        for slot in result.get("slots", []):
            slot_label = slot["label"]
            entries = sorted(slot["items"], key=lambda e: e["item"].get("name", "").lower())

            for entry in entries:
                item = entry["item"]
                qty = entry["quantity"]
                cost_gp = item.get("cost_gp", 0.0) or 0.0
                total = cost_gp * qty
                rarity = item.get("rarity", "")
                tags = ", ".join(item.get("tags", []))
                desc = item.get("description", "")
                tooltip = desc[:300] + ("…" if len(desc) > 300 else "") if desc else ""

                row = self._table.rowCount()
                self._table.insertRow(row)

                cells = [
                    item.get("name", ""),
                    str(qty),
                    item.get("item_type", ""),
                    rarity or "—",
                    item.get("cost", "") or "—",
                    f"{total:.2f} gp",
                    tags,
                ]

                for col, text in enumerate(cells):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(f"[{slot_label}]\n{tooltip}")
                    if col == 3 and rarity in _RARITY_COLORS:
                        cell.setBackground(QColor(_RARITY_COLORS[rarity]))
                    self._table.setItem(row, col, cell)

    # ── Send to Foundry ───────────────────────────────────────────────

    def _foundry_available(self) -> bool:
        """True only when a bridge exists and is actually configured."""
        if self.bridge_client is None:
            return False
        try:
            from app.config import foundry_bridge_enabled
            if not foundry_bridge_enabled():
                return False
        except Exception:
            pass
        # `enabled` is False without a token, in which case commands are
        # dropped on the floor rather than sent.
        return bool(getattr(self.bridge_client, "enabled", False))

    def _on_send_to_foundry(self) -> None:
        if self._shop_result is None or self.bridge_client is None:
            return

        profile_name = self._shop_result.get("profile_name", "Shop")
        html_content = _format_shop_html(self._shop_result)

        try:
            sent = self.bridge_client.send_create_journal(
                name=f"Shop: {profile_name}",
                content=html_content,
            )
        except Exception as exc:
            self._status.showMessage(f"Send to Foundry failed: {exc}")
            return

        self._status.showMessage(
            f"Sent 'Shop: {profile_name}' to Foundry."
            if sent
            else "Could not queue the command — check the bridge connection."
        )
