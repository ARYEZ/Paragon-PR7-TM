"""Keys -> what a terminal sends (no Qt; the view passes key names). xterm's sequences, as Windows Terminal sends
them: arrows depend on application-cursor mode (vim, less), function keys and Home / End / Page keys have their
escape codes, Ctrl+letter is the control character, Alt adds ESC in front, Shift / Ctrl with arrows use xterm's
modifier codes (;2 / ;5 / ;3)."""

from __future__ import annotations

CSI, SS3 = "\x1b[", "\x1bO"
TILDE = {"Insert": 2, "Delete": 3, "PageUp": 5, "PageDown": 6, "F5": 15, "F6": 17, "F7": 18, "F8": 19, "F9": 20,
         "F10": 21, "F11": 23, "F12": 24}
ARROWS = {"Up": "A", "Down": "B", "Right": "C", "Left": "D", "Home": "H", "End": "F"}
SS3_KEYS = {"F1": "P", "F2": "Q", "F3": "R", "F4": "S"}


def _mod(shift: bool, alt: bool, ctrl: bool) -> int:
    return 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)


def encode(name: str, text: str = "", ctrl: bool = False, alt: bool = False, shift: bool = False,
           app_cursor: bool = False) -> bytes:
    """`name`: a key name ("Up", "F5", "Return", "Backspace", "Tab", "Escape") or "" for a printable key with
    `text`. Returns b"" for keys a terminal doesn't send."""
    m = _mod(shift, alt, ctrl)
    if name in ARROWS:
        code = ARROWS[name]
        if m > 1:
            return f"{CSI}1;{m}{code}".encode()
        return f"{SS3 if app_cursor else CSI}{code}".encode()
    if name in SS3_KEYS:
        return (f"{CSI}1;{m}{SS3_KEYS[name]}" if m > 1 else f"{SS3}{SS3_KEYS[name]}").encode()
    if name in TILDE:
        n = TILDE[name]
        return (f"{CSI}{n};{m}~" if m > 1 else f"{CSI}{n}~").encode()
    if name == "Return":
        return b"\x1b\r" if alt else b"\r"
    if name == "Backspace":
        seq = b"\x08" if ctrl else b"\x7f"
        return b"\x1b" + seq if alt else seq
    if name == "Tab":
        return f"{CSI}Z".encode() if shift else b"\t"
    if name == "Escape":
        return b"\x1b"
    if not text:
        return b""
    if ctrl and len(text) == 1:
        c = text.upper()
        if "@" <= c <= "_":                       # Ctrl+A .. Ctrl+Z, Ctrl+[ \ ] ^ _
            seq = bytes([ord(c) - 64])
        elif c == " " or c == "2":
            seq = b"\x00"
        elif c == "/":
            seq = b"\x1f"
        else:
            seq = text.encode("utf-8")
        return b"\x1b" + seq if alt else seq
    data = text.encode("utf-8")
    return b"\x1b" + data if alt else data


def paste(text: str, bracketed: bool) -> bytes:
    """A paste: line breaks as Enter (\\r), wrapped in ESC[200~ ... ESC[201~ when the program asked (so a shell
    doesn't run each line as it arrives)."""
    body = text.replace("\r\n", "\n").replace("\n", "\r").encode("utf-8")
    if bracketed:
        body = body.replace(b"\x1b[201~", b"")    # a paste can't end the paste early
        return b"\x1b[200~" + body + b"\x1b[201~"
    return body
