"""Saved SSH sessions (no Qt), PuTTY's main strength: host, port, user, how to sign in, keep-alive, a command to run
on connecting, port forwarding, a folder to group them. Kept in <data>/sessions.json (%APPDATA%\\Paragon\\PR7-TM;
PR7TM_DATA in tests). Passwords and key passphrases are never in that file: Windows' Credential Manager keeps them
through keyring ("Paragon PR7-TM"; PR7TM_MEMORY_KEYRING in tests). Known host keys in <data>/known_hosts."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field

AUTH = {"key": "Key file", "password": "Password", "agent": "SSH agent (Pageant / OpenSSH agent)"}


def data_folder() -> str:
    env = os.environ.get("PR7TM_DATA")
    if env:
        return env
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.path.join(os.path.expanduser("~"), ".local",
                                                                                    "share")
    return os.path.join(base or os.path.expanduser("~"), "Paragon", "PR7-TM")


@dataclass
class Forward:
    kind: str = "local"                  # local: a port here reaches one there (ssh -L)
    here: str = "127.0.0.1:8000"
    there: str = "localhost:8000"
    note: str = ""


@dataclass
class Session:
    name: str
    host: str
    port: int = 22
    user: str = ""
    auth: str = "key"                    # AUTH
    key_file: str = ""
    keepalive: int = 30                  # seconds; 0 = off
    command: str = ""                    # run after connecting ("tmux new -A -s main")
    folder: str = ""
    forwards: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def target(self) -> str:
        return f"{self.user + '@' if self.user else ''}{self.host}{':' + str(self.port) if self.port != 22 else ''}"

    @staticmethod
    def from_dict(d: dict) -> "Session":
        d = dict(d)
        d["forwards"] = [Forward(**f) for f in d.get("forwards", [])]
        known = set(Session.__dataclass_fields__)
        return Session(**{k: v for k, v in d.items() if k in known})


def parse_target(text: str) -> tuple[str, str, int] | None:
    """Quick connect: "user@host", "host:2222", "ssh ari@nas.local -p 2222" -> (user, host, port)."""
    t = text.strip()
    if t.startswith("ssh "):
        t = t[4:].strip()
    port = 22
    m = re.search(r"\s-p\s*(\d+)", " " + t)
    if m:
        port = int(m.group(1))
        t = re.sub(r"\s*-p\s*\d+", "", t).strip()
    if not t or " " in t:
        return None
    user, _, host = t.rpartition("@")
    if host.startswith("[") and "]" in host:              # [::1]:2222
        h, _, rest = host[1:].partition("]")
        host = h
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    elif host.count(":") == 1:
        host, _, p = host.partition(":")
        if not p.isdigit():
            return None
        port = int(p)
    if not host or not re.fullmatch(r"[A-Za-z0-9._\-:]+", host):
        return None
    return user, host, port


def path() -> str:
    return os.path.join(data_folder(), "sessions.json")


def load() -> list[Session]:
    try:
        with open(path(), encoding="utf-8") as f:
            return [Session.from_dict(d) for d in json.load(f).get("sessions", [])]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def save(items: list[Session]):
    os.makedirs(data_folder(), exist_ok=True)
    tmp = path() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "sessions": [asdict(s) for s in items]}, f, indent=1)
    os.replace(tmp, path())


def known_hosts() -> str:
    return os.path.join(data_folder(), "known_hosts")


# ---------------------------------------------------------------- secrets (PR7-F's scheme)
SERVICE = "Paragon PR7-TM"
_memory: dict[str, str] = {}


def _keyring():
    if os.environ.get("PR7TM_MEMORY_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - no usable keyring: memory for this run only
        return None


def secret(session_id: str) -> str:
    kr = _keyring()
    if kr is None:
        return _memory.get(session_id, "")
    try:
        return kr.get_password(SERVICE, session_id) or ""
    except Exception:  # noqa: BLE001
        return ""


def set_secret(session_id: str, value: str):
    kr = _keyring()
    if kr is None:
        if value:
            _memory[session_id] = value
        else:
            _memory.pop(session_id, None)
        return
    try:
        if value:
            kr.set_password(SERVICE, session_id, value)
        else:
            kr.delete_password(SERVICE, session_id)
    except Exception:  # noqa: BLE001 - nothing to delete
        pass
