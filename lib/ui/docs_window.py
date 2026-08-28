"""
Help → Documentation: the shipped docs, readable beside the app.

Deliberately **not** modal. The whole point is to follow instructions while
doing the thing they describe -- set up Foundry with the Foundry page open,
work through storage providers with the storage page open. A modal dialog
would make you close the instructions to act on them.

Markdown is converted to HTML here rather than handed to
`QTextBrowser.setMarkdown()`, which looks like it would do the job and does
not: Qt's importer drops fenced code blocks to ordinary paragraphs. In docs
that are largely shell commands and directory layouts that is not a cosmetic
loss -- the reader cannot tell a command from prose, and the indentation that
carries the meaning of a tree listing is gone. It also emits no heading
anchors, so a cross-link like `architecture.md#storage-providers` would land
at the top of the page.
"""
from __future__ import annotations

import html as html_module
import re
from typing import Dict, List, Optional, Tuple

import markdown
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.sane_lists import SaneListExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QDesktopServices,
    QKeySequence,
    QTextCursor,
    QTextDocument,
)
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import app.settings as settings
from app import docs_content
from ui import colors

_GEOMETRY_KEY = "docs_window_geometry"
_SPLITTER_KEY = "docs_window_splitter"

#: Extensions are passed as *instances*, not names. Python-Markdown resolves a
#: name through importlib entry points, which PyInstaller's static analysis
#: cannot see -- a packaged build would raise "Failed loading extension" the
#: first time someone opened this window.
_EXTENSIONS = [
    TableExtension(),
    FencedCodeExtension(),
    SaneListExtension(),
    TocExtension(anchorlink=False, permalink=False),
]


def _stylesheet() -> str:
    """CSS for the rendered page, built from the live palette.

    Qt's rich text engine supports a subset of CSS 2.1, so this stays to
    colours, fonts, padding and borders -- no flexbox, no pseudo-elements.
    Read through `colors.X` attribute access, never `from ui.colors import X`,
    so a palette the user has changed is picked up here too.
    """
    return f"""
    body {{
        color: {colors.TEXT_PRIMARY};
        background-color: {colors.BG_DARK};
        font-size: 10.5pt;
    }}
    h1 {{ color: {colors.ACCENT_GOLD}; font-size: 19pt; }}
    h2 {{ color: {colors.ACCENT_GOLD}; font-size: 15pt; }}
    h3 {{ color: {colors.ACCENT_GOLD_DIM}; font-size: 12.5pt; }}
    h4, h5, h6 {{ color: {colors.ACCENT_GOLD_DIM}; font-size: 11pt; }}
    a {{ color: {colors.ACCENT_GOLD}; }}
    code {{
        font-family: monospace;
        background-color: {colors.BG_PANEL};
        color: {colors.TEXT_PRIMARY};
    }}
    pre {{
        font-family: monospace;
        background-color: {colors.BG_PANEL};
        color: {colors.TEXT_PRIMARY};
    }}
    blockquote {{
        color: {colors.TEXT_SECONDARY};
        background-color: {colors.BG_PANEL};
    }}
    th {{
        background-color: {colors.BG_PANEL};
        color: {colors.ACCENT_GOLD};
    }}
    hr {{ color: {colors.BORDER}; }}
    """


#: Images fetched over the network -- the README's build badges, mostly.
#: QTextBrowser will not load them (no network in the rich text engine), so
#: each one renders as a broken-image glyph. They are decoration that means
#: nothing in an offline help window, so they are dropped rather than shown
#: broken. Local images are left alone; `_SEARCH_PATHS` resolves them.
_REMOTE_IMG_RE = re.compile(r'<img[^>]+src="https?://[^"]*"[^>]*>', re.IGNORECASE)


def render(markdown_text: str) -> str:
    """Markdown to a full HTML document, themed and with heading anchors."""
    converter = markdown.Markdown(extensions=_EXTENSIONS)
    body = converter.convert(markdown_text)
    body = _REMOTE_IMG_RE.sub("", body)
    # Qt draws no table rules from CSS alone; the border attribute is what it
    # actually honours, and these docs lean on tables heavily.
    body = body.replace(
        "<table>", '<table border="1" cellpadding="5" cellspacing="0" width="100%">'
    )
    return f"<html><head><style>{_stylesheet()}</style></head><body>{body}</body></html>"


class DocsWindow(QDialog):
    """Contents on the left, the document on the right."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Documentation")
        # A real window, not a dialog stuck on top of the tracker: it gets its
        # own taskbar entry, minimise and maximise, and can sit beside the
        # main window on a second monitor.
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1000, 720)

        self._sections = docs_content.available()
        self._history: List[str] = []
        self._history_index = -1
        self._current: Optional[str] = None
        self._item_for_file: Dict[str, QListWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(self._build_toolbar())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self._build_contents())
        self.splitter.addWidget(self._build_viewer())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 750])
        root.addWidget(self.splitter, stretch=1)

        self.find_bar = self._build_find_bar()
        root.addWidget(self.find_bar)
        self.find_bar.setVisible(False)

        self._install_shortcuts()
        self._restore_geometry()

        first = docs_content.first_doc()
        if first is not None:
            self.show_doc(first.filename)
        else:
            self.viewer.setHtml(render(
                "# No documentation in this build\n\n"
                "The Markdown files were not packaged with this version. They "
                "are in the `docs/` directory of the repository."
            ))

    # ---- construction ----

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedWidth(36)
        self.back_btn.setToolTip("Back (Alt+Left)")
        self.back_btn.clicked.connect(self.go_back)
        self.forward_btn = QPushButton("→")
        self.forward_btn.setFixedWidth(36)
        self.forward_btn.setToolTip("Forward (Alt+Right)")
        self.forward_btn.clicked.connect(self.go_forward)

        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            f"color: {colors.ACCENT_GOLD}; font-weight: bold;"
        )

        find_btn = QPushButton("Find…")
        find_btn.setToolTip("Search this page (Ctrl+F)")
        find_btn.clicked.connect(self.open_find)

        row.addWidget(self.back_btn)
        row.addWidget(self.forward_btn)
        row.addSpacing(8)
        row.addWidget(self.title_label, stretch=1)
        row.addWidget(find_btn)
        return row

    def _build_contents(self) -> QWidget:
        self.contents = QListWidget()
        self.contents.setAlternatingRowColors(False)
        for heading, docs in self._sections:
            header = QListWidgetItem(heading.upper())
            # A heading, not a destination: clicking it must do nothing.
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QColor(colors.TEXT_SECONDARY))
            self.contents.addItem(header)
            for doc in docs:
                item = QListWidgetItem(f"   {doc.title}")
                item.setData(Qt.UserRole, doc.filename)
                item.setToolTip(doc.blurb)
                self.contents.addItem(item)
                self._item_for_file[doc.filename] = item
        self.contents.itemClicked.connect(self._on_contents_clicked)
        return self.contents

    def _build_viewer(self) -> QWidget:
        self.viewer = QTextBrowser()
        # So a relative <img src="images/x.png"> in a doc resolves. Links are
        # still routed by hand below; this only affects embedded resources.
        self.viewer.setSearchPaths([str(root) for root in docs_content.roots()])
        # Links are resolved here, not by QTextBrowser: it would try to load a
        # relative .md path off disk as a document and blank the page.
        self.viewer.setOpenLinks(False)
        self.viewer.setOpenExternalLinks(False)
        self.viewer.anchorClicked.connect(self._on_link_clicked)
        return self.viewer

    def _build_find_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find in this page…")
        self.find_edit.returnPressed.connect(self.find_next)
        self.find_edit.textChanged.connect(self._on_find_text_changed)
        prev_btn = QPushButton("Previous")
        prev_btn.clicked.connect(self.find_previous)
        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self.find_next)
        close_btn = QPushButton("Done")
        close_btn.setToolTip("Close the find bar (Escape)")
        close_btn.clicked.connect(self.close_find)
        self.find_status = QLabel()
        self.find_status.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")

        row.addWidget(QLabel("Find:"))
        row.addWidget(self.find_edit, stretch=1)
        row.addWidget(self.find_status)
        row.addWidget(prev_btn)
        row.addWidget(next_btn)
        row.addWidget(close_btn)
        return bar

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence.Find, self, self.open_find)
        QShortcut(QKeySequence("F3"), self, self.find_next)
        QShortcut(QKeySequence("Shift+F3"), self, self.find_previous)
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, self.go_forward)

    # ---- navigation ----

    def show_doc(self, filename: str, anchor: str = "", record: bool = True) -> None:
        """Render a doc, optionally scrolled to one of its headings."""
        text = docs_content.read(filename)
        if text is None:
            self.viewer.setHtml(render(
                f"# Not found\n\n`{html_module.escape(filename)}` is not part "
                "of this build."
            ))
            self.title_label.setText(filename)
            return

        if record:
            self._push_history(filename)
        self._current = filename
        self.viewer.setHtml(render(text))

        doc = docs_content.find(filename)
        self.title_label.setText(doc.title if doc else filename)
        self._select_in_contents(filename)

        if anchor:
            self.viewer.scrollToAnchor(anchor)
        else:
            self.viewer.verticalScrollBar().setValue(0)
        self._update_nav_buttons()

    def _push_history(self, filename: str) -> None:
        if self._history[self._history_index:self._history_index + 1] == [filename]:
            return
        # Following a link after going back discards the forward entries, the
        # same as a browser.
        del self._history[self._history_index + 1:]
        self._history.append(filename)
        self._history_index = len(self._history) - 1

    def go_back(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            self.show_doc(self._history[self._history_index], record=False)

    def go_forward(self) -> None:
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.show_doc(self._history[self._history_index], record=False)

    def _update_nav_buttons(self) -> None:
        self.back_btn.setEnabled(self._history_index > 0)
        self.forward_btn.setEnabled(self._history_index < len(self._history) - 1)

    def _select_in_contents(self, filename: str) -> None:
        item = self._item_for_file.get(filename)
        if item is not None:
            self.contents.setCurrentItem(item)
        else:
            self.contents.clearSelection()

    def _on_contents_clicked(self, item: QListWidgetItem) -> None:
        filename = item.data(Qt.UserRole)
        if filename:
            self.show_doc(filename)

    def _on_link_clicked(self, url: QUrl) -> None:
        """Route a link: another doc, a heading here, or the web."""
        raw = url.toString()

        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return

        # A bare "#heading" is a jump inside the page we are already on.
        if raw.startswith("#"):
            self.viewer.scrollToAnchor(raw[1:])
            return

        path, _, anchor = raw.partition("#")
        if not path:
            self.viewer.scrollToAnchor(anchor)
            return

        if docs_content.resolve(path) is not None:
            self.show_doc(path, anchor=anchor)
            return

        # A relative link to something not shipped (a source file, an image).
        # Better to say so than to blank the page.
        self.viewer.setHtml(render(
            f"# Not available here\n\n`{html_module.escape(path)}` is part of "
            "the repository but is not shipped with the app.\n\n"
            "[Browse the repository](https://github.com/mhyde777/dnd_app)"
        ))
        self.title_label.setText(path)

    # ---- find ----

    def open_find(self) -> None:
        self.find_bar.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_find(self) -> None:
        self.find_bar.setVisible(False)
        self.find_status.clear()
        self.viewer.setFocus()

    def keyPressEvent(self, event) -> None:
        """Escape closes the find bar first, the window second.

        Overridden rather than bound as a QShortcut because QDialog already
        maps Escape to reject(); with both in play which one wins is not
        something to leave to chance, and losing the window on a stray Escape
        mid-search would be a nasty surprise.
        """
        if event.key() == Qt.Key_Escape and self.find_bar.isVisible():
            self.close_find()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_find_text_changed(self, _text: str) -> None:
        self.find_status.clear()

    def find_next(self) -> None:
        self._search(backwards=False)

    def find_previous(self) -> None:
        self._search(backwards=True)

    def _search(self, backwards: bool) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        flags = QTextDocument.FindBackward if backwards else QTextDocument.FindFlags()
        if self.viewer.find(needle, flags):
            self.find_status.clear()
            return

        # Wrap: restart from the far end rather than silently doing nothing at
        # the last match, which reads as "search is broken".
        cursor = self.viewer.textCursor()
        cursor.movePosition(QTextCursor.End if backwards else QTextCursor.Start)
        self.viewer.setTextCursor(cursor)
        if self.viewer.find(needle, flags):
            self.find_status.setText("wrapped")
        else:
            self.find_status.setText("not found")

    # ---- geometry ----

    def _restore_geometry(self) -> None:
        saved = settings.get(_GEOMETRY_KEY)
        if isinstance(saved, list) and len(saved) == 4:
            try:
                self.setGeometry(*(int(v) for v in saved))
            except (TypeError, ValueError):
                pass
        sizes = settings.get(_SPLITTER_KEY)
        if isinstance(sizes, list) and len(sizes) == 2:
            try:
                self.splitter.setSizes([int(v) for v in sizes])
            except (TypeError, ValueError):
                pass

    def closeEvent(self, event) -> None:
        rect = self.geometry()
        settings.update({
            _GEOMETRY_KEY: [rect.x(), rect.y(), rect.width(), rect.height()],
            _SPLITTER_KEY: list(self.splitter.sizes()),
        })
        super().closeEvent(event)
