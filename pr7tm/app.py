"""Start PR7-TM.

    PR7-TM.exe                         a window with the default profile (one window per user: starting it again
                                       opens a new tab in it, as Windows Terminal's default does)
    PR7-TM.exe --profile NAME          that profile ("PowerShell", "Ubuntu (WSL)" ...)
    PR7-TM.exe --session NAME          a saved session
    PR7-TM.exe ssh user@host[:port]    quick connect
    PR7-TM.exe --version
    PR7-TM.exe --selftest OUT.json     a real shell through the real window offscreen (ConPTY on Windows): types a
                                       command, reads its output back, resizes; writes what it saw (CI checks the
                                       installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import time

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-TM-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over(args: list[str]) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(json.dumps({"args": args}).encode() + b"\n")
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def open_from_args(window, args: list[str]) -> bool:
    """What the command line asks for, as a new tab; False when it asked for nothing in particular."""
    from . import sessions
    if args[:1] == ["--profile"] and len(args) >= 2:
        name = args[1].casefold()
        i = next((i for i, p in enumerate(window.profiles) if p.name.casefold() == name and not p.admin), None)
        if i is not None:
            window.new_tab(i)
            return True
    if args[:1] == ["--session"] and len(args) >= 2:
        s = next((x for x in window.sessions if x.name.casefold() == args[1].casefold()), None)
        if s is not None:
            window.open_session(s)
            return True
    if args[:1] == ["ssh"] and len(args) >= 2:
        got = sessions.parse_target(" ".join(args[1:]))
        if got:
            user, host, port = got
            s = next((x for x in window.sessions if x.host == host and x.port == port and (x.user == user or not user)),
                     None) or sessions.Session(f"{user + '@' if user else ''}{host}", host, port, user, auth="password")
            window.open_session(s)
            return True
    return False


def listen(window):
    """Later starts hand over to this window (PR7-R's hand-off, with its Windows fix: data may already be waiting)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = []

        def read():
            buf.extend(bytes(sock.readAll()))
            if buf.endswith(b"\n") and not done:
                done.append(True)
                try:
                    args = json.loads(buf.decode()).get("args", [])
                except ValueError:
                    args = []
                if not open_from_args(window, args):
                    window.new_tab()
                window.showNormal()
                window.raise_()
                window.activateWindow()
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        sock.disconnected.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(out: str) -> int:
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7TM_DATA"] = tempfile.mkdtemp()
    os.environ["PR7TM_MEMORY_KEYRING"] = "1"
    result = {}
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
        from . import __version__, profiles, theme
        from .main_window import MainWindow
        app = QApplication.instance() or QApplication(sys.argv[:1])
        theme.load_fonts()
        found = profiles.find()
        if sys.platform == "win32":
            shell = profiles.Profile("Command Prompt", [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                                                    "System32", "cmd.exe")])
            command = b"echo pr7tm-selftest-%NUMBER_OF_PROCESSORS%-ok\r"
        else:
            shell = profiles.Profile("sh", ["/bin/sh"])
            command = b"echo pr7tm-selftest-$((40+2))-ok\r"
        w = MainWindow(profile_list=[shell])
        w.answers.update({"say": lambda k, t: None, "confirm": True, "last_tab_closed": False})
        w.resize(1200, 800)
        w.show()
        v = w.new_tab(0)

        def spin(cond, seconds=30):
            end = time.time() + seconds
            while time.time() < end and not cond():
                app.processEvents()
                time.sleep(0.02)
            return cond()
        spin(lambda: v.started)
        spin(lambda: v.term.screen_text().strip(), 20)              # the shell's first output (prompt)
        v.backend.write(command)
        seen = spin(lambda: "pr7tm-selftest-" in v.term.screen_text() and "-ok" in
                    v.term.screen_text().split("pr7tm-selftest-", 2)[-1], 30)
        size_before = (v.term.cols, v.term.lines)
        w.resize(900, 600)
        spin(lambda: (v.term.cols, v.term.lines) != size_before, 5)
        w.split(None)
        app.processEvents()
        panes = len(w.tab().panes())
        w.grab()
        text = v.term.screen_text()
        result = {"version": __version__, "echo": seen, "screen": text[-600:], "panes": panes,
                  "resized": (v.term.cols, v.term.lines) != size_before, "profiles": [p.name for p in found],
                  "fonts": "Inter" in QFontDatabase.families()}
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if result.get("echo") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["--version"]:
            from . import __version__
            print(__version__)
            return 0
        if argv[:1] == ["--selftest"] and len(argv) == 2:
            return selftest(argv[1])
    except Exception:  # noqa: BLE001 - a command-line mode never waits on an error box (PR7-IS's lesson)
        return 1
    from PySide6.QtWidgets import QApplication

    from . import finish, settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-TM")
    if hand_over(argv):
        return 0
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    from PySide6.QtGui import QFont, QIcon
    app.setFont(QFont("Inter", 10))
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    w.show()
    if not open_from_args(w, argv):
        w.new_tab()
    from PySide6.QtCore import QTimer
    follow = QTimer(w)                            # one finish for the family: follow another app's switch
    follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    follow.start(2000)
    listen(w)
    from . import update_ui
    update_ui.start(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
