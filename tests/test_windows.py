"""What only real Windows can show (CI runs these): ConPTY shells (Command Prompt, PowerShell) with colours, a resize
and an exit code; the PC's real profiles; the real Credential Manager."""
import os
import sys

import pytest

from conftest import wait

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only (CI)")
SYSTEM = os.environ.get("SystemRoot", r"C:\Windows")


def run_backend(argv, command: bytes, expect: str, cols=100, rows=30):
    from pr7tm import backends, screen
    t = screen.Terminal(cols, rows)
    b = backends.LocalBackend(argv)
    ended = []
    b.on_data = lambda d: [b.write(r) for r in t.feed(d)]
    b.on_exit = ended.append
    b.start(cols, rows)
    assert wait(lambda: t.screen_text().strip(), 30), "no prompt"
    b.write(command)
    assert wait(lambda: expect in t.screen_text(), 30), t.screen_text()
    return b, t, ended


def test_command_prompt_through_conpty():
    b, t, ended = run_backend([os.path.join(SYSTEM, "System32", "cmd.exe")], b"echo conpty-%NUMBER_OF_PROCESSORS%-ok\r",
                              "-ok")
    b.resize(120, 40)
    b.write(b"mode con\r")
    assert wait(lambda: "120" in t.screen_text(), 20), t.screen_text()      # the console knows its new width
    b.write(b"exit 3\r")
    assert wait(lambda: ended, 20) and "exit code 3" in ended[0]


def test_powershell_colours_stay_in_the_family():
    ps = os.path.join(SYSTEM, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    b, t, _ = run_backend([ps, "-NoLogo", "-NoProfile"], b"Write-Host -ForegroundColor Green 'green-text'\r",
                          "green-text")
    from pr7tm import colours
    row = next(r for r in t.rows() if "green-text" in t.row_text(r) and "Write-Host" not in t.row_text(r))
    x = t.row_text(row).index("green-text")
    fg = colours.resolve(row[x].fg, colours.FOREGROUND)
    assert fg == colours.PALETTE["brightgreen"] or fg == colours.PALETTE["green"], (row[x].fg, fg)  # pearl
    b.close()


def test_real_profiles():
    from pr7tm import profiles
    names = [p.name for p in profiles.find()]
    assert "Command Prompt" in names and any("PowerShell" in n for n in names) and names[-1].endswith("administrator")


@pytest.mark.skipif(not os.environ.get("CI"), reason="writes Credential Manager: CI only")
def test_real_credential_manager(monkeypatch):
    from pr7tm import sessions
    monkeypatch.delenv("PR7TM_MEMORY_KEYRING", raising=False)
    try:
        sessions.set_secret("ci-test-session", "s3cret")
        assert sessions.secret("ci-test-session") == "s3cret"
    finally:
        sessions.set_secret("ci-test-session", "")
    assert sessions.secret("ci-test-session") == ""
