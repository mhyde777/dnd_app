from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox
)
from app.config import save_github_token

class TokenPromptWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GitHub Token Setup")

        layout = QVBoxLayout()
        instructions = QLabel("""
        <b>Welcome!</b><br><br>
        To use cloud-based encounter saving, please enter your
        <b>GitHub Personal Access Token</b> (with <code>gist</code> permission).<br><br>
        You can generate one at:<br>
        <a href='https://github.com/settings/tokens'>github.com/settings/tokens</a>
        """)
        instructions.setOpenExternalLinks(True)

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Paste your GitHub token here")
        self.token_input.setEchoMode(QLineEdit.Password)

        save_button = QPushButton("Save Token")
        save_button.clicked.connect(self.save_token)

        layout.addWidget(instructions)
        layout.addWidget(self.token_input)
        layout.addWidget(save_button)
        self.setLayout(layout)

    def save_token(self):
        token = self.token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "Missing Token", "Please paste your GitHub token.")
            return

        save_github_token(token)
        QMessageBox.information(self, "Token Saved", "Your GitHub token has been saved!")
        self.accept()

