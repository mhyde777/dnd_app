from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QHBoxLayout,
    QPushButton, QGroupBox
)


class DeathSavesDialog(QDialog):
    """
    Simple tracker:
      - +Success / +Fail buttons
      - Reset
      - Mark Stable (3 successes) / Dead (3 fails)
    Writes results directly onto the creature object:
      creature.death_successes, creature.death_failures, creature.death_stable
    """
    def __init__(self, creature, parent=None):
        super().__init__(parent)
        self.creature = creature

        self.setWindowTitle(f"Death Saves — {getattr(creature, 'name', 'Creature')}")
        self.setModal(True)

        root = QVBoxLayout(self)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        box = QGroupBox("Track")
        box_layout = QHBoxLayout(box)

        self.btn_succ = QPushButton("+ Success")
        self.btn_fail = QPushButton("+ Fail")
        self.btn_reset = QPushButton("Reset")
        self.btn_close = QPushButton("Close")

        box_layout.addWidget(self.btn_succ)
        box_layout.addWidget(self.btn_fail)
        box_layout.addWidget(self.btn_reset)
        box_layout.addStretch()
        box_layout.addWidget(self.btn_close)

        root.addWidget(box)

        self.btn_succ.clicked.connect(self.add_success)
        self.btn_fail.clicked.connect(self.add_failure)
        self.btn_reset.clicked.connect(self.reset)
        self.btn_close.clicked.connect(self.accept)

        self.refresh()

    def _get(self, attr, default):
        try:
            return getattr(self.creature, attr)
        except Exception:
            return default

    def _set(self, attr, value):
        try:
            setattr(self.creature, attr, value)
        except Exception:
            # fallback if you didn't add properties yet
            setattr(self.creature, f"_{attr}", value)

    def refresh(self):
        succ = int(self._get("death_successes", 0) or 0)
        fail = int(self._get("death_failures", 0) or 0)
        stable = bool(self._get("death_stable", False))

        # Clamp
        succ = max(0, min(3, succ))
        fail = max(0, min(3, fail))

        # Determine state text
        if fail >= 3:
            text = f"Successes: {succ} / 3   Failures: {fail} / 3\nResult: DEAD"
        elif stable or succ >= 3:
            # stable means you stopped tracking; succ>=3 implies stable
            text = f"Successes: {succ} / 3   Failures: {fail} / 3\nResult: STABLE"
            stable = True
        else:
            text = f"Successes: {succ} / 3   Failures: {fail} / 3\nResult: Rolling…"

        self.status_label.setText(text)

        # Persist any clamping/stable inference
        self._set("death_successes", succ)
        self._set("death_failures", fail)
        self._set("death_stable", stable)

        # Disable add buttons if resolved
        resolved = (fail >= 3) or stable
        self.btn_succ.setEnabled(not resolved)
        self.btn_fail.setEnabled(not resolved)

    def add_success(self):
        succ = int(self._get("death_successes", 0) or 0) + 1
        self._set("death_successes", succ)
        self.refresh()

    def add_failure(self):
        fail = int(self._get("death_failures", 0) or 0) + 1
        self._set("death_failures", fail)
        self.refresh()

    def reset(self):
        self._set("death_successes", 0)
        self._set("death_failures", 0)
        self._set("death_stable", False)
        self.refresh()

