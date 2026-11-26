"""Check a real install of PR7-TM-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files (ConPTY's part included), the Start menu entry, the uninstall entry, and the installed exe's
--selftest: a real Command Prompt through ConPTY in the real window, a command typed and its output read back, a resize
and a split.
`uninstalled`: all of it gone."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-TM"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-TM.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{1B3CDC35-2FB9-49F0-A5F3-7211F808AF28}_is1"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-TM.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7tm" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-TM", "Installed apps entry", p)
    check(any((APP / "_internal").rglob("winpty*")), "ConPTY's part (pywinpty) is bundled", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=600, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        if "error" in got:
            print(got["error"])
        check(got.get("echo") is True and got.get("fonts") is True,
              f"the installed exe runs a real shell through ConPTY and reads its output ({got.get('screen', '')[-200:]!r})", p)
        check(got.get("panes") == 2 and got.get("resized") is True, "it splits and resizes", p)
        check("Command Prompt" in got.get("profiles", []), f"it finds this PC's shells ({got.get('profiles')})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-TM.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
