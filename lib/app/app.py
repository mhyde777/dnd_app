# from PyQt5.QtWidgets import QDialogButtonBox, QPushButton

class Application:

    def __init__(self):
        self.manager = self.CreatureManager()

        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        
        self.update_active_init()

    def update_active_init(self):
        current_name = self.manager.creatures[self.current_turn].name 
        self.active_init_label.setText(f"Active: {current_name}")
        self.table.selectRow()

    def __init__(self) -> None:
        pass

    def load_encounter(self):
        pass

    def add_combatant(self):
        pass

    def remove_combatant(self):
        pass

    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.manager.creatures):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        self.update_active_init()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.manager.creatures) -1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        else:
            self.current_turn -= 1
        self.update_active_init()
