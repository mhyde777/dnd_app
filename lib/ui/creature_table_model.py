from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QTimer
from PyQt5.QtGui import QColor, QFont
from dataclasses import fields as dataclass_fields

SPELL_ICON_COLUMN_NAME = "_spellbook"

class CreatureTableModel(QAbstractTableModel):
    def __init__(self, manager, fields=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.active_creature_name = None
        self.selected_index = None
        self.view = parent

        if fields is None and self.manager.creatures:
            sample_creature = next(iter(self.manager.creatures.values()))
            excluded = {"_spell_slots", "_innate_slots", "_spell_slots_used", "_innate_slots_used", "_active"}
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
        name = self.creature_names[row]
        creature = self.manager.creatures[name]
        attr = self.fields[col]

        if attr == SPELL_ICON_COLUMN_NAME:
            from app.creature import CreatureType
            if creature._type != CreatureType.MONSTER:
                return QVariant()

            has_slots = getattr(creature, "_spell_slots", {})
            has_innate = getattr(creature, "_innate_slots", {})

            if role == Qt.DisplayRole and (has_slots or has_innate):
                return "📖"

            if role == Qt.FontRole:
                font = QFont("Noto Color Emoji")
                font.setPointSize(12)
                return font

            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter
            return QVariant()

        value = getattr(creature, attr)

        if role == Qt.DisplayRole:
            if isinstance(value, bool):
                return ""
            if value == 0:
                return ""
            return str(value)

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        if role == Qt.BackgroundRole:
            is_boolean = isinstance(value, bool)
            if is_boolean:
                return QColor("#006400") if value else QColor("darkred")

            curr_hp = getattr(creature, "_curr_hp", -1)
            max_hp = getattr(creature, "_max_hp", -1)

            if isinstance(curr_hp, int) and isinstance(max_hp, int) and max_hp > 0:
                hp_ratio = curr_hp / max_hp
                if curr_hp == 0:
                    return QColor("red") if name == self.active_creature_name else QColor("darkRed")
                elif hp_ratio <= 0.5:
                    return QColor("#7a663a") if name == self.active_creature_name else QColor("#5e4e2a")
                elif name == self.active_creature_name:
                    return QColor('#006400')

        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()
        name = self.creature_names[row]
        creature = self.manager.creatures[name]
        attr = self.fields[col]

        # print(f"[SETDATA] {name} - {attr} -> {value}")

        try:
            if isinstance(getattr(creature, attr), bool):
                setattr(creature, attr, value == Qt.Checked)
            elif isinstance(getattr(creature, attr), int):
                setattr(creature, attr, int(value))
            elif isinstance(getattr(creature, attr), str):
                setattr(creature, attr, str(value))
            else:
                return False

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            self.deselect_active_cell()

            if attr == "_init" and self.view:
                # print("[DEBUG] Scheduling initiative refresh...")
                QTimer.singleShot(0, self.view.handle_initiative_update)

            return True
        except (ValueError, TypeError):
            return False

    def deselect_active_cell(self):
        if self.view:
            self.view.clearSelection()
        self.selected_index = None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled

        attr = self.fields[index.column()]
        if attr == SPELL_ICON_COLUMN_NAME:
            creature = self.manager.creatures[self.creature_names[index.row()]]
            from app.creature import CreatureType
            if creature._type == CreatureType.MONSTER:
                return Qt.ItemIsEnabled | Qt.ItemIsSelectable
            return Qt.NoItemFlags

        value = getattr(self.manager.creatures[self.creature_names[index.row()]], attr)

        if isinstance(value, bool):
            return Qt.ItemIsEnabled
        else:
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
            '_type': '',
            '_name': 'Name',
            '_init': 'Init',
            '_curr_hp': 'Curr HP',
            '_max_hp': 'Max HP',
            '_armor_class': 'AC',
            '_movement': 'M',
            '_action': 'A',
            '_bonus_action': 'BA',
            '_reaction': 'R',
            '_object_interaction': 'OI',
            '_notes': 'Notes',
            '_status_time': 'Status',
            '_spellbook': '📖'
        }
        return mapping.get(field, field.lstrip('_').replace('_', ' ').title())

    def set_fields_from_sample(self):
        if self.manager.creatures:
            sample = next(iter(self.manager.creatures.values()))
            excluded = {"_spell_slots", "_innate_slots", "_spell_slots_used", "_innate_slots_used", "_active"}
            self.fields = [f.name for f in dataclass_fields(sample) if f.name not in excluded]
            if SPELL_ICON_COLUMN_NAME not in self.fields:
                self.fields.append(SPELL_ICON_COLUMN_NAME)
            self.layoutChanged.emit()

    def refresh(self):
        sorted_items = sorted(
            self.manager.creatures.items(),
            key=lambda item: item[1].initiative,
            reverse=True
        )
        self.creature_names = [name for name, _ in sorted_items]
        # print("[REFRESH] Sorted creature_names:", self.creature_names)

        if not self.fields and self.manager.creatures:
            sample = next(iter(self.manager.creatures.values()))
            excluded = {"_spell_slots", "_innate_slots", "_spell_slots_used", "_innate_slots_used"}
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
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, self.columnCount() - 1),
            [Qt.BackgroundRole]
        )

    def set_creatures(self, creatures):
        self.creatures = creatures
        self.layoutChanged.emit()
