import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7TM_DATA"] = tempfile.mkdtemp(prefix="pr7tm-data-")      # never the real data folder
os.environ["PR7TM_MEMORY_KEYRING"] = "1"                               # never the real Credential Manager

@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7tm import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()



@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("PR7TM_DATA", str(d))
    from pr7tm import sessions
    sessions._memory.clear()
    return d


@pytest.fixture
def ssh_server():
    from sshserver import SSHServerThread
    s = SSHServerThread()
    yield s
    s.stop()


def wait(cond, timeout=10.0, step=0.02):
    """Spin the Qt event loop (if there is one) until cond() is true."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance():
                QApplication.instance().processEvents()
        except ImportError:
            pass
        if cond():
            return True
        time.sleep(step)
    return cond()


@pytest.fixture
def window(qapp, data):
    """The real window with /bin/sh as its one profile (Windows CI: cmd.exe); questions answered by `answers`."""
    from pr7tm import profiles, settings
    from pr7tm.main_window import MainWindow
    for k, v in (("font_size", 11), ("scrollback", 10000), ("default_profile", "")):
        settings.set(k, v)
    if sys.platform == "win32":
        prof = profiles.Profile("Command Prompt", [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                                                "System32", "cmd.exe")])
    else:
        prof = profiles.Profile("sh", ["/bin/sh"])
    w = MainWindow(profile_list=[prof, profiles.Profile("sh as administrator", prof.argv, "key", admin=True)])
    w.said = []
    w.answers.update({"say": lambda kind, text: w.said.append((kind, text)), "confirm": True,
                      "last_tab_closed": False, "menu": True})
    w.resize(1200, 800)
    w.show()
    yield w
    w.answers["confirm"] = True
    w.close()
