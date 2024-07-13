class WidgetLogic:
    def update_active_init(self):
        current_name = self.data.at[self.current_turn, 'Name']
        self.active_init_label.setText(f"Active: {current_name}")

        self.table.selectRow(self.current_turn)


    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.data):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        self.update_active_init()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.data) - 1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        else:
            self.current_turn -= 1
        self.update_active_init()

    def load_encounter(self):
        pass

    def add_combat(self):
        pass

    def rmv_combat(self):
        pass




