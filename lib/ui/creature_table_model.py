from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt5.QtGui import QColor
from dataclasses import fields as dataclass_fields

class CreatureTableModel(QAbstractTableModel):
    def __init__(self, manager, fields=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.active_creature_name = None
        self.selected_index = None  # Store selected index to deselect it later
        self.view = parent  # Store reference to the QTableView instance

        if fields is None and self.manager.creatures:
            sample_creature = next(iter(self.manager.creatures.values()))
            self.fields = [f.name for f in dataclass_fields(sample_creature)]
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

            # ✅ Boolean column formatting (based on boolean state only)
            if is_boolean:
                return QColor("#006400") if value else QColor("darkred")

            # ✅ Non-boolean cell formatting based on HP and active creature
            curr_hp = getattr(creature, "_curr_hp", -1)
            max_hp = getattr(creature, "_max_hp", -1)

            if isinstance(curr_hp, int) and isinstance(max_hp, int) and max_hp > 0:
                hp_ratio = curr_hp / max_hp

                if curr_hp == 0:
                    return QColor("red") if name == self.active_creature_name else QColor("darkRed")
                elif hp_ratio <= 0.5:
                    return QColor("#7a663a") if name == self.active_creature_name else QColor("#5e4e2a")
                elif name == self.active_creature_name:
                    return QColor('#006400')  # dark green

        return QVariant()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()
        name = self.creature_names[row]
        creature = self.manager.creatures[name]
        attr = self.fields[col]

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

            # Deselect the active cell after editing
            self.deselect_active_cell()

            return True
        except (ValueError, TypeError):
            return False

    def deselect_active_cell(self):
        """Deselect the currently selected cell in the view."""
        if self.view:
            self.view.clearSelection()  # Clear selection from QTableView
        self.selected_index = None  # Clear the selected index

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled

        attr = self.fields[index.column()]
        value = getattr(self.manager.creatures[self.creature_names[index.row()]], attr)

        if isinstance(value, bool):
            return Qt.ItemIsEnabled
        else:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return QVariant()

        if orientation == Qt.Horizontal:
            return self.field_to_header(self.fields[section])
        else:
            return str(section + 1)

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
            '_status_time': 'Status'
        }
        return mapping.get(field, field.lstrip('_').replace('_', ' ').title())

    def set_fields_from_sample(self):
        if self.manager.creatures:
            sample = next(iter(self.manager.creatures.values()))
            self.fields = [f.name for f in dataclass_fields(sample)]
            self.layoutChanged.emit()

    def refresh(self):
        self.creature_names = list(self.manager.creatures.keys())
        if not self.fields and self.manager.creatures:
            sample = next(iter(self.manager.creatures.values()))
            self.fields = [f.name for f in dataclass_fields(sample)]

        self.layoutChanged.emit()

        # Force dataChanged for all cells (needed for background updates)
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
        self.layoutChanged.emit()  # Trigger the model to refresh
