"""The terminal itself (no Qt): what a program prints, kept as a grid of cells with scrollback, by **pyte** (a full
VT100 / xterm emulator in Python). PR7-TM adds what a terminal window needs around it:

    feed(bytes)        output from the shell or SSH (UTF-8 split across reads is fine: pyte decodes incrementally)
    replies            what the terminal must answer (cursor position, "what are you": DSR / DA), sent back to the
                       program by the owner (ConPTY asks for the cursor position when a shell starts)
    rows(offset)       the visible rows, `offset` lines up into the scrollback
    text(a, b)         the selected text (rows joined with line breaks, trailing spaces trimmed, as Windows Terminal)
    find(word)         every (row, column) where it appears, scrollback included
    app_cursor / bracketed_paste   the modes that change what keys and pastes send
"""

from __future__ import annotations

import pyte
from pyte import modes

APP_CURSOR = 1 << 5                           # DECCKM: arrows send ESC O A instead of ESC [ A (pyte keeps private modes shifted by 5)
BRACKETED_PASTE = 2004 << 5                   # pyte keeps private modes shifted by 5
CURSOR_VISIBLE = modes.DECTCEM


class _Screen(pyte.HistoryScreen):
    def __init__(self, owner, cols, rows, history):
        super().__init__(cols, rows, history=history, ratio=0.5)
        self.owner = owner

    def write_process_input(self, data: str):
        self.owner.replies.append(data.encode("utf-8"))

    def set_title(self, param):
        super().set_title(param)
        self.owner.title = self.title

    def bell(self, *args):
        self.owner.bells += 1


class Terminal:
    def __init__(self, cols: int = 120, rows: int = 34, history: int = 10000):
        self.replies: list[bytes] = []
        self.title = ""
        self.bells = 0
        self.screen = _Screen(self, cols, rows, history)
        self.stream = pyte.ByteStream(self.screen)

    # ------------------------------------------------------------ feeding
    def feed(self, data: bytes) -> list[bytes]:
        """Show program output; returns (and clears) what must be answered."""
        self.stream.feed(data)
        out, self.replies = self.replies, []
        return out

    def resize(self, cols: int, rows: int):
        """Windows Terminal's way: when the pane gets shorter, only as many top lines as needed to keep the cursor
        in view go up into the scrollback (pyte alone would throw the top lines away)."""
        cols, rows = max(2, cols), max(1, rows)
        sc = self.screen
        if (cols, rows) == (sc.columns, sc.lines):
            return
        if rows < sc.lines:
            shift = max(0, sc.cursor.y + 1 - rows)
            old = {y: sc.buffer[y] for y in range(sc.lines)}
            for y in range(shift):
                sc.history.top.append(old[y])
            sc.buffer.clear()
            for y in range(shift, shift + rows):
                sc.buffer[y - shift] = old[y]
            sc.cursor.y -= shift
            sc.lines = rows
            sc.set_margins()
            sc.dirty.update(range(rows))
        if (cols, rows) != (sc.columns, sc.lines):
            sc.resize(rows, cols)

    @property
    def cols(self) -> int:
        return self.screen.columns

    @property
    def lines(self) -> int:
        return self.screen.lines

    # ------------------------------------------------------------ modes
    @property
    def app_cursor(self) -> bool:
        return APP_CURSOR in self.screen.mode

    @property
    def bracketed_paste(self) -> bool:
        return BRACKETED_PASTE in self.screen.mode

    @property
    def cursor_visible(self) -> bool:
        return CURSOR_VISIBLE in self.screen.mode

    @property
    def cursor(self) -> tuple[int, int]:
        return self.screen.cursor.y, self.screen.cursor.x

    # ------------------------------------------------------------ what's shown
    @property
    def scrollback(self) -> int:
        return len(self.screen.history.top)

    def all_rows(self) -> list:
        """Scrollback then the screen, each a row of pyte cells (a dict: column -> Char)."""
        top = list(self.screen.history.top)
        return top + [self.screen.buffer[y] for y in range(self.screen.lines)]

    def rows(self, offset: int = 0) -> list:
        """The visible rows, `offset` lines up into the scrollback (0 = the live screen)."""
        offset = max(0, min(offset, self.scrollback))
        rows = self.all_rows()
        end = len(rows) - offset
        return rows[end - self.screen.lines:end]

    def row_text(self, row, cols: int | None = None) -> str:
        cols = cols or self.cols
        return "".join(row[x].data if x in row else " " for x in range(cols))

    def screen_text(self) -> str:
        return "\n".join(self.row_text(r).rstrip() for r in self.rows())

    def text(self, start: tuple[int, int], end: tuple[int, int]) -> str:
        """The text between two (row, column) points in all_rows() order, both ends included."""
        (r0, c0), (r1, c1) = sorted([start, end])
        rows = self.all_rows()
        out = []
        for r in range(r0, min(r1, len(rows) - 1) + 1):
            line = self.row_text(rows[r])
            a = c0 if r == r0 else 0
            b = c1 + 1 if r == r1 else len(line)
            out.append(line[a:b].rstrip())
        return "\r\n".join(out)

    def find(self, word: str) -> list[tuple[int, int]]:
        if not word:
            return []
        w = word.casefold()
        hits = []
        for r, row in enumerate(self.all_rows()):
            line = self.row_text(row).casefold()
            i = line.find(w)
            while i >= 0:
                hits.append((r, i))
                i = line.find(w, i + 1)
        return hits
