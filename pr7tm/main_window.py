"""PR7-TM's window, the mock-up's: tabs of terminals (each tab a tree of split panes), the new-tab menu (this PC's
shells and the saved SSH sessions), the Sessions page, Quick connect, Find, Settings. Windows Terminal's keys:

    Ctrl+Shift+T new tab (the default profile)    Ctrl+Shift+1..9 open profile N    Ctrl+Shift+N quick connect
    Alt+Shift+D split (the same profile)          Alt+Shift+= / Alt+Shift+- split right / down
    Alt+arrow   move between panes                Ctrl+Shift+W close the pane       Ctrl+Tab / Ctrl+Shift+Tab tabs
    Ctrl+Shift+F find                             Ctrl+, sessions and settings      F11 full screen

SSH connects on a thread; its questions (host key, password, passphrase) come to the GUI through `Asker`. Every
question goes through `_ask(kind)` (tests: `answers`), every message through `_say`. `start_panes = False` lets
tests start backends themselves."""

from __future__ import annotations

import os
import queue
import sys
import threading

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QStackedWidget, QTabBar,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__, backends, colours, finish, profiles, sessions, settings, theme, widgets
from .termview import TermView

ID_ROLE = Qt.ItemDataRole.UserRole + 1


def _dim(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def _field(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


class Asker(QObject):
    """A backend's thread asks the GUI and waits for the answer."""
    asked = Signal(str, object, object)

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.asked.connect(self._answer, Qt.ConnectionType.QueuedConnection)

    def _answer(self, kind, payload, box):
        try:
            box.put(self.handler(kind, payload))
        except Exception:  # noqa: BLE001 - never leave the thread waiting
            box.put(None)

    def ask(self, kind, payload):
        if threading.current_thread() is threading.main_thread():
            return self.handler(kind, payload)
        box: queue.Queue = queue.Queue()
        self.asked.emit(kind, payload, box)
        return box.get()


class _Bridge(QObject):
    connected = Signal(object, object)          # TermView, error (None when connected)


# ==================================================================== a tab: a tree of split panes
class Tab(QWidget):
    def __init__(self, window: "MainWindow", first: TermView):
        super().__init__()
        self.window = window
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.root: QWidget = first
        self.lay.addWidget(first)
        self.current: TermView = first
        self.kind = "terminal"

    def panes(self) -> list[TermView]:
        return self.root.findChildren(TermView) if not isinstance(self.root, TermView) else [self.root]

    def split(self, new: TermView, orientation: Qt.Orientation):
        old = self.current
        parent = old.parentWidget()
        sp = QSplitter(orientation)
        sp.setHandleWidth(4)
        sp.setChildrenCollapsible(False)
        if isinstance(parent, QSplitter):
            idx = parent.indexOf(old)
            parent.insertWidget(idx, sp)
        else:
            self.lay.replaceWidget(old, sp)
            self.root = sp
        sp.addWidget(old)
        sp.addWidget(new)
        total = sp.width() if orientation == Qt.Orientation.Horizontal else sp.height()
        sp.setSizes([max(1, total // 2)] * 2)
        self.current = new
        new.setFocus()

    def remove(self, pane: TermView) -> bool:
        """Take a pane out; False when it was the last one (the tab closes)."""
        if pane is self.root:
            return False
        parent = pane.parentWidget()
        pane.setParent(None)
        pane.deleteLater()
        if isinstance(parent, QSplitter) and parent.count() == 1:
            survivor = parent.widget(0)
            grand = parent.parentWidget()
            if isinstance(grand, QSplitter):
                grand.insertWidget(grand.indexOf(parent), survivor)
            else:
                self.lay.replaceWidget(parent, survivor)
                self.root = survivor
            parent.setParent(None)
            parent.deleteLater()
        rest = self.panes()
        self.current = rest[0] if rest else None
        if self.current:
            self.current.setFocus()
        return True

    def neighbour(self, direction: str) -> TermView | None:
        """Alt+arrow: the pane whose centre is nearest in that direction."""
        cur = self.current
        c = cur.mapTo(self, cur.rect().center())
        best, best_d = None, None
        for p in self.panes():
            if p is cur:
                continue
            q = p.mapTo(self, p.rect().center())
            dx, dy = q.x() - c.x(), q.y() - c.y()
            ok = {"Left": dx < 0 and abs(dx) >= abs(dy) / 2, "Right": dx > 0 and abs(dx) >= abs(dy) / 2,
                  "Up": dy < 0 and abs(dy) >= abs(dx) / 2, "Down": dy > 0 and abs(dy) >= abs(dx) / 2}[direction]
            d = dx * dx + dy * dy
            if ok and (best_d is None or d < best_d):
                best, best_d = p, d
        return best


# ==================================================================== the Sessions page
class SessionsPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.kind = "sessions"
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 0)
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["SESSION", "HOST"])
        self.tree.setIconSize(QSize(18, 18))
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self.show_session())
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.open())
        left.addWidget(self.tree, 1)
        nb = QPushButton("NEW SESSION")
        nb.clicked.connect(self.new)
        left.addWidget(nb, 0, Qt.AlignmentFlag.AlignLeft)
        row.addLayout(left, 2)
        panel = QFrame()
        panel.setObjectName("card")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(20, 16, 20, 16)
        self.heading = QLabel("")
        self.heading.setProperty("role", "heading")
        pl.addWidget(self.heading)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        self.f_name, self.f_host, self.f_user, self.f_then = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_auth = QComboBox()
        for k, text in sessions.AUTH.items():
            self.f_auth.addItem(text, k)
        self.f_auth.currentIndexChanged.connect(lambda _i: self._auth_fields())
        keyrow = QHBoxLayout()
        self.f_key = QLineEdit()
        self.f_key.setPlaceholderText("C:\\Users\\you\\.ssh\\id_ed25519")
        browse = QPushButton("…")
        browse.clicked.connect(self._browse_key)
        keyrow.addWidget(self.f_key, 1)
        keyrow.addWidget(browse)
        self.key_row = QWidget()
        self.key_row.setLayout(keyrow)
        keyrow.setContentsMargins(0, 0, 0, 0)
        self.f_secret = QLineEdit()
        self.f_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_keep = QComboBox()
        for s, text in ((0, "Off"), (15, "Every 15 seconds"), (30, "Every 30 seconds"), (60, "Every minute")):
            self.f_keep.addItem(text, s)
        self.f_folder = QComboBox()
        self.f_folder.setEditable(True)
        self.secret_label = _field("Password")
        self.key_label = _field("Key file")
        for i, (label, w) in enumerate(((_field("Name"), self.f_name), (_field("Host"), self.f_host),
                                        (_field("Port"), self.f_port), (_field("User"), self.f_user),
                                        (_field("Sign in with"), self.f_auth), (self.key_label, self.key_row),
                                        (self.secret_label, self.f_secret), (_field("Keep alive"), self.f_keep),
                                        (_field("Then run"), self.f_then), (_field("Folder"), self.f_folder))):
            g.addWidget(label, i, 0)
            g.addWidget(w, i, 1)
        g.setColumnStretch(1, 1)
        pl.addLayout(g)
        h2 = QLabel("Port forwarding")
        h2.setProperty("role", "heading")
        pl.addWidget(h2)
        self.fw = QTreeWidget()
        self.fw.setHeaderLabels(["KIND", "HERE", "THERE"])
        self.fw.setRootIsDecorated(False)
        self.fw.setColumnWidth(0, 120)
        self.fw.setColumnWidth(1, 200)
        self.fw.setFixedHeight(110)
        pl.addWidget(self.fw)
        fr = QHBoxLayout()
        self.f_here = QLineEdit()
        self.f_here.setPlaceholderText("127.0.0.1:8000")
        self.f_there = QLineEdit()
        self.f_there.setPlaceholderText("localhost:8000")
        addf = QPushButton("ADD")
        addf.clicked.connect(self.add_forward)
        remf = QPushButton("REMOVE")
        remf.clicked.connect(lambda: [self.fw.takeTopLevelItem(self.fw.indexOfTopLevelItem(i))
                                      for i in self.fw.selectedItems()])
        for w in (self.f_here, self.f_there, addf, remf):
            fr.addWidget(w)
        pl.addLayout(fr)
        self.hostkey = _dim("")
        self.hostkey.setWordWrap(True)
        pl.addWidget(self.hostkey)
        pl.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        for text, slot, primary in (("DELETE", self.delete, False), ("SAVE", self.save, False),
                                    ("OPEN", self.open, True)):
            b = QPushButton(text)
            if primary:
                b.setProperty("kind", "primary")
            b.clicked.connect(lambda _=False, s=slot: s())
            btns.addWidget(b)
        pl.addLayout(btns)
        row.addWidget(panel, 3)
        self.current_id: str | None = None
        self.fill()

    def fill(self, select: str | None = None):
        self.tree.clear()
        folders: dict[str, QTreeWidgetItem] = {}
        chosen = None
        for s in sorted(self.window.sessions, key=lambda s: (s.folder.casefold(), s.name.casefold())):
            parent = None
            if s.folder:
                parent = folders.get(s.folder)
                if parent is None:
                    parent = folders[s.folder] = QTreeWidgetItem([s.folder, ""])
                    parent.setIcon(0, widgets.file_icon("folder", 18))
                    self.tree.addTopLevelItem(parent)
            it = QTreeWidgetItem([s.name, s.target()])
            it.setData(0, ID_ROLE, s.id)
            it.setIcon(0, widgets.line_icon("server", theme.LED_ORANGE, 18))
            (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
            if s.id == (select or self.current_id):
                chosen = it
        self.tree.expandAll()
        self.f_folder.clear()
        self.f_folder.addItems([""] + sorted({s.folder for s in self.window.sessions if s.folder}))
        if chosen:
            self.tree.setCurrentItem(chosen)
        elif self.window.sessions:
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first.child(0) if first.childCount() else first)
        else:
            self.new()

    def session(self) -> sessions.Session | None:
        return next((s for s in self.window.sessions if s.id == self.current_id), None)

    def show_session(self):
        it = self.tree.currentItem()
        sid = it.data(0, ID_ROLE) if it else None
        if not sid:
            return
        self.current_id = sid
        s = self.session()
        self.heading.setText(s.name)
        self.f_name.setText(s.name)
        self.f_host.setText(s.host)
        self.f_port.setValue(s.port or 22)
        self.f_user.setText(s.user)
        self.f_auth.setCurrentIndex(max(0, self.f_auth.findData(s.auth)))
        self.f_key.setText(s.key_file)
        self.f_secret.clear()
        self.f_secret.setPlaceholderText("(saved; leave empty to keep)" if sessions.secret(s.id) else "")
        self.f_keep.setCurrentIndex(max(0, self.f_keep.findData(s.keepalive)))
        self.f_then.setText(s.command)
        self.f_folder.setCurrentText(s.folder)
        self.fw.clear()
        for f in s.forwards:
            self.fw.addTopLevelItem(QTreeWidgetItem(["Local", f.here, f.there]))
        self.hostkey.setText(self.window.known_key_text(s))
        self._auth_fields()

    def _auth_fields(self):
        auth = self.f_auth.currentData()
        self.key_row.setVisible(auth == "key")
        self.key_label.setVisible(auth == "key")
        self.f_secret.setVisible(auth != "agent")
        self.secret_label.setVisible(auth != "agent")
        self.secret_label.setText("PASSPHRASE" if auth == "key" else "PASSWORD")

    def _browse_key(self):
        path = self.window._ask("key_file", os.path.join(os.path.expanduser("~"), ".ssh"))
        if path:
            self.f_key.setText(os.path.normpath(path))

    def add_forward(self):
        here, there = self.f_here.text().strip(), self.f_there.text().strip()
        if not here or not there:
            return
        if ":" not in here:
            here = f"127.0.0.1:{here}"
        self.fw.addTopLevelItem(QTreeWidgetItem(["Local", here, there]))
        self.f_here.clear()
        self.f_there.clear()

    def new(self):
        self.current_id = None
        self.heading.setText("New session")
        for e in (self.f_name, self.f_host, self.f_user, self.f_key, self.f_secret, self.f_then):
            e.clear()
        self.f_port.setValue(22)
        self.f_auth.setCurrentIndex(0)
        self.f_keep.setCurrentIndex(self.f_keep.findData(30))
        self.fw.clear()
        self.hostkey.setText("")
        self.f_name.setFocus()
        self._auth_fields()

    def form(self) -> sessions.Session | None:
        name, host = self.f_name.text().strip(), self.f_host.text().strip()
        if not host:
            self.window._say("warning", "Give the server's address.")
            return None
        s = self.session() if self.current_id else None
        new = sessions.Session(name or host, host, self.f_port.value(), self.f_user.text().strip(),
                               self.f_auth.currentData(), self.f_key.text().strip(), self.f_keep.currentData(),
                               self.f_then.text().strip(), self.f_folder.currentText().strip(),
                               [sessions.Forward("local", self.fw.topLevelItem(i).text(1),
                                                 self.fw.topLevelItem(i).text(2))
                                for i in range(self.fw.topLevelItemCount())])
        if s is not None:
            new.id = s.id
        return new

    def save(self) -> sessions.Session | None:
        s = self.form()
        if s is None:
            return None
        if self.f_secret.text():
            sessions.set_secret(s.id, self.f_secret.text())
        ws = self.window.sessions
        if any(x.id == s.id for x in ws):
            self.window.sessions = [s if x.id == s.id else x for x in ws]
        else:
            self.window.sessions.append(s)
        sessions.save(self.window.sessions)
        self.current_id = s.id
        self.fill(s.id)
        return s

    def delete(self) -> bool:
        s = self.session()
        if s is None or not self.window._ask("confirm", f"Delete the session \u201c{s.name}\u201d?"):
            return False
        sessions.set_secret(s.id, "")
        self.window.sessions = [x for x in self.window.sessions if x.id != s.id]
        sessions.save(self.window.sessions)
        self.current_id = None
        self.fill()
        return True

    def open(self):
        s = self.save()
        if s is not None:
            self.window.open_session(s)


# ==================================================================== the window
class MainWindow(QMainWindow):
    def __init__(self, profile_list: list | None = None, start_panes: bool = True):
        super().__init__()
        self.answers: dict = {}
        self.said: list = []
        self.start_panes = start_panes
        self.profiles = profile_list if profile_list is not None else profiles.find()
        self.sessions = sessions.load()
        self.asker = Asker(self._ask)
        self.bridge = _Bridge()
        self.bridge.connected.connect(self._connected)
        self.setWindowTitle("Paragon PR7-TM")
        self.resize(1320, 860)
        self._build()
        self._menus()
        self.restyle()

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("TERMINAL")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys: dict[str, widgets.KeyButton] = {}
        groups = [[("newtab", "newtab", "New tab", self.new_tab_menu), ("sessions", "server", "Sessions",
                                                                         self.show_sessions),
                   ("split", "sidebar", "Split", lambda: self.split(Qt.Orientation.Horizontal))],
                  [("copy", "copy", "Copy", self.copy), ("paste", "open", "Paste", self.paste),
                   ("find", "search", "Find", self.show_find)],
                  [("settings", "gear", "Settings", self.options)]]
        for i, group in enumerate(groups):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for key, icon, label, slot in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                k.clicked.connect(lambda _=False, s=slot: s())
                bl.addWidget(k)
                self.keys[key] = k
        bl.addStretch(1)
        self.toolbar = bar
        lay.addWidget(bar)
        tabrow = QWidget()
        tl = QHBoxLayout(tabrow)
        tl.setContentsMargins(16, 0, 16, 0)
        tl.setSpacing(4)
        self.tabbar = QTabBar()
        self.tabbar.setTabsClosable(False)       # our own "×" per tab (Qt's close button ignores the family style)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setIconSize(QSize(16, 16))
        self.tabbar.currentChanged.connect(self._tab_changed)
        self.tabbar.tabMoved.connect(self._tab_moved)
        tl.addWidget(self.tabbar)
        plus = QPushButton("+")
        plus.setObjectName("plus")
        plus.setToolTip("New tab (Ctrl+Shift+T)")
        plus.clicked.connect(lambda: self.new_tab())
        drop = QPushButton("⌄")
        drop.setObjectName("plus")
        drop.setToolTip("Choose what to open")
        drop.clicked.connect(self.new_tab_menu)
        tl.addWidget(plus)
        tl.addWidget(drop)
        tl.addStretch(1)
        self.drop = drop
        lay.addWidget(tabrow)
        self.findbar = QFrame()
        self.findbar.setObjectName("findbar")
        fl = QHBoxLayout(self.findbar)
        fl.setContentsMargins(16, 4, 16, 4)
        fl.addWidget(_field("Find"))
        self.find_edit = QLineEdit()
        self.find_edit.setFixedWidth(320)
        self.find_edit.textChanged.connect(lambda _t: self.find(0))
        self.find_edit.returnPressed.connect(lambda: self.find(1))
        fl.addWidget(self.find_edit)
        for text, step in (("↑", -1), ("↓", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=step: self.find(s))
            fl.addWidget(b)
        self.find_count = _dim("")
        fl.addWidget(self.find_count)
        fl.addStretch(1)
        x = QPushButton("×")
        x.clicked.connect(self.hide_find)
        fl.addWidget(x)
        self.findbar.hide()
        lay.addWidget(self.findbar)
        self.stack = QStackedWidget()
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 0, 16, 8)
        wl.addWidget(self.stack)
        lay.addWidget(wrap, 1)
        foot = QFrame()
        foot.setObjectName("foot")
        fo = QHBoxLayout(foot)
        fo.setContentsMargins(16, 6, 16, 6)
        self.status = _dim("")
        fo.addWidget(self.status, 1)
        self.hint = _dim("Alt+Shift+D splits  ·  Ctrl+Shift+T new tab  ·  right click copies or pastes")
        fo.addWidget(self.hint)
        lay.addWidget(foot)
        self.find_pos = -1

    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "New Tab", lambda: self.new_tab(), "Ctrl+Shift+T", "newtab")
        self._act(m, "Quick Connect…", self.quick_connect, "Ctrl+Shift+N", "quick")
        for i in range(9):
            self._act(m, f"Profile {i + 1}", lambda i=i: self.new_tab(i), f"Ctrl+Shift+{i + 1}", f"profile{i}") \
                .setVisible(False)
        m.addSeparator()
        self._act(m, "Close Pane", self.close_pane, "Ctrl+Shift+W", "closepane")
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&Edit")
        self._act(m, "Copy", self.copy, "Ctrl+Shift+C", "copy")
        self._act(m, "Paste", self.paste, "Ctrl+Shift+V", "paste")
        self._act(m, "Select All", lambda: self.pane() and self.pane().select_all(), "Ctrl+Shift+A", "selectall")
        self._act(m, "Find…", self.show_find, "Ctrl+Shift+F", "find")
        m = mb.addMenu("&View")
        self._act(m, "Split Pane", lambda: self.split(None), "Alt+Shift+D", "split")
        self._act(m, "Split Right", lambda: self.split(Qt.Orientation.Horizontal), "Alt+Shift+=", "splitright")
        self._act(m, "Split Down", lambda: self.split(Qt.Orientation.Vertical), "Alt+Shift+-", "splitdown")
        for d in ("Left", "Right", "Up", "Down"):
            self._act(m, f"Pane {d}", lambda d=d: self.move_focus(d), f"Alt+{d}", f"pane{d}").setVisible(False)
        self._act(m, "Next Tab", lambda: self.step_tab(1), "Ctrl+Tab", "nexttab")
        self._act(m, "Previous Tab", lambda: self.step_tab(-1), "Ctrl+Shift+Tab", "prevtab")
        m.addSeparator()
        self._act(m, "Full Screen", self.toggle_full_screen, "F11", "full")
        fm = m.addMenu("Finish")
        self.finish_acts = {}
        fg = QActionGroup(self)
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            fg.addAction(a)
            self.finish_acts[name] = a
        m = mb.addMenu("&Tools")
        self._act(m, "Sessions", self.show_sessions, "Ctrl+,", "sessions")
        self._act(m, "Settings…", self.options, None, "settings")
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-TM", lambda: self._say("info", f"Paragon PR7-TM {__version__}\nA terminal, the way "
                                                               "Windows Terminal and PuTTY work."))

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central {{ background: {theme.BACKGROUND}; }} QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QFrame#findbar {{ background: {theme.TAB_FRAME}; }} "
            f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 8px; }} "
            f"QPushButton[kind=\"primary\"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; "
            f"font-weight: 600; padding: 7px 22px; }} "
            f"QPushButton#plus {{ background: transparent; color: {theme.TEXT}; border: none; padding: 6px 10px; "
            f"font-size: 15px; }} "
            f"QTabBar::tab {{ background: {theme.BUTTON}; color: {theme.TEXT_DIM}; border: none; padding: 8px 14px; "
            f"margin-right: 4px; border-top-left-radius: 8px; border-top-right-radius: 8px; min-width: 120px; }} "
            f"QTabBar::tab:selected {{ background: {colours.BACKGROUND}; color: #FFFFFF; "
            f"border-top: 2px solid {theme.ACCENT}; }} "
            f"QSplitter::handle {{ background: {theme.PANEL_EDGE}; }} "
            f"QPushButton#tabclose {{ background: transparent; color: {theme.TEXT_DIM}; border: none; padding: 0; "
            f"font-size: 14px; }} QPushButton#tabclose:hover {{ color: #FFFFFF; background: {theme.ACCENT_DIM}; "
            f"border-radius: 4px; }} "
            f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; }} "
            f"QTreeView::branch:selected {{ background: transparent; }} "
            f"QTreeView {{ selection-background-color: transparent; }}")
        self.header.update()
        for name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(name == theme.FINISH)

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)
        settings.set("finish", theme.FINISH)
        self.restyle()

    # ================================================================ tabs
    def tabs(self) -> list[QWidget]:
        return [self.stack.widget(i) for i in range(self.stack.count())]

    def tab(self) -> QWidget | None:
        return self.stack.currentWidget()

    def pane(self) -> TermView | None:
        t = self.tab()
        return t.current if isinstance(t, Tab) else None

    def _add_tab(self, widget: QWidget, title: str, icon: str):
        self.stack.addWidget(widget)
        i = self.tabbar.addTab(widgets.line_icon(icon, theme.LED_ORANGE, 16), title)
        x = QPushButton("×")
        x.setObjectName("tabclose")
        x.setFixedSize(20, 20)
        x.setToolTip("Close tab (Ctrl+Shift+W closes the pane)")
        x.clicked.connect(lambda _=False, w=widget: self.close_tab(self.stack.indexOf(w)))
        self.tabbar.setTabButton(i, QTabBar.ButtonPosition.RightSide, x)
        self.tabbar.setCurrentIndex(i)
        self.stack.setCurrentIndex(i)
        return i

    def _tab_changed(self, i: int):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
            p = self.pane()
            if p is not None:
                p.setFocus()
        self._sync()

    def _tab_moved(self, a: int, b: int):
        w = self.stack.widget(a)
        self.stack.removeWidget(w)
        self.stack.insertWidget(b, w)
        self.stack.setCurrentIndex(self.tabbar.currentIndex())

    def step_tab(self, n: int):
        if self.tabbar.count():
            self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + n) % self.tabbar.count())

    def _make_pane(self, backend, title: str) -> TermView:
        v = TermView(backend, title, settings.get_int("font_size", 11), settings.get_int("scrollback", 10000))
        v.title_changed.connect(lambda t, v=v: self._pane_title(v, t))
        v.closed.connect(lambda v=v: self.close_pane(v))
        v.restart.connect(lambda v=v: self.restart_pane(v))
        v.focused.connect(lambda v=v: self._pane_focused(v))
        v.resized.connect(lambda c, r: self._sync())
        v.spec = None
        return v

    def _pane_focused(self, v: TermView):
        for t in self.tabs():
            if isinstance(t, Tab) and v in t.panes():
                t.current = v
        self._sync()

    def _pane_title(self, v: TermView, title: str):
        for i, t in enumerate(self.tabs()):
            if isinstance(t, Tab) and t.current is v:
                self.tabbar.setTabText(i, title[:40])
        self._sync()

    def _start(self, v: TermView):
        if self.start_panes:
            QTimer.singleShot(0, lambda: self._start_now(v))

    def _start_now(self, v: TermView):
        try:
            v.start()
        except Exception as e:  # noqa: BLE001 - shown in the pane
            v.term.feed(f"\x1b[91mCouldn't start it: {e}\x1b[0m\r\n".encode())
            v.ended = str(e)
            v.update()

    def profile_backend(self, p: profiles.Profile):
        return backends.LocalBackend(p.argv, p.cwd or None)

    def new_tab(self, index: int | None = None) -> TermView | None:
        """A tab with a profile (the default one when no index is given)."""
        if not self.profiles:
            return None
        if index is None:
            name = settings.get("default_profile", "")
            index = next((i for i, p in enumerate(self.profiles) if p.name == name and not p.admin), 0)
        if index >= len(self.profiles):
            return None
        p = self.profiles[index]
        if p.admin:
            self.run_as_admin(p)
            return None
        v = self._make_pane(self.profile_backend(p), p.name)
        v.spec = ("profile", index)
        self._add_tab(Tab(self, v), p.name, p.icon)
        self._start(v)
        v.setFocus()
        return v

    def open_session(self, s: sessions.Session, split: Qt.Orientation | None = None) -> TermView:
        """An SSH session in a new tab (or a split): connecting happens on a thread, questions come here."""
        v = self._make_pane(backends.SSHBackend(s, ask=self.asker.ask), s.target())
        v.spec = ("session", s.id)
        if split is not None and isinstance(self.tab(), Tab):
            self.tab().split(v, split)
        else:
            self._add_tab(Tab(self, v), s.target(), "server")
        v.term.feed(f"\x1b[90mConnecting to {s.target()}…\x1b[0m\r\n".encode())
        self._connect(v)
        return v

    def _connect(self, v: TermView):
        if not self.start_panes:
            return

        def work():
            try:
                v.backend.connect()
                self.bridge.connected.emit(v, None)
            except Exception as e:  # noqa: BLE001 - shown in the pane
                self.bridge.connected.emit(v, e)
        threading.Thread(target=work, daemon=True).start()

    def _connected(self, v: TermView, error):
        if error is not None:
            v.term.feed(f"\x1b[91m{error}\x1b[0m\r\n".encode())
            v.ended = str(error)
            v.term.feed(b"\x1b[90m[Enter closes this pane, R tries again.]\x1b[0m\r\n")
            v.update()
            return
        self._start_now(v)

    def restart_pane(self, v: TermView):
        """R after the program ended: the same profile / session again in the same place."""
        spec = getattr(v, "spec", None)
        if spec is None:
            return
        if spec[0] == "profile":
            backend = self.profile_backend(self.profiles[spec[1]])
            title = self.profiles[spec[1]].name
        else:
            s = next((x for x in self.sessions if x.id == spec[1]), None) or getattr(v.backend, "session", None)
            backend = backends.SSHBackend(s, ask=self.asker.ask)
            title = s.target()
        new = self._make_pane(backend, title)
        new.spec = spec
        for t in self.tabs():
            if isinstance(t, Tab) and v in t.panes():
                parent = v.parentWidget()
                if isinstance(parent, QSplitter):
                    parent.replaceWidget(parent.indexOf(v), new)
                else:
                    t.lay.replaceWidget(v, new)
                    t.root = new
                t.current = new
        v.close_backend()
        v.setParent(None)
        v.deleteLater()
        if spec[0] == "profile":
            self._start(new)
        else:
            new.term.feed(f"\x1b[90mConnecting to {title}…\x1b[0m\r\n".encode())
            self._connect(new)
        new.setFocus()

    def split(self, orientation: Qt.Orientation | None):
        """Alt+Shift+D: the same profile / session beside (wider panes split side by side, else one above)."""
        t = self.tab()
        if not isinstance(t, Tab) or t.current is None:
            return None
        cur = t.current
        if orientation is None:
            orientation = Qt.Orientation.Horizontal if cur.width() >= cur.height() * 1.6 else Qt.Orientation.Vertical
        spec = getattr(cur, "spec", None) or ("profile", 0)
        if spec[0] == "session":
            s = next((x for x in self.sessions if x.id == spec[1]), None) or getattr(cur.backend, "session", None)
            return self.open_session(s, split=orientation)
        p = self.profiles[spec[1]]
        v = self._make_pane(self.profile_backend(p), p.name)
        v.spec = spec
        t.split(v, orientation)
        self._start(v)
        return v

    def move_focus(self, direction: str):
        t = self.tab()
        if isinstance(t, Tab):
            n = t.neighbour(direction)
            if n is not None:
                t.current = n
                n.setFocus()

    def close_pane(self, v: TermView | None = None):
        v = v or self.pane()
        if v is None:
            t = self.tab()
            if t is not None:
                self.close_tab(self.stack.indexOf(t))
            return
        for i, t in enumerate(self.tabs()):
            if isinstance(t, Tab) and v in t.panes():
                v.close_backend()
                if not t.remove(v):
                    self.close_tab(i)
                self._sync()
                return

    def close_tab(self, i: int):
        w = self.stack.widget(i)
        if w is None:
            return
        if isinstance(w, Tab):
            running = [p for p in w.panes() if p.backend.alive]
            if len(running) > 1 and not self._ask("confirm", f"Close this tab and its {len(running)} panes?"):
                return
            for p in w.panes():
                p.close_backend()
        self.tabbar.removeTab(i)
        self.stack.removeWidget(w)
        w.deleteLater()
        if not self.stack.count():
            if self._ask("last_tab_closed", None) is not False:
                self.close()
        self._sync()

    # ================================================================ the new-tab menu
    def new_tab_menu(self) -> QMenu:
        m = QMenu(self)
        sec = m.addSection("THIS PC")
        sec.setEnabled(False)
        for i, p in enumerate(self.profiles):
            a = m.addAction(widgets.line_icon(p.icon, theme.LED_ORANGE, 16), p.name, lambda i=i: self.new_tab(i))
            if i < 9 and not p.admin:
                a.setShortcut(QKeySequence(f"Ctrl+Shift+{i + 1}"))
        if self.sessions:
            m.addSection("SAVED SESSIONS")
            for s in sorted(self.sessions, key=lambda s: (s.folder.casefold(), s.name.casefold())):
                m.addAction(widgets.line_icon("server", theme.LED_ORANGE, 16), f"{s.name}  ·  {s.target()}",
                            lambda s=s: self.open_session(s))
        m.addSeparator()
        m.addAction(widgets.line_icon("search", theme.LED_ORANGE, 16), "Quick connect…", self.quick_connect) \
            .setShortcut(QKeySequence("Ctrl+Shift+N"))
        m.addAction(widgets.line_icon("gear", theme.LED_ORANGE, 16), "Sessions and settings", self.show_sessions) \
            .setShortcut(QKeySequence("Ctrl+,"))
        self.last_menu = m
        if "menu" not in self.answers:
            m.exec(self.drop.mapToGlobal(self.drop.rect().bottomLeft()))
        return m

    def quick_connect(self):
        text = self._ask("text", "Connect to (user@host or user@host:port):")
        if not text:
            return None
        got = sessions.parse_target(text)
        if got is None:
            self._say("warning", f"\u201c{text}\u201d isn't an address PR7-TM understands (try user@host:port).")
            return None
        user, host, port = got
        s = next((x for x in self.sessions if x.host == host and (x.user == user or not user) and x.port == port), None)
        if s is None:
            s = sessions.Session(f"{user + '@' if user else ''}{host}", host, port, user, auth="password")
        return self.open_session(s)

    def show_sessions(self) -> "SessionsPage":
        for i, t in enumerate(self.tabs()):
            if isinstance(t, SessionsPage):
                self.tabbar.setCurrentIndex(i)
                return t
        page = SessionsPage(self)
        self._add_tab(page, "Sessions", "gear")
        return page

    def known_key_text(self, s: sessions.Session) -> str:
        import paramiko
        path = sessions.known_hosts()
        if not os.path.exists(path):
            return "Host key: not seen yet (asked the first time you connect)"
        hk = paramiko.HostKeys()
        try:
            hk.load(path)
        except (OSError, paramiko.SSHException):
            return ""
        name = s.host if (s.port or 22) == 22 else f"[{s.host}]:{s.port}"
        known = hk.lookup(name)
        if not known:
            return "Host key: not seen yet (asked the first time you connect)"
        import base64
        import hashlib
        kind, key = next(iter(known.items()))
        fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        return f"Known host key  ·  {kind}  SHA256:{fp}"

    def run_as_admin(self, p: profiles.Profile) -> bool:
        """ConPTY can't run an elevated shell inside a window that isn't (Windows Terminal can't either): a new
        PR7-TM window as administrator, with that profile."""
        if "elevate" in self.answers:
            return self.answers["elevate"](p)
        if sys.platform != "win32":
            return False
        import ctypes
        import subprocess
        exe, pre = (sys.executable, []) if getattr(sys, "frozen", False) else (sys.executable, ["-m", "pr7tm"])
        name = p.name.replace(" as administrator", "")
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(pre + ["--profile", name]),
                                                None, 1)
        return r > 32

    # ================================================================ copy, paste, find
    def copy(self):
        p = self.pane()
        if p is not None and p.copy():
            self.status.setText("Copied.")

    def paste(self):
        p = self.pane()
        if p is not None:
            p.paste()
            p.setFocus()

    def show_find(self):
        self.findbar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def hide_find(self):
        self.findbar.hide()
        p = self.pane()
        if p is not None:
            p.hits = []
            p.update()
            p.setFocus()

    def find(self, step: int):
        p = self.pane()
        if p is None:
            return 0
        word = self.find_edit.text()
        p.hits = p.term.find(word)
        p.hit_len = len(word)
        if not p.hits:
            self.find_count.setText("No matches" if word else "")
            p.update()
            return 0
        self.find_pos = (self.find_pos + step) % len(p.hits) if step else len(p.hits) - 1
        r, _c = p.hits[self.find_pos]
        total = len(p.term.all_rows())
        p.offset = max(0, min(p.term.scrollback, total - r - p.term.lines // 2))     # bring it into view
        p._update_bar()
        p.update()
        self.find_count.setText(f"{self.find_pos + 1} of {len(p.hits)}")
        return len(p.hits)

    # ================================================================ settings
    def options(self) -> bool:
        if "options" in self.answers:
            ok = self._ask("options")
        else:
            d = QDialog(self)
            d.setWindowTitle("Settings")
            form = QFormLayout()
            prof = QComboBox()
            for p in self.profiles:
                if not p.admin:
                    prof.addItem(p.name)
            prof.setCurrentText(settings.get("default_profile", self.profiles[0].name if self.profiles else ""))
            size = QSpinBox()
            size.setRange(6, 36)
            size.setValue(settings.get_int("font_size", 11))
            back = QSpinBox()
            back.setRange(1000, 100000)
            back.setSingleStep(1000)
            back.setValue(settings.get_int("scrollback", 10000))
            fin = QComboBox()
            fin.addItem("OBSIDIAN", "obsidian")
            fin.addItem("AURORA", "aurora")
            fin.setCurrentIndex(0 if theme.FINISH == "obsidian" else 1)
            for label, w in (("Default profile", prof), ("Font size", size), ("Scrollback lines", back),
                             ("Finish", fin)):
                form.addRow(_field(label), w)
            v = QVBoxLayout(d)
            v.addLayout(form)
            v.addWidget(_dim("The terminal stays dark in both finishes, as keys and menus do."))
            b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            b.accepted.connect(d.accept)
            b.rejected.connect(d.reject)
            v.addWidget(b)
            ok = bool(d.exec())
            if ok:
                settings.set("default_profile", prof.currentText())
                settings.set("font_size", size.value())
                settings.set("scrollback", back.value())
                if fin.currentData() != theme.FINISH:
                    self.set_finish(fin.currentData())
        if ok:
            for t in self.tabs():
                if isinstance(t, Tab):
                    for p in t.panes():
                        p.set_font_size(settings.get_int("font_size", 11))
        return bool(ok)

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    def toggle_full_screen(self):
        full = not self.isFullScreen()
        for w in (self.header, self.toolbar, self.menuBar()):
            w.setVisible(not full)
        self.showFullScreen() if full else self.showNormal()

    # ================================================================ status
    def _sync(self):
        t = self.tab()
        if isinstance(t, Tab) and t.current is not None:
            p = t.current
            what = p.term.title or p.base_title
            self.status.setText(f"{what}  ·  {p.term.cols} × {p.term.lines}" + ("  ·  ended" if p.ended else ""))
            self.setWindowTitle(f"{what}  ·  Paragon PR7-TM")
        elif isinstance(t, SessionsPage):
            self.status.setText(f"SESSIONS  ·  {len(self.sessions)} saved")
            self.setWindowTitle("Sessions  ·  Paragon PR7-TM")
        else:
            self.status.setText("")

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            a = self.answers[kind]
            return a(payload) if callable(a) else a
        if kind == "hostkey":
            host, keytype, fp = payload
            box = QMessageBox(QMessageBox.Icon.Question, "PR7-TM", f"The first connection to {host}", parent=self)
            box.setInformativeText(f"Its key is {keytype}\n{fp}\n\nIf you expected this server, PR7-TM remembers the key "
                                   "and warns you if it ever changes.")
            ok = box.addButton("CONNECT", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return box.clickedButton() is ok
        if kind in ("password", "passphrase"):
            s = payload
            label = (f"Password for {s.target()}:" if kind == "password" else
                     f"Passphrase for the key {os.path.basename(s.key_file)}:")
            text, ok = QInputDialog.getText(self, "PR7-TM", label, QLineEdit.EchoMode.Password)
            if not ok:
                return None
            if text and s.id in {x.id for x in self.sessions} and \
                    QMessageBox.question(self, "PR7-TM", "Remember it in Windows' Credential Manager?") == \
                    QMessageBox.StandardButton.Yes:
                sessions.set_secret(s.id, text)
            return text
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-TM", payload) == QMessageBox.StandardButton.Yes
        if kind == "text":
            text, ok = QInputDialog.getText(self, "Quick connect", payload)
            return text if ok else None
        if kind == "key_file":
            return QFileDialog.getOpenFileName(self, "Key file", payload)[0]
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind in ("error", "warning") else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-TM", text, parent=self).exec()

    def closeEvent(self, e):
        running = sum(1 for t in self.tabs() if isinstance(t, Tab) for p in t.panes() if p.backend.alive)
        if running > 1 and not self._ask("confirm", f"Close PR7-TM and its {running} running sessions?"):
            e.ignore()
            return
        for t in self.tabs():
            if isinstance(t, Tab):
                for p in t.panes():
                    p.close_backend()
        super().closeEvent(e)
