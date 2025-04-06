from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt5.QtGui import QColor
from dataclasses import fields as dataclass_fields

class CreatureTableModel(QAbstractTableModel):
    def __init__(self, manager, fields=None, parent=None):
        super().__init__(parent)
        self.manager = manager

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
                return ""  # No checkmark/✗
            return str(value)

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        if role == Qt.BackgroundRole:
            if attr == '_curr_hp' and value == 0:
                return QColor('darkRed')

            # Color-code boolean attributes
            if isinstance(value, bool):
                return QColor('#006400') if value else QColor('darkRed')

            # Highlight active creature
            if name == self.active_creature_name:
                return QColor('#006400')  # active row

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
            return True
        except (ValueError, TypeError):
            return False

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled

        attr = self.fields[index.column()]
        value = getattr(self.manager.creatures[self.creature_names[index.row()]], attr)

        if isinstance(value, bool):
            # ⛔ Not selectable or editable — just clickable
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
            '_init': 'Init',
            '_curr_hp': 'Curr HP',
            '_max_hp': 'Max HP'
        }
        if field in mapping:
            return mapping[field]
        return field.lstrip('_').replace('_', ' ').title()



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

    def set_active_creature(self, name: str):
        self.active_creature_name = name
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, self.columnCount() - 1),
            [Qt.BackgroundRole]
) 
