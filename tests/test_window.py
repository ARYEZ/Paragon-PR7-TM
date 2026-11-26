import json
import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import wait
from pr7tm import __version__, sessions
from pr7tm.main_window import SessionsPage, Tab

ECHO = b"echo hi-%NUMBER_OF_PROCESSORS%-there\r" if sys.platform == "win32" else b"echo hi-$((6*7))-there\r"


def shown(v, text):
    return wait(lambda: text in v.term.screen_text(), 20)


def test_a_tab_runs_a_real_shell_and_types(window):
    v = window.new_tab()
    assert wait(lambda: v.started and v.term.screen_text().strip())
    QTest.keyClicks(v, "echo typed-in")
    QTest.keyClick(v, Qt.Key.Key_Return)
    assert shown(v, "typed-in\n") or shown(v, "typed-in")
    v.backend.write(ECHO)
    assert wait(lambda: "-there" in v.term.screen_text().split("echo hi-")[-1], 20)
    assert window.tabbar.count() == 1 and window.status.text().endswith(f"{v.term.cols} × {v.term.lines}")
    window.grab()


def test_splits_focus_and_closing(window):
    v = window.new_tab()
    wait(lambda: v.started)
    right = window.split(Qt.Orientation.Horizontal)
    down = window.split(Qt.Orientation.Vertical)
    wait(lambda: down.height() > 0 and right.height() > 0 and down.y() > 0, 5)     # laid out
    t = window.tab()
    assert isinstance(t, Tab) and len(t.panes()) == 3 and t.current is down
    window.move_focus("Up")
    assert t.current is right
    window.move_focus("Left")
    assert t.current is v
    window.close_pane(down)
    assert len(t.panes()) == 2
    window.close_pane(right)
    assert t.panes() == [v] and t.root is v
    window.close_pane(v)
    assert window.tabbar.count() == 0


def test_copy_paste_and_selection(window, qapp):
    v = window.new_tab()
    wait(lambda: v.started and v.term.screen_text().strip())
    v.backend.write(b"echo selectable-text\r")
    assert shown(v, "selectable-text\n") or shown(v, "selectable-text")
    hits = v.term.find("selectable-text")
    r, c = hits[-1]
    v.sel_start, v.sel_end = (r, c), (r, c + len("selectable-text") - 1)
    QTest.keyClick(v, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)     # Ctrl+C with a selection copies
    assert qapp.clipboard().text() == "selectable-text" and v.selected_text() == ""
    qapp.clipboard().setText("echo pasted-in\n")
    QTest.keyClick(v, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert shown(v, "pasted-in\n") or wait(lambda: v.term.screen_text().count("pasted-in") >= 2)


def test_find(window):
    v = window.new_tab()
    wait(lambda: v.started and v.term.screen_text().strip())
    v.backend.write(b"echo needle-one\r")
    assert shown(v, "needle-one")
    window.show_find()
    window.find_edit.setText("NEEDLE")
    assert len(v.hits) >= 1 and window.find_count.text().endswith(f"of {len(v.hits)}")
    window.grab()
    window.hide_find()
    assert v.hits == []


def test_program_end_enter_closes_r_restarts(window):
    v = window.new_tab()
    wait(lambda: v.started and v.term.screen_text().strip())
    v.backend.write(b"exit\r")
    assert wait(lambda: v.ended)
    assert "Enter closes this pane" in v.term.screen_text()
    QTest.keyClick(v, Qt.Key.Key_R)
    new = window.pane()
    assert new is not v and wait(lambda: new.started)
    new.backend.write(b"exit\r")
    assert wait(lambda: new.ended)
    QTest.keyClick(new, Qt.Key.Key_Return)
    assert window.tabbar.count() == 0


def test_admin_profile_asks_windows(window):
    asked = []
    window.answers["elevate"] = lambda p: asked.append(p.name) or True
    assert window.new_tab(1) is None and asked == ["sh as administrator"]


def test_new_tab_menu_lists_profiles_and_sessions(window, data):
    window.sessions = [sessions.Session("NAS", "nas.local", user="ari")]
    m = window.new_tab_menu()
    texts = [a.text() for a in m.actions() if a.text()]
    assert texts[:3] == ["THIS PC", "sh", "sh as administrator"]
    assert "SAVED SESSIONS" in texts and "NAS  ·  ari@nas.local" in texts and "Quick connect…" in texts


def test_ssh_tab_through_the_window(window, ssh_server):
    asked = []
    window.answers.update({"hostkey": lambda p: asked.append("hostkey") or True,
                           "password": lambda s: asked.append("password") or "s3cret pass"})
    window.answers["text"] = f"ari@127.0.0.1:{ssh_server.port}"
    v = window.quick_connect()
    assert v is not None and shown(v, "Welcome to the test server")
    assert asked == ["hostkey", "password"]
    QTest.keyClicks(v, "echo over ssh")
    QTest.keyClick(v, Qt.Key.Key_Return)
    assert wait(lambda: "over ssh\n" in v.term.screen_text().split("echo over ssh")[-1])
    v.backend.write(b"colours\r")
    assert shown(v, "green blue")
    window.grab()                                               # green and blue drawn in family colours
    window.answers["text"] = "not an address"
    assert window.quick_connect() is None and "isn't an address" in window.said[-1][1]


def test_sessions_page_saves_and_opens(window, data, ssh_server):
    page = window.show_sessions()
    assert isinstance(page, SessionsPage) and window.tabbar.tabText(window.tabbar.currentIndex()) == "Sessions"
    page.new()
    page.f_name.setText("Test box")
    page.f_host.setText("127.0.0.1")
    page.f_port.setValue(ssh_server.port)
    page.f_user.setText("ari")
    page.f_auth.setCurrentIndex(page.f_auth.findData("password"))
    page.f_secret.setText("s3cret pass")
    page.f_then.setText("echo from-the-session")
    page.f_folder.setCurrentText("Home")
    page.f_here.setText("127.0.0.1:18022")
    page.f_there.setText("localhost:22")
    page.add_forward()
    s = page.save()
    assert s and sessions.load()[0].folder == "Home" and sessions.secret(s.id) == "s3cret pass"
    assert "s3cret" not in open(sessions.path()).read()
    assert page.tree.topLevelItem(0).text(0) == "Home"
    s.forwards = []                                             # not opening a port in this test
    sessions.save(window.sessions)
    page.f_here.clear()
    page.fw.clear()
    window.answers["hostkey"] = True
    page.open()
    v = window.pane()
    assert shown(v, "from-the-session")
    page = window.show_sessions()
    page.fill(s.id)
    assert page.hostkey.text().startswith("Known host key")
    window.answers["confirm"] = True
    assert page.delete() and sessions.load() == [] and sessions.secret(s.id) == ""


def test_selftest(tmp_path):
    out = tmp_path / "self.json"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "pr7tm", "--selftest", str(out)], cwd=root, capture_output=True,
                       text=True, timeout=180)
    got = json.loads(out.read_text())
    assert r.returncode == 0, (got, r.stderr)
    assert got["version"] == __version__ and got["echo"] and got["panes"] == 2 and got["resized"] and got["fonts"]


def test_second_start_hands_over():
    code = ("import sys, os; sys.path.insert(0, sys.argv[1]); os.environ['QT_QPA_PLATFORM']='offscreen';"
            "from PySide6.QtWidgets import QApplication; a = QApplication([]);"
            "from pr7tm import app; print(app.hand_over([]))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-c", code, root], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "False"


def test_family_list_is_whole():
    from pr7tm import family
    assert len(set(family.APPS.values())) == len(family.APPS) and {"PR7-HW", "PR7-BK", "PR7-TM"} <= set(family.APPS)
