# initiative_tracker.py
from kivy.app import App
from kivy.uix.gridlayout import GridLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.treeview import TreeView, TreeViewLabel
from kivy.properties import NumericProperty, StringProperty, ListProperty
import pandas as pd

class InitiativeTracker(App):
    current_turn = NumericProperty(0)
    round_counter = NumericProperty(1)
    time_counter = NumericProperty(0)
    data = ListProperty([])

    def build(self):
        self.load_data()
        root = GridLayout(cols=2)
        self.create_treeview(root)
        self.create_controls(root)
        return root

    def load_data(self):
        # Load data from DataFrame or CSV file
        self.data = pd.DataFrame({
            'Name': ['Chitra', 'Echo', 'Jorji', 'Surina', 'Val'],
            'Init': [20, 16, 12, 8, 4],
            'Max HP': [27, 21, 21, 28, 25],
            'Cur HP': [27, 21, 21, 28, 25],
            'AC': [16, 17, 15, 16, 15],
            'M': [0, 0, 0, 0, 0],
            'A': [0, 0, 0, 0, 0],
            'BA': [0, 0, 0, 0, 0],
            'R': [0, 0, 0, 0, 0],
            'OI': [0, 0, 0, 0, 0]
        }).sort_values(by='Init', ascending=False).reset_index(drop=True)

    def create_treeview(self, parent):
        self.treeview = TreeView(hide_root=True, size_hint_x=0.7)
        self.treeview.bind('on_select', self.on_tree_select)
        
        for col in self.data.columns:
            self.treeview.add_node(TreeViewLabel(text=col))

        for index, row in self.data.iterrows():
            values = [str(val) for val in row.tolist()]
            self.treeview.add_node(TreeViewLabel(text='\n'.join(values)))

        parent.add_widget(self.treeview)

    def create_controls(self, parent):
        controls_layout = BoxLayout(orientation='vertical', size_hint_x=0.3)

        self.active_initiative_label = Label(text='Active: ', font_size=16)
        self.round_counter_label = Label(text='Round: 1', font_size=16)
        self.time_counter_label = Label(text='Time: 0 seconds', font_size=16)
        self.add_character_button = Button(text='Add Character')
        self.add_character_button.bind(on_release=self.add_character)

        status_buttons_layout = GridLayout(cols=2, padding=10)

        status_buttons_layout.add_widget(Button(text='Action', on_release=lambda btn: self.toggle_status('A')))
        status_buttons_layout.add_widget(Button(text='Bonus Action', on_release=lambda btn: self.toggle_status('BA')))
        status_buttons_layout.add_widget(Button(text='Reaction', on_release=lambda btn: self.toggle_status('R')))
        status_buttons_layout.add_widget(Button(text='Object Interaction', on_release=lambda btn: self.toggle_status('OI')))

        controls_layout.add_widget(self.active_initiative_label)
        controls_layout.add_widget(self.round_counter_label)
        controls_layout.add_widget(self.time_counter_label)
        controls_layout.add_widget(self.add_character_button)
        controls_layout.add_widget(status_buttons_layout)

        parent.add_widget(controls_layout)

    def update_active_initiative(self):
        current_name = self.data.at[self.current_turn, 'Name']
        self.active_initiative_label.text = f"Active: {current_name}"

    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.data):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.text = f"Round: {self.round_counter}"
            self.time_counter_label.text = f"Time: {self.time_counter} seconds"
            self.data[['A', 'BA', 'OI']] = 0
        self.update_active_initiative()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.data) - 1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.text = f"Round: {self.round_counter}"
                self.time_counter_label.text = f"Time: {self.time_counter} seconds"
        else:
            self.current_turn -= 1
        self.update_active_initiative()

    def add_character(self, *args):
        # Add character logic here
        pass

    def toggle_status(self, status):
        row_index = self.current_turn
        current_value = self.data.at[row_index, status]
        self.data.at[row_index, status] = 1 if current_value == 0 else 0

    def on_tree_select(self, instance):
        # Handle treeview selection
        pass

if __name__ == '__main__':
    InitiativeTracker().run()
