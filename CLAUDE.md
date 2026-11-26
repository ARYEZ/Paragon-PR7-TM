# Paragon PR7-TM: notes for Claude

**Paragon PR7-TM** is the owner's personal terminal: Python (**PySide6** + pyte + paramiko + pywinpty) that **works the way
Windows Terminal and PuTTY work**, in the Paragon family look (PR7-Z ... PR7-HW, PR7-BK `ARYEZ/Paragon-PR7-BK`). Windows
10/11 x64 is the target; it runs on Linux for tests. The owner writes Python; explain the why.

## How it's built

- `pr7tm/screen.py` (no Qt): `Terminal` wraps pyte's HistoryScreen + ByteStream: `feed` returns the replies the program
  must get (DSR / DA: ConPTY asks for the cursor position), `rows(offset)` with scrollback, `text`, `find`, modes
  (app cursor = 1 << 5, bracketed paste = 2004 << 5: pyte shifts private modes). `resize` keeps the lines near the cursor
  (shrinking pushes top lines into the scrollback; pyte alone deletes them).
- `pr7tm/keys.py` (no Qt): xterm sequences by key name; `paste` (\r line breaks, ESC[200~ / ESC[201~ when asked).
- `pr7tm/colours.py` (no Qt): the 16 colours in family hues; `resolve` maps pyte's colour names / hex (xterm's first 16
  back to ours) and `family(r, g, b)` moves other hues (green -> pearl, blue -> pink, cyan -> peach, yellow -> orange).
- `pr7tm/backends.py` (no Qt): `LocalBackend` (Windows: pywinpty's PtyProcess = ConPTY; Linux: os.openpty with a controlling
  tty), `SSHBackend` (paramiko Transport step by step: connect, **host key checked first** (new asks, changed refuses,
  <data>/known_hosts), then key file (`PKey.from_path`, passphrase as bytes; a needed passphrase can arrive as TypeError) /
  password (keyboard-interactive fallback) / agent; pty + shell, keep-alive, command, ssh -L forwards). Output arrives on
  a thread via `on_data`; `ask(kind, payload)` asks the user from that thread.
- `pr7tm/sessions.py` (no Qt): `Session` / `Forward` in <data>/sessions.json (**PR7TM_DATA** in tests), secrets in keyring
  "Paragon PR7-TM" (**PR7TM_MEMORY_KEYRING** in tests), `parse_target` for Quick connect. `pr7tm/profiles.py`: the PC's
  shells (pwsh, powershell, cmd, `wsl -l -q` (UTF-16), Git Bash) + "as administrator" (a new elevated PR7-TM window:
  ConPTY can't host an elevated shell in an unelevated window).
- `pr7tm/termview.py`: `TermView` paints styled runs (wide characters a cell each), cursor blink, selection, Windows
  Terminal's clipboard rules, scrollback bar only when there's scrollback, `resized` / `title_changed` / `closed` /
  `restart` signals; output comes through a queued signal and redraws at most every 16 ms.
- `pr7tm/main_window.py`: `Tab` (a tree of QSplitters of TermViews: `split`, `remove`, `neighbour`), `SessionsPage`, the
  new-tab menu, Quick connect, Find bar, Settings; SSH connects on a thread (`_connect` -> `_connected`), questions via
  `Asker`; own "×" tab buttons (Qt's close button ignores the family style); `_ask` / `answers` / `_say`;
  `answers["elevate"]` stands in for the administrator window.
- `pr7tm/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix): a second start opens a tab in it (`--profile`,
  `--session`, `ssh user@host`); command-line modes never let an error escape; `--selftest OUT.json` (a real shell
  through ConPTY in the real window: a command and its output, a resize, a split; CI on the installed exe).
- Tests: `tests/sshserver.py` is a real paramiko SSH server (password / key, a small shell, direct-tcpip forwarding).
- Installer `installer/pr7tm.iss` (per user, AppId {1B3CDC35-2FB9-49F0-A5F3-7211F808AF28} permanent; desktopicon); CI installs it,
  `tools/verify_install.py installed|uninstalled`. Spec: collect_all("winpty") (ConPTY's DLLs and helpers), file details,
  no UPX, PyInstaller's bootloader built in CI, Defender scan.
- Updates: `pr7tm/updates.py` / `update_ui.py` (the family's files, keep them in step); `family.py`: the family's AppIds
  (PR7-TM included; tests check every name and AppId is there once). `pr7tm/finish.py`: the family's finish.

## The look (family rules)

- Theme is PR7-BK's (OBSIDIAN + AURORA). The terminal itself stays dark in both finishes (as keys and menus do); its
  colours are the family's only (`colours.py`); Inter for the UI, the terminal monospaced (the one exception).
- The PR7-TM mark: PR7 `Logo.cpp` geometry plus T (new, `widgets.T_OUTER`) and M (PR7-WM's); icon "7TM" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (canned shell output through a stand-in backend).

## Rules

- Behaviour questions: do what Windows Terminal does (tabs, panes, keys, clipboard); sessions as PuTTY (host keys).
- Never log, print or send a password, passphrase or key.
- Tests: `python -m pytest` (offscreen) with real shells (a pty here, ConPTY on Windows CI) and the real SSH server in
  tests/sshserver.py. Never the real settings, data folder or Credential Manager (conftest).
- Releases: bump `__version__` in `pr7tm/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed.
