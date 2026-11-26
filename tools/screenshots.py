"""Screenshots of the real PR7-TM window, offscreen. The shells' output is canned (ANSI as PowerShell and an SSH
server print it) through a stand-in backend, so the pictures are the same every time:
QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR

tabs.png              PowerShell and an SSH session side by side (OBSIDIAN)
sessions_aurora.png   the Sessions page (AURORA)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PR7TM_DATA"] = str(tmp / "data")
os.environ["PR7TM_MEMORY_KEYRING"] = "1"
os.environ["PARAGON_FAMILY_FILE"] = str(tmp / "finish")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "settings"))

from pr7tm import backends, profiles, sessions, theme  # noqa: E402
from pr7tm.main_window import MainWindow  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))
E = "\x1b["
PS = (f"PowerShell 7.5.4\r\n{E}95mPS {E}93mD:\\Studio\\Projects{E}95m> {E}0mgit status -sb\r\n"
      f"## main...origin/main {E}31m[ahead 2]{E}0m\r\n {E}31mM{E}0m titles/elseworld_titles_v6.blend\r\n"
      f"{E}32m??{E}0m titles/titles_notes.txt\r\n{E}95mPS {E}93mD:\\Studio\\Projects{E}95m> {E}0m"
      f"Get-ChildItem renders | Select -Last 3\r\n\r\n    Directory: D:\\Studio\\Projects\\renders\r\n\r\n"
      f"{E}1;36mMode     LastWriteTime        Length Name{E}0m\r\n{E}36m----     -------------        ------ ----{E}0m\r\n"
      f"-a---    26/11/2026  00:41  48213337 {E}93mtitles_v6_0001-0240.mp4{E}0m\r\n"
      f"-a---    26/11/2026  00:58  51004122 {E}93mtitles_v6_0241-0480.mp4{E}0m\r\n"
      f"d----    25/11/2026  22:10           {E}1;34mframes{E}0m\r\n\r\n{E}95mPS {E}93mD:\\Studio\\Projects{E}95m> {E}0m")
NAS = (f"{E}90mLinux nas 6.8.0-49-generic x86_64{E}0m\r\n{E}1;33mari@nas{E}0m:{E}1;34m~{E}0m$ df -h /srv/backups\r\n"
       f"{E}1;36mFilesystem      Size  Used Avail Use% Mounted on{E}0m\r\n/dev/md0         15T  8.2T  6.8T  55% /srv/backups\r\n"
       f"{E}1;33mari@nas{E}0m:{E}1;34m~{E}0m$ systemctl status restic-rest\r\n{E}32m●{E}0m {E}1mrestic-rest.service - restic "
       f"REST server{E}0m\r\n     Active: {E}1;32mactive (running){E}0m since Mon 2026-11-23\r\n"
       f"{E}1;33mari@nas{E}0m:{E}1;34m~{E}0m$ ls --color\r\n{E}1;34mbackups{E}0m  {E}1;32mdeploy.sh{E}0m  "
       f"{E}1;36mlatest -> backups/2026-11-26{E}0m  notes.txt\r\n{E}1;33mari@nas{E}0m:{E}1;34m~{E}0m$ ")


class Canned(backends.Backend):
    def __init__(self, text, name):
        super().__init__()
        self.text, self.description = text, name

    def start(self, cols, rows):
        self.alive = True
        self.on_data(self.text.encode())

    def write(self, data):
        pass


w = MainWindow(profile_list=[profiles.Profile("PowerShell", ["pwsh"]), profiles.Profile("Command Prompt", ["cmd"])])
w.sessions = [sessions.Session("NAS", "nas.local", user="ari", folder="Home", command="tmux new -A -s main",
                               forwards=[sessions.Forward(here="127.0.0.1:8000", there="localhost:8000 (restic REST)")]),
              sessions.Session("Pi-hole", "192.168.1.2", user="pi", folder="Home"),
              sessions.Session("Render node", "studio-render", 2222, "render", folder="Studio"),
              sessions.Session("VPS", "vps.example.net", user="root", folder="Cloud", auth="password")]
w.answers.update({"say": lambda k, t: None, "confirm": True, "last_tab_closed": False})
w.profile_backend = lambda p: Canned(PS, p.name)
w.resize(1320, 860)
w.show()
v = w.new_tab(0)
app.processEvents()
v.start()
right = w._make_pane(Canned(NAS, "ari@nas.local"), "ari@nas.local")
w.tab().split(right, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Orientation.Horizontal)
app.processEvents()
right.start()
v.setFocus()
for _ in range(5):
    app.processEvents()
w.tabbar.setTabText(0, "PowerShell")


def shoot(name):
    for _ in range(5):
        app.processEvents()
    w.grab().save(str(out / name))


w.set_finish("obsidian")
shoot("tabs.png")
w.set_finish("aurora")
page = w.show_sessions()
page.fill(w.sessions[0].id)
shoot("sessions_aurora.png")
w.set_finish("obsidian")
w.close()
print("ok", out)
