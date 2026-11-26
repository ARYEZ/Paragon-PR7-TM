"""One terminal pane: draws the Terminal's grid and sends keys to its Backend, the way Windows Terminal behaves.

    keys        everything goes to the program (Tab included); Ctrl+C copies when something is selected, else it's
                the program's Ctrl+C; Ctrl+V / Shift+Insert / Ctrl+Shift+V paste; Ctrl+Shift+C copies
    mouse       drag selects, double click selects a word, right click copies the selection or pastes; the wheel
                scrolls the scrollback; Ctrl+wheel and Ctrl+= / Ctrl+- / Ctrl+0 change the font size
    output      comes from the backend's thread through a queued signal, is fed to the Terminal, and the pane redraws
                at most every 16 ms; what the terminal must answer goes straight back to the program
    the end     "[The program ended ...]" is printed in the pane; Enter closes it, R starts it again (`ended`)
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QScrollBar, QWidget

from . import colours, keys
from .screen import Terminal

PAD = 8
KEY_NAMES = {Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right",
             Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "PageUp",
             Qt.Key.Key_PageDown: "PageDown", Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete",
             Qt.Key.Key_Return: "Return", Qt.Key.Key_Enter: "Return", Qt.Key.Key_Backspace: "Backspace",
             Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab", Qt.Key.Key_Escape: "Escape"}
KEY_NAMES.update({getattr(Qt.Key, f"Key_F{i}"): f"F{i}" for i in range(1, 13)})


def mono_font(size: int) -> QFont:
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "monospace"])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setPointSize(size)
    return f


class TermView(QWidget):
    data_arrived = Signal(bytes)
    exited = Signal(str)
    title_changed = Signal(str)
    closed = Signal()             # Enter after the program ended
    restart = Signal()            # R after the program ended
    focused = Signal()
    resized = Signal(int, int)    # columns, rows (the status bar shows them)

    def __init__(self, backend, title: str = "", font_size: int = 11, history: int = 10000, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.base_title = title or backend.description
        self.term = Terminal(120, 34, history)
        self.font_size = font_size
        self.offset = 0                         # lines up into the scrollback
        self.sel_start = self.sel_end = None    # (row in all_rows, column)
        self.hits: list[tuple[int, int]] = []   # Find
        self.hit_len = 0
        self.ended = ""
        self.started = False
        self.blink_on = True
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.bar.valueChanged.connect(self._bar_moved)
        self.data_arrived.connect(self._on_data, Qt.ConnectionType.QueuedConnection)
        self.exited.connect(self._on_exit, Qt.ConnectionType.QueuedConnection)
        backend.on_data = self.data_arrived.emit
        backend.on_exit = self.exited.emit
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.timeout.connect(self._refresh)
        self.blink = QTimer(self)
        self.blink.timeout.connect(self._blink)
        self.blink.start(530)
        self.set_font_size(font_size)

    # ------------------------------------------------------------ metrics
    def set_font_size(self, size: int):
        self.font_size = max(6, min(36, size))
        self.font = mono_font(self.font_size)
        self.bold_font = QFont(self.font)
        self.bold_font.setBold(True)
        fm = QFontMetrics(self.font)
        self.cw = max(1, fm.horizontalAdvance("M"))
        self.lh = max(1, fm.height())
        self.ascent = fm.ascent()
        self._fit()
        self.update()

    def grid_size(self) -> tuple[int, int]:
        w = self.width() - 2 * PAD - self.bar.sizeHint().width()
        h = self.height() - 2 * PAD
        return max(2, w // self.cw), max(1, h // self.lh)

    def _fit(self):
        cols, rows = self.grid_size()
        changed = (cols, rows) != (self.term.cols, self.term.lines)
        self.term.resize(cols, rows)
        if changed:
            self.resized.emit(cols, rows)
        if self.started:
            self.backend.resize(cols, rows)
        self._update_bar()

    def resizeEvent(self, e):
        bw = self.bar.sizeHint().width()
        self.bar.setGeometry(self.width() - bw, 0, bw, self.height())
        self._fit()
        super().resizeEvent(e)

    def start(self):
        """Start the program at the pane's size (after the pane is laid out; the window calls this)."""
        if self.started:
            return
        self._fit()
        self.started = True
        cols, rows = self.grid_size()
        self.backend.start(cols, rows)

    # ------------------------------------------------------------ output
    def _on_data(self, data: bytes):
        before = self.term.scrollback
        for reply in self.term.feed(data):
            self.backend.write(reply)
        if self.offset:                          # reading the scrollback: stay on the same lines
            self.offset = min(self.term.scrollback, self.offset + self.term.scrollback - before)
        if self.term.title:
            self.title_changed.emit(self.term.title)
        if not self.repaint_timer.isActive():
            self.repaint_timer.start(16)

    def _refresh(self):
        self._update_bar()
        self.update()

    def _on_exit(self, message: str):
        self.ended = message
        self.term.feed(f"\r\n\x1b[90m[{message} Enter closes this pane, R starts it again.]\x1b[0m\r\n".encode())
        self._refresh()

    def screen_text(self) -> str:
        return self.term.screen_text()

    # ------------------------------------------------------------ scrollback
    def _update_bar(self):
        self.bar.setVisible(self.term.scrollback > 0)      # nothing to scroll back to: no bar
        self.bar.blockSignals(True)
        self.bar.setRange(0, self.term.scrollback)
        self.bar.setPageStep(self.term.lines)
        self.bar.setValue(self.term.scrollback - self.offset)
        self.bar.blockSignals(False)

    def _bar_moved(self, v: int):
        self.offset = self.term.scrollback - v
        self.update()

    def scroll_lines(self, n: int):
        self.offset = max(0, min(self.term.scrollback, self.offset + n))
        self._update_bar()
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_font_size(self.font_size + (1 if steps > 0 else -1))
            return
        self.scroll_lines(int(steps * 3))

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        bg = QColor(colours.BACKGROUND)
        p.fillRect(self.rect(), bg)
        rows = self.term.rows(self.offset)
        first = len(self.term.all_rows()) - self.offset - self.term.lines   # all_rows index of the top row
        sel = self._selection()
        hit_cells = {(r, c + k) for r, c in self.hits for k in range(self.hit_len)}
        cols = self.term.cols
        for y, row in enumerate(rows):
            top = PAD + y * self.lh
            ri = first + y
            run_text, run_style, run_x = [], None, 0

            def flush():
                if run_style is None:
                    return
                fg, bgc, bold, under = run_style
                rect = QRect(PAD + run_x * self.cw, top, self.cw * len(run_text), self.lh)
                if bgc != colours.BACKGROUND:
                    p.fillRect(rect, QColor(bgc))
                text = "".join(run_text)
                if text.strip():
                    p.setFont(self.bold_font if bold else self.font)
                    p.setPen(QColor(fg))
                    p.drawText(rect.x(), top + self.ascent, text)
                    if under:
                        p.drawLine(rect.x(), top + self.lh - 2, rect.right(), top + self.lh - 2)
            for x in range(cols):
                ch = row[x] if x in row else None
                data = (ch.data or " ") if ch else " "
                fg = colours.resolve(ch.fg, colours.FOREGROUND) if ch else colours.FOREGROUND
                bgc = colours.resolve(ch.bg, colours.BACKGROUND) if ch else colours.BACKGROUND
                if ch and ch.reverse:
                    fg, bgc = bgc, fg
                if sel and self._in_sel(sel, ri, x):
                    bgc = colours.SELECTION
                elif (ri, x) in hit_cells:
                    bgc, fg = colours.PALETTE["brown"], "#000000"
                style = (fg, bgc, bool(ch and ch.bold), bool(ch and ch.underscore))
                wide = len(data) != 1 or ord(data[0]) > 0x2E7F      # wide / combined characters: a cell each
                if style != run_style or wide or (run_text and (len(run_text[-1]) != 1 or ord(run_text[-1][0]) > 0x2E7F)):
                    flush()
                    run_text, run_style, run_x = [], style, x
                run_text.append(data)
            flush()
        # the cursor
        if self.offset == 0 and self.term.cursor_visible and not self.ended:
            cy, cx = self.term.cursor
            r = QRect(PAD + cx * self.cw, PAD + cy * self.lh, self.cw, self.lh)
            if self.hasFocus():
                if self.blink_on:
                    p.fillRect(r, QColor(colours.CURSOR))
                    row = rows[cy] if cy < len(rows) else {}
                    ch = row[cx] if cx in row else None
                    if ch and ch.data.strip():
                        p.setFont(self.font)
                        p.setPen(QColor(colours.BACKGROUND))
                        p.drawText(r.x(), r.y() + self.ascent, ch.data)
            else:
                p.setPen(QPen(QColor(colours.CURSOR), 1))
                p.drawRect(r.adjusted(0, 0, -1, -1))

    def _blink(self):
        if self.hasFocus():
            self.blink_on = not self.blink_on
            self.update()

    # ------------------------------------------------------------ selection
    def _cell(self, pos: QPoint) -> tuple[int, int]:
        col = max(0, min(self.term.cols - 1, (pos.x() - PAD) // self.cw))
        row = max(0, min(self.term.lines - 1, (pos.y() - PAD) // self.lh))
        first = len(self.term.all_rows()) - self.offset - self.term.lines
        return first + row, col

    def _selection(self):
        if self.sel_start is None or self.sel_end is None or self.sel_start == self.sel_end:
            return None
        return tuple(sorted([self.sel_start, self.sel_end]))

    @staticmethod
    def _in_sel(sel, r, c) -> bool:
        (r0, c0), (r1, c1) = sel
        return (r0 < r < r1) or (r == r0 and r0 != r1 and c >= c0) or (r == r1 and r0 != r1 and c <= c1) or \
            (r0 == r1 == r and c0 <= c <= c1)

    def selected_text(self) -> str:
        sel = self._selection()
        return self.term.text(*sel) if sel else ""

    def select_all(self):
        n = len(self.term.all_rows())
        self.sel_start, self.sel_end = (0, 0), (n - 1, self.term.cols - 1)
        self.update()

    def clear_selection(self):
        self.sel_start = self.sel_end = None
        self.update()

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MouseButton.LeftButton:
            self.sel_start = self.sel_end = self._cell(e.position().toPoint())
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            if self._selection():
                self.copy()
                self.clear_selection()
            else:
                self.paste()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.sel_start is not None:
            self.sel_end = self._cell(e.position().toPoint())
            self.update()

    def mouseDoubleClickEvent(self, e):
        r, c = self._cell(e.position().toPoint())
        line = self.term.row_text(self.term.all_rows()[r])
        a = b = c
        word = lambda ch: ch.isalnum() or ch in "-_./\\:~@"     # noqa: E731 - paths and URLs count as one word
        while a > 0 and word(line[a - 1]):
            a -= 1
        while b < len(line) - 1 and word(line[b + 1]):
            b += 1
        self.sel_start, self.sel_end = (r, a), (r, b)
        self.update()

    # ------------------------------------------------------------ clipboard
    def copy(self) -> bool:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)
            return True
        return False

    def paste(self, text: str | None = None):
        text = QApplication.clipboard().text() if text is None else text
        if text:
            self.offset = 0
            self.backend.write(keys.paste(text, self.term.bracketed_paste))

    # ------------------------------------------------------------ keys
    def focusNextPrevChild(self, _next: bool) -> bool:
        return False                             # Tab belongs to the program

    def focusInEvent(self, e):
        self.blink_on = True
        self.focused.emit()
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    def event(self, e):
        if e.type() == e.Type.ShortcutOverride:   # these belong to the terminal, not to the window's shortcuts
            k, m = e.key(), e.modifiers()
            ctrl = bool(m & Qt.KeyboardModifier.ControlModifier)
            shift = bool(m & Qt.KeyboardModifier.ShiftModifier)
            if ctrl and not shift and k in (Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_A):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        k, m = e.key(), e.modifiers()
        ctrl = bool(m & Qt.KeyboardModifier.ControlModifier)
        shift = bool(m & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(m & Qt.KeyboardModifier.AltModifier)
        if self.ended:
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.closed.emit()
            elif k == Qt.Key.Key_R:
                self.restart.emit()
            return
        if ctrl and shift and k == Qt.Key.Key_C or (ctrl and not shift and k == Qt.Key.Key_C and self._selection()):
            self.copy()
            self.clear_selection()
            return
        if (ctrl and k == Qt.Key.Key_V) or (shift and k == Qt.Key.Key_Insert):
            self.paste()
            return
        if ctrl and k in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            self.set_font_size(self.font_size + 1)
            return
        if ctrl and k == Qt.Key.Key_Minus:
            self.set_font_size(self.font_size - 1)
            return
        if ctrl and k == Qt.Key.Key_0:
            self.set_font_size(11)
            return
        if shift and k in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self.scroll_lines(self.term.lines if k == Qt.Key.Key_PageUp else -self.term.lines)
            return
        name = KEY_NAMES.get(k, "")
        text = e.text()
        if ctrl and not name and k < 0x80 and chr(k).isprintable():
            text = chr(k).lower()               # Qt gives control characters (or nothing) as text with Ctrl held
        data = keys.encode(name, text, ctrl=ctrl, alt=alt, shift=shift or k == Qt.Key.Key_Backtab,
                           app_cursor=self.term.app_cursor)
        if data:
            if self.offset:
                self.offset = 0
                self._update_bar()
            self.clear_selection() if self._selection() else None
            self.blink_on = True
            self.backend.write(data)

    def inputMethodEvent(self, e):
        if e.commitString():
            self.backend.write(e.commitString().encode("utf-8"))

    def close_backend(self):
        self.backend.close()
