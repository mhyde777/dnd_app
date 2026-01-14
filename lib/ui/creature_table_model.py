from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QTimer
from PyQt5.QtGui import QColor, QFont
from dataclasses import fields as dataclass_fields

SPELL_ICON_COLUMN_NAME = "_spellbook"
_COND_ABBR = {
    "Blinded": "Bli",
    "Charmed": "Cha",
    "Concentrating": "Conc",
    "Deafened": "Dea",
    "Exhaustion": "Exh",
    "Frightened": "Fgt",
    "Grappled": "Grp",
    "Incapacitated": "Inc",
    "Invisible": "Inv",
    "Paralyzed": "Par",
    "Petrified": "Pet",
    "Poisoned": "Poi",
    "Prone": "Pro",
    "Restrained": "Res",
    "Stunned": "Stun",
    "Unconscious": "Unc",
}

class CreatureTableModel(QAbstractTableModel):
    def __init__(self, manager, fields=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.active_creature_name = None
        self.selected_index = None
        self.view = parent

        # Build fields from a sample creature if not provided
        if fields is None and self.manager.creatures:
            excluded = {
                "_spell_slots",
                "_innate_slots",
                "_spell_slots_used",
                "_innate_slots_used",
                "_death_successes",
                "_death_failures",
                "_death_stable",
                "_death_saves_prompt",
                "_active",
            }
            sample = next(iter(self.manager.creatures.values()))
            self.fields = [f.name for f in dataclass_fields(sample) if f.name not in excluded]

            if SPELL_ICON_COLUMN_NAME not in self.fields:
                self.fields.append(SPELL_ICON_COLUMN_NAME)
        else:
            self.fields = fields or []

        self.creature_names = list(self.manager.creatures.keys())

    def rowCount(self, parent=QModelIndex()):
        return len(self.creature_names)

    def columnCount(self, parent=QModelIndex()):
        return len(self.fields)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return QVariant()

        row = index.row()
        col = index.column()

        # Guard against stale row indices
        if row < 0 or row >= len(self.creature_names):
            return QVariant()

        name = self.creature_names[row]
        creature = self.manager.creatures.get(name)
        if creature is None:
            return QVariant()

        attr = self.fields[col]

        # Conditions: display as comma-separated string (read-only)
        if attr == "_conditions":
            try:
                conds = getattr(creature, "conditions", []) or []
                conds = list(conds)
            except Exception:
                conds = []

            if role == Qt.DisplayRole:
                if not conds:
                    return ""
                abbrs = [_COND_ABBR.get(c, c[:4]) for c in conds]
                return " • ".join(abbrs)

            if role == Qt.ToolTipRole:
                return "\n".join(conds) if conds else ""

            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter

        if attr == "_player_visible":
            from app.creature import CreatureType

            if creature._type != CreatureType.MONSTER:
                return QVariant()

            if role == Qt.CheckStateRole:
                return Qt.Checked if getattr(creature, "player_visible", False) else Qt.Unchecked

            if role == Qt.DisplayRole:
                return ""

            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter

            return QVariant()

        # Spellbook icon column
        if attr == SPELL_ICON_COLUMN_NAME:
            from app.creature import CreatureType

            if creature._type != CreatureType.MONSTER:
                return QVariant()

            has_slots = getattr(creature, "_spell_slots", {}) or {}
            has_innate = getattr(creature, "_innate_slots", {}) or {}

            if role == Qt.DisplayRole and (has_slots or has_innate):
                return "📖"

            if role == Qt.FontRole:
                font = QFont("Noto Color Emoji")
                font.setPointSize(12)
                return font

            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter

            return QVariant()

        # Default: read raw attribute value
        try:
            value = getattr(creature, attr)
        except Exception:
            return QVariant()

        if role == Qt.DisplayRole:
            if isinstance(value, bool):
                return ""
            if value == 0:
                return ""
            return str(value)

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        if role == Qt.BackgroundRole:
            # Boolean columns: green/red
            if isinstance(value, bool):
                return QColor("#006400") if value else QColor("darkred")
           
            # Death save visuals (Players only)
            try:
                succ = int(getattr(creature, "_death_successes", 0) or 0)
                fail = int(getattr(creature, "_death_failures", 0) or 0)
                stable = bool(getattr(creature, "_death_stable", False))
            except Exception:
                succ = fail = 0
                stable = False

            is_active = (name == self.active_creature_name)

            # dead = gray (slightly lighter if active)
            if fail >= 3:
                return QColor("#808080") if is_active else QColor("#6b6b6b")

            # stable = blue (slightly brighter if active)
            if stable:
                return QColor("#3a74c8") if is_active else QColor("#2b5aa6")

            if role == Qt.ForegroundRole:
                try:
                    fail = int(getattr(creature, "_death_failures", 0) or 0)
                except Exception:
                    fail = 0
                if fail >= 3:
                    return QColor("#e6e6e6")  # light text on gray

            # HP-based coloring + active row
            curr_hp = getattr(creature, "_curr_hp", -1)
            max_hp = getattr(creature, "_max_hp", -1)

            if isinstance(curr_hp, int) and isinstance(max_hp, int) and max_hp > 0:
                hp_ratio = curr_hp / max_hp

                if curr_hp == 0:
                    return QColor("red") if name == self.active_creature_name else QColor("darkRed")

                if hp_ratio <= 0.5:
                    return QColor("#7a663a") if name == self.active_creature_name else QColor("#5e4e2a")

                if name == self.active_creature_name:
                    return QColor("#006400")

        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self.creature_names):
            return False

        name = self.creature_names[row]
        creature = self.manager.creatures.get(name)
        if creature is None:
            return False

        attr = self.fields[col]

        # Explicitly block edits to conditions in-table (use the checkbox panel instead)
        if attr == "_conditions":
            return False

        try:
            current = getattr(creature, attr)

            if isinstance(current, bool):
                setattr(creature, attr, value == Qt.Checked)
            elif isinstance(current, int):
                setattr(creature, attr, int(value))
            elif isinstance(current, str):
                setattr(creature, attr, str(value))
            else:
                return False

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            self.deselect_active_cell()

            if attr == "_init" and self.view:
                QTimer.singleShot(0, self.view.handle_initiative_update)

            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def deselect_active_cell(self):
        if self.view:
            self.view.clearSelection()
        self.selected_index = None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self.creature_names):
            return Qt.ItemIsEnabled

        attr = self.fields[col]
        creature = self.manager.creatures.get(self.creature_names[row])

        if attr == SPELL_ICON_COLUMN_NAME:
            if creature is None:
                return Qt.NoItemFlags

            from app.creature import CreatureType

            if creature._type == CreatureType.MONSTER:
                return Qt.ItemIsEnabled | Qt.ItemIsSelectable
            return Qt.NoItemFlags

        if attr == "_conditions":
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if creature is None:
            return Qt.NoItemFlags
        
        if attr == "_player_visible":
            from app.creature import CreatureType

            if creature._type != CreatureType.MONSTER:
                return Qt.NoItemFlags
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

        if attr == "_player_visible":
            from app.creature import CreatureType

            if creature._type != CreatureType.MONSTER:
                return Qt.NoItemFlags
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

        try:
            value = getattr(creature, attr)
        except Exception:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if isinstance(value, bool):
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            field = self.fields[section]

            if role == Qt.DisplayRole:
                return self.field_to_header(field)

            if role == Qt.FontRole and field == SPELL_ICON_COLUMN_NAME:
                font = QFont("Noto Color Emoji")
                font.setPointSize(12)
                return font

        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return str(section + 1)

        return QVariant()

    def field_to_header(self, field):
        mapping = {
            "_type": "",
            "_name": "Name",
            "_init": "Init",
            "_curr_hp": "Curr HP",
            "_max_hp": "Max HP",
            "_armor_class": "AC",
            "_movement": "M",
            "_action": "A",
            "_bonus_action": "BA",
            "_reaction": "R",
            "_object_interaction": "OI",
            "_notes": "Notes",
            "_public_notes": "Public Notes",
            "_player_visible": "Show",
            "_conditions": "Conditions",
            "_status_time": "Status",
            "_spellbook": "📖",
        }
        return mapping.get(field, field.lstrip("_").replace("_", " ").title())

    def set_fields_from_sample(self):
        if not self.manager.creatures:
            return

        excluded = {
            "_spell_slots",
            "_innate_slots",
            "_spell_slots_used",
            "_innate_slots_used",
            "_death_successes",
            "_death_failures",
            "_death_stable",
            "_death_saves_prompt",
            "_active",
        }
        sample = next(iter(self.manager.creatures.values()))
        self.fields = [f.name for f in dataclass_fields(sample) if f.name not in excluded]

        if SPELL_ICON_COLUMN_NAME not in self.fields:
            self.fields.append(SPELL_ICON_COLUMN_NAME)

        self.layoutChanged.emit()

    def refresh(self):
        # Always sort by initiative desc
        if hasattr(self.manager, "ordered_items"):
            sorted_items = self.manager.ordered_items()
        else:
            sorted_items = sorted(
                self.manager.creatures.items(),
                key=lambda item: item[1].initiative,
                reverse=True,
            )
        self.creature_names = [name for name, _ in sorted_items]

        # If fields were never initialized (edge-case), rebuild them consistently
        if not self.fields and self.manager.creatures:
            excluded = {
                "_spell_slots",
                "_innate_slots",
                "_spell_slots_used",
                "_innate_slots_used",
                "_death_saves_prompt",
                "_active",
            }
            sample = next(iter(self.manager.creatures.values()))
            self.fields = [f.name for f in dataclass_fields(sample) if f.name not in excluded]
            if SPELL_ICON_COLUMN_NAME not in self.fields:
                self.fields.append(SPELL_ICON_COLUMN_NAME)

        self.layoutChanged.emit()

        if self.rowCount() > 0 and self.columnCount() > 0:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.BackgroundRole])

    def set_active_creature(self, name: str):
        self.active_creature_name = name
        if self.rowCount() <= 0 or self.columnCount() <= 0:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, self.columnCount() - 1),
            [Qt.BackgroundRole],
        )

    def set_creatures(self, creatures):
        # Keep the model consistent with how everything else reads creatures
        self.manager.creatures = creatures
        self.refresh()
