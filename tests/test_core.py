import os
import socket
import sys
import threading

import paramiko
import pytest

from conftest import wait
from pr7tm import backends, colours, keys, profiles, screen, sessions


def test_colours_stay_in_the_family():
    import colorsys
    for name in colours.NAMES:
        r, g, b = colours.hexrgb(colours.PALETTE[name])
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        assert s < 0.3 or h * 360 <= 42 or h * 360 >= 318, name          # no green / blue / cyan / purple
    assert colours.resolve("green", "#000000") == colours.PALETTE["green"]
    assert colours.resolve("00cd00", "#000000") == colours.PALETTE["green"]        # 256-colour index 2
    assert colours.resolve("default", "#123456") == "#123456"
    for rgb in ((10, 200, 30), (0, 135, 255), (140, 60, 200), (0, 200, 200), (230, 220, 20)):
        out = colours.resolve("%02x%02x%02x" % rgb, "#000000")
        r, g, b = colours.hexrgb(out)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        assert s < 0.2 or h * 360 <= 42 or h * 360 >= 318, (rgb, out)
    assert colours.family(244, 53, 58) == (244, 53, 58)                    # the family red stays
    assert colours.family(128, 128, 128) == (128, 128, 128)               # greys stay


def test_terminal_screen_scrollback_and_replies():
    t = screen.Terminal(20, 3, history=100)
    for i in range(6):
        t.feed(f"line {i}\r\n".encode())
    assert t.scrollback >= 3 and t.row_text(t.rows()[0]).rstrip() == "line 4"
    assert t.row_text(t.rows(offset=2)[0]).rstrip() == "line 2"
    assert t.feed(b"\x1b[6n") == [b"\x1b[3;1R"]                              # where's the cursor? answered
    t.feed("é ü 日本\r\n".encode()[:3])                                        # UTF-8 split across reads
    t.feed("é ü 日本\r\n".encode()[3:])
    assert "é ü 日本" in t.screen_text()
    t.feed(b"\x1b]0;my title\x07")
    assert t.title == "my title"
    t.feed(b"\x1b[?1h")
    assert t.app_cursor
    t.feed(b"\x1b[?2004h")
    assert t.bracketed_paste
    hits = t.find("LINE 3")
    assert hits and t.text(hits[0], (hits[0][0], hits[0][1] + 5)) == "line 3"


def test_keys():
    assert keys.encode("Up") == b"\x1b[A" and keys.encode("Up", app_cursor=True) == b"\x1bOA"
    assert keys.encode("Up", ctrl=True) == b"\x1b[1;5A" and keys.encode("F5") == b"\x1b[15~"
    assert keys.encode("F1") == b"\x1bOP" and keys.encode("Delete") == b"\x1b[3~"
    assert keys.encode("", "c", ctrl=True) == b"\x03" and keys.encode("", "x", alt=True) == b"\x1bx"
    assert keys.encode("Backspace") == b"\x7f" and keys.encode("Tab", shift=True) == b"\x1b[Z"
    assert keys.encode("", "é") == "é".encode()
    assert keys.paste("a\nb", bracketed=False) == b"a\rb"
    assert keys.paste("a\r\nb", bracketed=True) == b"\x1b[200~a\rb\x1b[201~"


def test_quick_connect_parsing():
    assert sessions.parse_target("ari@nas.local") == ("ari", "nas.local", 22)
    assert sessions.parse_target("nas.local:2222") == ("", "nas.local", 2222)
    assert sessions.parse_target("ssh render@studio-render -p 2222") == ("render", "studio-render", 2222)
    assert sessions.parse_target("[::1]:2200") == ("", "::1", 2200)
    assert sessions.parse_target("not a host") is None and sessions.parse_target("") is None


def test_sessions_keep_no_secrets(data):
    s = sessions.Session("NAS", "nas.local", user="ari", auth="password",
                         forwards=[sessions.Forward(here="127.0.0.1:8000", there="localhost:8000")])
    sessions.set_secret(s.id, "hunter2 hunter2")
    sessions.save([s])
    assert "hunter2" not in open(sessions.path()).read()
    back = sessions.load()[0]
    assert back.target() == "ari@nas.local" and back.forwards[0].there == "localhost:8000"
    assert sessions.secret(s.id) == "hunter2 hunter2"


def test_profiles_on_windows_shape():
    files = {r"C:\Program Files\PowerShell\7\pwsh.exe", r"C:\Program Files\Git\bin\bash.exe",
             r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"}
    import ntpath
    os.environ.setdefault("SystemRoot", r"C:\Windows")
    got = profiles.find(exists=lambda p: ntpath.normpath(p) in files or p in files, which=lambda n: None,
                        distros=["Ubuntu"])
    names = [p.name for p in got]
    if sys.platform == "win32" or True:
        assert names[0] == "PowerShell" and "Command Prompt" in names and "Ubuntu (WSL)" in names
        assert "Git Bash" in names and got[-1].admin and got[-1].name == "PowerShell as administrator"
    out = "Ubuntu\r\nDebian\r\n".encode("utf-16-le")
    assert profiles.wsl_distros(run=lambda a: out) == ["Ubuntu", "Debian"]


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX pseudo terminal")
def test_local_shell_for_real():
    b = backends.LocalBackend(["/bin/sh"], env={"PS1": "$ ", "PATH": os.environ.get("PATH", "")})
    got = bytearray()
    ended = []
    b.on_data = got.extend
    b.on_exit = ended.append
    b.start(100, 30)
    b.write(b"stty size; echo hello-$((40+2))\n")
    assert wait(lambda: b"hello-42" in got), got
    assert b"30 100" in got                                                 # the pty knows its size
    b.resize(120, 40)
    b.write(b"stty size\n")
    assert wait(lambda: b"40 120" in got)
    b.write(b"exit\n")
    assert wait(lambda: ended) and "exit code 0" in ended[0]


def test_ssh_password_hostkey_and_resize(data, ssh_server):
    s = sessions.Session("test", "127.0.0.1", ssh_server.port, "ari", auth="password", command="echo started")
    asked = []

    def ask(kind, payload):
        asked.append((kind, payload))
        return {"hostkey": True, "password": "s3cret pass"}[kind]
    b = backends.SSHBackend(s, ask=ask)
    got = bytearray()
    b.on_data = got.extend
    b.start(90, 25)
    assert [k for k, _ in asked] == ["hostkey", "password"] and asked[0][1][2].startswith("SHA256:")
    assert ssh_server.terms == ["xterm-256color"]
    assert wait(lambda: b"started" in got)                                  # the command after connecting
    b.write(b"size\r")
    assert wait(lambda: b"90x25" in got)
    b.resize(100, 30)
    import time
    time.sleep(0.3)
    b.write(b"size\r")
    assert wait(lambda: b"100x30" in got)
    ended = []
    b.on_exit = ended.append
    b.write(b"exit\r")
    assert wait(lambda: ended)
    b.close()
    # the second time the key is known: no question; a saved password isn't asked
    sessions.set_secret(s.id, "s3cret pass")
    asked.clear()
    b2 = backends.SSHBackend(s, ask=ask)
    b2.start(80, 24)
    assert asked == []
    b2.close()


def test_ssh_refused_key_and_changed_key(data, ssh_server, tmp_path):
    s = sessions.Session("test", "127.0.0.1", ssh_server.port, "ari", auth="password")
    sessions.set_secret(s.id, "s3cret pass")
    with pytest.raises(Exception, match="wasn't accepted"):
        backends.SSHBackend(s, ask=lambda k, p: False).connect()
    # a known host with a different key: refused, as PuTTY does
    kh = sessions.known_hosts()
    os.makedirs(os.path.dirname(kh), exist_ok=True)
    other = paramiko.ECDSAKey.generate()
    with open(kh, "w") as f:
        f.write(f"[127.0.0.1]:{ssh_server.port} {other.get_name()} {other.get_base64()}\n")
    with pytest.raises(ConnectionError, match="CHANGED"):
        backends.SSHBackend(s, ask=lambda k, p: True).connect()


def test_ssh_key_file_and_port_forwarding(data, tmp_path):
    from sshserver import SSHServerThread
    pk = paramiko.RSAKey.generate(2048)
    keyfile = tmp_path / "id_rsa"
    pk.write_private_key_file(str(keyfile), password="phrase")
    srv = SSHServerThread(pubkey=pk)
    echo = socket.socket()
    echo.bind(("127.0.0.1", 0))
    echo.listen(1)
    eport = echo.getsockname()[1]

    def echo_once():
        c, _ = echo.accept()
        c.sendall(c.recv(100).upper())
        c.close()
    threading.Thread(target=echo_once, daemon=True).start()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    lport = free.getsockname()[1]
    free.close()
    s = sessions.Session("k", "127.0.0.1", srv.port, "ari", auth="key", key_file=str(keyfile),
                         forwards=[sessions.Forward(here=f"127.0.0.1:{lport}", there=f"localhost:{eport}")])
    asked = []
    b = backends.SSHBackend(s, ask=lambda k, p: asked.append(k) or {"hostkey": True, "passphrase": "phrase"}[k])
    b.start(80, 24)
    assert asked == ["hostkey", "passphrase"]
    c = socket.create_connection(("127.0.0.1", lport), timeout=5)
    c.sendall(b"through the tunnel")
    assert c.recv(100) == b"THROUGH THE TUNNEL"
    c.close()
    b.close()
    srv.stop()


def test_shrinking_keeps_the_text_near_the_cursor():
    t = screen.Terminal(30, 10, history=100)
    for i in range(4):
        t.feed(f"line {i}\r\n".encode())
    t.feed(b"$ ")
    t.resize(30, 3)                                    # cursor on row 4: two lines go up into the scrollback
    assert [t.row_text(r).rstrip() for r in t.rows()] == ["line 2", "line 3", "$"]
    assert t.cursor == (2, 2) and t.scrollback == 2
    t.resize(30, 10)
    assert t.row_text(t.rows()[0]).rstrip() == "line 2"
