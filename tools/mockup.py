"""Mock-up pictures of PR7-TM, drawn offscreen in the family theme (the sessions are made up):
QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_tabs.png       Tabs and a split: PowerShell on the left, an SSH session to the NAS on the right (OBSIDIAN)
2_sessions.png   Saved sessions (PuTTY's): host, user, key or password, port forwarding, startup command (AURORA)
3_newtab.png     The new-tab menu: local shells and saved SSH sessions in one list, Quick connect (OBSIDIAN)
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,  # noqa: E402
                               QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7tm import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def toolbar():
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    groups = [[("newtab", "New tab"), ("server", "Sessions"), ("sidebar", "Split")],
              [("copy", "Copy"), ("open", "Paste"), ("search", "Find")], [("gear", "Settings")]]
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    return bar


def status(left, right):
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(16, 6, 16, 6)
    lay.addWidget(dim(left))
    lay.addStretch(1)
    lay.addWidget(dim(right))
    return f


def window(body, status_bar):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("TERMINAL"))
    lay.addWidget(toolbar())
    wrap = QWidget()
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(16, 6, 16, 8)
    wl.addWidget(body)
    lay.addWidget(wrap, 1)
    lay.addWidget(status_bar)
    w.resize(1320, 860)
    return w


def card(title, rows, extra=None):
    f = QFrame()
    f.setObjectName("card")
    f.setStyleSheet(f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                    f"border-radius: 8px; }}")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 10, 14, 12)
    v.setSpacing(6)
    h = QLabel(title)
    h.setProperty("role", "heading")
    v.addWidget(h)
    g = QGridLayout()
    g.setHorizontalSpacing(14)
    g.setVerticalSpacing(4)
    for i, (k, val) in enumerate(rows):
        g.addWidget(field(k), i, 0, Qt.AlignmentFlag.AlignTop)
        lab = QLabel(val)
        lab.setWordWrap(True)
        g.addWidget(lab, i, 1)
    g.setColumnStretch(1, 1)
    v.addLayout(g)
    if extra is not None:
        v.addWidget(extra)
    v.addStretch(1)
    return f


def chips(names, on):
    w = QWidget()
    lay = QGridLayout(w)
    lay.setContentsMargins(0, 6, 0, 0)
    lay.setSpacing(4)
    for i, n in enumerate(names):
        lab = QLabel(n)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lit = n in on
        lab.setStyleSheet(f"QLabel {{ background: {theme.qss_gradient() if lit else theme.BUTTON}; color: "
                          f"{'#FFFFFF' if lit else theme.TEXT_DIM}; border-radius: 4px; padding: 3px 6px; "
                          f"font-size: 10.5px; font-weight: 600; }}")
        lay.addWidget(lab, i // 7, i % 7)
    return w


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


MONO = QFont("Cascadia Mono")
MONO.setStyleHint(QFont.StyleHint.Monospace)
MONO.setFamilies(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
MONO.setPixelSize(14)
# the 16 terminal colours in the family's hues only (Windows Terminal's green / blue / cyan / purple become pearl,
# pink, peach and the family red)
ANSI = {"fg": "#E4DFE2", "dim": "#8A8A92", "red": "#F4353A", "pearl": "#F2ECE4", "orange": "#FF7A1A",
        "pink": "#F06292", "rose": "#DE0639", "peach": "#F4B49A", "white": "#FFFFFF", "bg": "#0B090C"}


class Term(QWidget):
    """A terminal pane: rows of (text, colour, bold) painted on a grid, a block cursor."""

    def __init__(self, rows, cursor=None, title="", active=True):
        super().__init__()
        self.rows, self.cursor, self.title, self.active = rows, cursor, title, active

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(ANSI["bg"]))
        p.setFont(MONO)
        fm = p.fontMetrics()
        cw, lh = fm.horizontalAdvance("M"), fm.height() + 3
        y = 14 + fm.ascent()
        for row in self.rows:
            x = 14
            for text, col, bold in row:
                f = QFont(MONO)
                f.setBold(bold)
                p.setFont(f)
                p.setPen(QColor(ANSI.get(col, col)))
                p.drawText(x, y, text)
                x += p.fontMetrics().horizontalAdvance(text)
            y += lh
        if self.cursor:
            _cx, cy = self.cursor               # the cursor sits after the last row's text
            last = self.rows[cy] if cy < len(self.rows) else []
            x = 14 + sum(QFontMetricsWidth(MONO, t) for t, _c, _b in last)
            r = QRectF(x, 14 + cy * lh, cw, lh - 2)
            if self.active:
                p.fillRect(r, QColor(ANSI["orange"]))
            else:
                p.setPen(QPen(QColor(ANSI["orange"]), 1))
                p.drawRect(r)
        if not self.active:
            p.fillRect(self.rect(), QColor(0, 0, 0, 70))


def QFontMetricsWidth(font, text):
    from PySide6.QtGui import QFontMetrics
    return QFontMetrics(font).horizontalAdvance(text)


def seg(*parts):
    """("text", colour[, bold]) ... -> a row."""
    return [(t[0], t[1], len(t) > 2 and t[2]) for t in parts]


def tabs(names, current, finish_dark=True):
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 0, 16, 0)
    lay.setSpacing(4)
    for i, (icon, name) in enumerate(names):
        b = QPushButton(f"  {name}    ×")
        b.setIcon(widgets.line_icon(icon, theme.LED_ORANGE, 16))
        on = i == current
        b.setStyleSheet(f"QPushButton {{ background: {ANSI['bg'] if on else theme.BUTTON}; color: "
                        f"{'#FFFFFF' if on else theme.TEXT_DIM}; border: none; border-top-left-radius: 8px; "
                        f"border-top-right-radius: 8px; padding: 8px 14px; text-align: left; "
                        f"{'border-top: 2px solid ' + theme.ACCENT + ';' if on else ''} }}")
        lay.addWidget(b)
    plus = QPushButton("+  ⌄")
    plus.setStyleSheet(f"QPushButton {{ background: transparent; color: {theme.TEXT}; border: none; padding: 8px; }}")
    lay.addWidget(plus)
    lay.addStretch(1)
    return bar


def term_window(tab_names, current, body, status_bar):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("TERMINAL"))
    lay.addWidget(toolbar())
    lay.addWidget(tabs(tab_names, current))
    wrap = QWidget()
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(16, 0, 16, 8)
    wl.addWidget(body)
    lay.addWidget(wrap, 1)
    lay.addWidget(status_bar)
    w.resize(1320, 860)
    return w


PS = [seg(("PowerShell 7.5.4", "fg")),
      seg(("PS ", "pink"), ("D:\\Studio\\Projects", "orange"), ("> ", "pink"), ("git status -sb", "fg")),
      seg(("## main...origin/main ", "pearl"), ("[ahead 2]", "red")),
      seg((" M ", "red"), ("titles/elseworld_titles_v6.blend", "fg")),
      seg(("?? ", "rose"), ("titles/titles_notes.txt", "fg")),
      seg(("PS ", "pink"), ("D:\\Studio\\Projects", "orange"), ("> ", "pink"), ("Get-ChildItem renders | Select -Last 4",
                                                                            "fg")),
      [],
      seg(("    Directory: D:\\Studio\\Projects\\renders", "pearl")),
      [],
      seg(("Mode     LastWriteTime        Length Name", "peach", True)),
      seg(("----     -------------        ------ ----", "peach")),
      seg(("-a---    26/11/2026  00:41  48213337 ", "fg"), ("titles_v6_0001-0240.mp4", "orange")),
      seg(("-a---    26/11/2026  00:58  51004122 ", "fg"), ("titles_v6_0241-0480.mp4", "orange")),
      seg(("-a---    26/11/2026  01:02     40960 ", "fg"), ("render.log", "fg")),
      seg(("d----    25/11/2026  22:10           ", "fg"), ("frames", "pink", True)),
      [],
      seg(("PS ", "pink"), ("D:\\Studio\\Projects", "orange"), ("> ", "pink"))]
NAS = [seg(("Linux nas 6.8.0-49-generic x86_64", "dim")),
       seg(("Last login: Wed Nov 25 21:14:07 2026 from 192.168.1.20", "dim")),
       seg(("ari@nas", "orange", True), (":", "fg"), ("~", "pink", True), ("$ ", "fg"), ("df -h /srv/backups", "fg")),
       seg(("Filesystem      Size  Used Avail Use% Mounted on", "peach", True)),
       seg(("/dev/md0         15T  8.2T  6.8T  55% /srv/backups", "fg")),
       seg(("ari@nas", "orange", True), (":", "fg"), ("~", "pink", True), ("$ ", "fg"),
           ("systemctl status restic-rest", "fg")),
       seg(("● ", "orange"), ("restic-rest.service - restic REST server", "fg", True)),
       seg(("     Loaded: loaded (/etc/systemd/system/restic-rest.service)", "fg")),
       seg(("     Active: ", "fg"), ("active (running)", "pearl", True), (" since Mon 2026-11-23", "fg")),
       seg(("   Main PID: 1182 (rest-server)", "fg")),
       seg(("     Memory: 24.1M", "fg")),
       seg(("ari@nas", "orange", True), (":", "fg"), ("~", "pink", True), ("$ ", "fg"))]

# ------------------------------------------------------------------ 1: tabs and a split
theme.set_finish("obsidian")
style()
split = QSplitter()
split.setHandleWidth(4)
split.addWidget(Term(PS, (21, 16)))
split.addWidget(Term(NAS, (10, 11), active=False))
split.setSizes([700, 580])
shoot(term_window([("app", "PowerShell"), ("server", "ari@nas.local"), ("app", "Command Prompt")], 0, split,
                  status("PowerShell  ·  D:\\Studio\\Projects  ·  120 × 34", "Ctrl+Shift+D splits  ·  "
                         "Ctrl+Shift+T new tab  ·  right click pastes")), "1_tabs.png")

# ------------------------------------------------------------------ 2: saved sessions
theme.set_finish("aurora")
style()
body = QWidget()
row = QHBoxLayout(body)
row.setContentsMargins(0, 8, 0, 0)
tree = QTreeWidget()
tree.setHeaderLabels(["SESSION", "HOST"])
tree.setIconSize(QSize(18, 18))
for folder, kids in (("Home", [("NAS", "ari@nas.local"), ("Pi-hole", "pi@192.168.1.2")]),
                     ("Studio", [("Render node", "render@studio-render:2222"), ("Studio Pi", "ari@studio-pi")]),
                     ("Cloud", [("VPS", "root@vps.example.net"), ("Backups (B2 gateway)", "ari@b2gw.example.net")])):
    f = QTreeWidgetItem([folder, ""])
    f.setIcon(0, widgets.file_icon("folder", 18))
    tree.addTopLevelItem(f)
    for name, host in kids:
        it = QTreeWidgetItem([name, host])
        it.setIcon(0, widgets.line_icon("server", theme.LED_ORANGE, 18))
        f.addChild(it)
        if name == "NAS":
            tree.setCurrentItem(it)
tree.expandAll()
tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
row.addWidget(tree, 2)
panel = QFrame()
panel.setObjectName("card")
panel.setStyleSheet(f"QFrame#card {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                    f"border-radius: 8px; }}")
pl = QVBoxLayout(panel)
pl.setContentsMargins(20, 16, 20, 16)
h = QLabel("NAS")
h.setProperty("role", "heading")
pl.addWidget(h)
g = QGridLayout()
g.setHorizontalSpacing(14)
g.setVerticalSpacing(8)
fields = [("Host", QLineEdit("nas.local")), ("Port", QLineEdit("22")), ("User", QLineEdit("ari"))]
auth = QComboBox()
auth.addItem("Key file  ·  C:\\Users\\Ari\\.ssh\\id_ed25519")
fields.append(("Sign in with", auth))
kp = QComboBox()
kp.addItem("Every 30 seconds")
fields.append(("Keep alive", kp))
fields.append(("Then run", QLineEdit("tmux new -A -s main")))
fields.append(("Folder", QComboBox()))
fields[-1][1].addItem("Home")
for i, (k, wdg) in enumerate(fields):
    g.addWidget(field(k), i, 0)
    g.addWidget(wdg, i, 1)
g.setColumnStretch(1, 1)
pl.addLayout(g)
pl.addSpacing(6)
h2 = QLabel("Port forwarding")
h2.setProperty("role", "heading")
pl.addWidget(h2)
fw = QTreeWidget()
fw.setHeaderLabels(["KIND", "HERE", "THERE"])
fw.setRootIsDecorated(False)
fw.setColumnWidth(0, 120)
fw.setColumnWidth(1, 200)
for kind, here, there in (("Local", "127.0.0.1:8000", "localhost:8000  (restic REST server)"),
                          ("Local", "127.0.0.1:5000", "localhost:5000  (NAS web page)")):
    fw.addTopLevelItem(QTreeWidgetItem([kind, here, there]))
fw.setFixedHeight(110)
pl.addWidget(fw)
pl.addWidget(dim("Known host key  ·  ED25519 SHA256:q3Vn0r6xY0M2s1FfVJwW9bQe4d7mTzYw8hJ2kLpA1cE  ·  first seen 2026-03-04"))
pl.addStretch(1)
btns = QHBoxLayout()
btns.addStretch(1)
btns.addWidget(QPushButton("DELETE"))
btns.addWidget(QPushButton("SAVE"))
b = QPushButton("OPEN")
b.setStyleSheet(f"QPushButton {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; font-weight: 600; "
                f"padding: 7px 22px; }}")
btns.addWidget(b)
pl.addLayout(btns)
row.addWidget(panel, 3)
shoot(term_window([("app", "PowerShell"), ("server", "ari@nas.local"), ("gear", "Sessions")], 2, body,
                  status("SESSIONS  ·  6 saved", "Passwords and key passphrases are kept in Windows' Credential "
                         "Manager")), "2_sessions.png")

# ------------------------------------------------------------------ 3: the new-tab menu
theme.set_finish("obsidian")
style()
host = QWidget()
host.resize(1288, 640)
t = Term(PS[:6] + [seg(("PS ", "pink"), ("D:\\Studio\\Projects", "orange"), ("> ", "pink"))], (21, 6))
t.setParent(host)
t.setGeometry(0, 0, 1288, 640)
menu = QFrame(host)
menu.setObjectName("menu")
menu.setStyleSheet(f"QFrame#menu {{ background: {theme.MENU}; border: 1px solid {theme.PANEL_EDGE}; "
                   f"border-radius: 8px; }} QLabel {{ color: {theme.ON_DARK}; }}")
ml = QVBoxLayout(menu)
ml.setContentsMargins(6, 8, 6, 8)
ml.setSpacing(0)


def item(icon, text, key="", lit=False):
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {theme.qss_gradient() if lit else 'transparent'}; border-radius: 5px; }}")
    hl = QHBoxLayout(f)
    hl.setContentsMargins(10, 7, 12, 7)
    ic = QLabel()
    ic.setPixmap(widgets.line_icon(icon, "#FFFFFF" if lit else theme.LED_ORANGE, 16).pixmap(16, 16))
    hl.addWidget(ic)
    lab = QLabel(text)
    hl.addWidget(lab, 1)
    k = QLabel(key)
    k.setStyleSheet(f"color: {'#FFFFFF' if lit else theme.TEXT_DIM}; font-size: 11px;")
    hl.addWidget(k)
    return f


def head(text):
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10.5px; font-weight: 600; padding: 8px 10px 4px 10px;")
    return lab


ml.addWidget(head("THIS PC"))
for icon, text, key in (("app", "PowerShell", "Ctrl+Shift+1"), ("app", "Command Prompt", "Ctrl+Shift+2"),
                        ("desktop", "Ubuntu (WSL)", "Ctrl+Shift+3"), ("app", "Git Bash", "Ctrl+Shift+4"),
                        ("key", "PowerShell as administrator", "")):
    ml.addWidget(item(icon, text, key))
ml.addWidget(head("SAVED SESSIONS"))
for i, (text, key) in enumerate((("NAS  ·  ari@nas.local", ""), ("Render node  ·  render@studio-render", ""),
                                 ("VPS  ·  root@vps.example.net", ""))):
    ml.addWidget(item("server", text, key, lit=i == 0))
ml.addWidget(item("search", "Quick connect…", "Ctrl+Shift+N"))
ml.addWidget(item("gear", "Sessions and settings", "Ctrl+,"))
menu.setGeometry(330, 0, 420, 520)
shoot(term_window([("app", "PowerShell"), ("server", "ari@nas.local"), ("app", "Command Prompt")], 0, host,
                  status("PowerShell  ·  D:\\Studio\\Projects", "Profiles found on this PC: PowerShell 7, Windows "
                         "PowerShell, Command Prompt, Ubuntu (WSL), Git Bash")), "3_newtab.png")
print("ok", out)
