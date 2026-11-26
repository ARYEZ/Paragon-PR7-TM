"""The shells on this PC (no Qt), as Windows Terminal finds them: PowerShell 7, Windows PowerShell, Command Prompt,
each WSL distribution, Git Bash. On Linux (tests): the user's $SHELL. A profile is (name, command line, icon)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Profile:
    name: str
    argv: list
    icon: str = "app"
    admin: bool = False
    cwd: str = ""


def _system(*parts) -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), *parts)


def wsl_distros(run=None) -> list[str]:
    """`wsl.exe -l -q`, which answers in UTF-16."""
    exe = _system("System32", "wsl.exe")
    if run is None:
        if not os.path.exists(exe):
            return []
        try:
            out = subprocess.run([exe, "-l", "-q"], capture_output=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    else:
        out = run([exe, "-l", "-q"])
    text = out.decode("utf-16-le", "ignore") if b"\x00" in out else out.decode("utf-8", "ignore")
    return [d.strip().strip("\x00") for d in text.splitlines() if d.strip().strip("\x00")]


def find(exists=os.path.exists, which=shutil.which, distros=None) -> list[Profile]:
    if sys.platform != "win32" and exists is os.path.exists:
        shell = os.environ.get("SHELL") or which("bash") or "/bin/sh"
        return [Profile(os.path.basename(shell), [shell, "-i"], "app")]
    out = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pwsh = which("pwsh.exe") or next((p for p in (os.path.join(pf, "PowerShell", "7", "pwsh.exe"),) if exists(p)), None)
    if pwsh:
        out.append(Profile("PowerShell", [pwsh, "-NoLogo"], "app"))
    winps = _system("System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if exists(winps):
        out.append(Profile("Windows PowerShell" if pwsh else "PowerShell", [winps, "-NoLogo"], "app"))
    out.append(Profile("Command Prompt", [_system("System32", "cmd.exe")], "app"))
    for d in (distros if distros is not None else wsl_distros()):
        out.append(Profile(f"{d} (WSL)", [_system("System32", "wsl.exe"), "-d", d], "desktop"))
    bash = os.path.join(pf, "Git", "bin", "bash.exe")
    if exists(bash):
        out.append(Profile("Git Bash", [bash, "--login", "-i"], "app"))
    first = out[0]
    out.append(Profile(f"{first.name} as administrator", first.argv, "key", admin=True))
    return out
