"""Curses front end: rendering and input only; all behaviour lives in actions.py."""

import curses
import locale
import os
import re
import shutil
import signal
import sys
import tempfile
import textwrap
from pathlib import Path

from seminar2.live import hub
from seminar2.text import fold
from seminar2.tui import actions
from seminar2.tui.actions import truncation_note

MIN_W, MIN_H = 80, 24
SPINNER = "|/-\\"
TITLE = "SEMINAR 2 // AI COURSE UET // CONTROL CONSOLE"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b.")
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ESC, ENTER, TAB, BACKSPACE, CTRL_U = 27, 10, 9, 127, 21
BACKSPACES = (curses.KEY_BACKSPACE, BACKSPACE, 8)

HELP = [
    "KEYS",
    "",
    "Menu     up/down or j/k   move          Enter   open options form",
    "         PgUp/PgDn g/G    jump          /       filter the list",
    "         ?                this help     q       quit",
    "Form     up/down/Tab      change field  left/right  change value",
    "         type             edit number/text   Space  toggle yes/no",
    "         Enter            run           Esc     back",
    "Output   up/down PgUp/PgDn g/G  scroll  Esc/q   back (cancels a running job)",
    "",
    "Background processes started here are stopped when you quit.",
    "Press any key to close.",
]


def clean(line):
    """Drop ANSI escapes and control characters so subprocess output can't garble curses."""
    return CTRL.sub("", ANSI.sub("", line).expandtabs(4))


def wrap(lines, width):
    out = []
    for line in lines:
        out += textwrap.wrap(line, max(width, 10), drop_whitespace=False, replace_whitespace=False,
                             subsequent_indent="      " if line.startswith(" ") else "") or [""]
    return out


class Form:
    """Raw field state: choice -> index, bool -> bool, int/text -> the typed string."""

    def __init__(self, action):
        self.action = action
        self.focus = 0
        self.error = ""
        self.raw = []
        for o in action.options:
            if o.kind == "choice":
                self.raw.append(o.choices.index(o.default) if o.default in o.choices else 0)
            elif o.kind == "bool":
                self.raw.append(bool(o.default))
            else:
                self.raw.append("" if o.default is None else str(o.default))

    def values(self):
        return {o.name: (o.choices[v] if o.kind == "choice" else v) for o, v in zip(self.action.options, self.raw)}

    def display(self, i, width=None):
        """Text of field i; `width` caps typed text, keeping its end (the cursor) visible."""
        o, v = self.action.options[i], self.raw[i]
        if o.kind == "choice":
            return f"<  {o.choices[v]}  >"
        if o.kind == "bool":
            return "[x] yes" if v else "[ ] no"
        if width is not None and len(v) > width:
            v = "…" + v[-(width - 1):] if width > 1 else v[-1:]
        return f"[ {v}{'_' if i == self.focus else ' '}]"

    def step(self, delta):
        o, v = self.action.options[self.focus], self.raw[self.focus]
        if o.kind == "choice":
            self.raw[self.focus] = (v + delta) % len(o.choices)
        elif o.kind == "bool":
            self.raw[self.focus] = not v
        elif o.kind == "int":
            try:
                n = int(v) + delta
            except ValueError:
                n = int(o.default) if o.default is not None else (o.min or 0)
            if o.min is not None:
                n = max(n, o.min)
            if o.max is not None:
                n = min(n, o.max)
            self.raw[self.focus] = str(n)

    def type(self, ch):
        o, v = self.action.options[self.focus], self.raw[self.focus]
        if o.kind == "bool" and ch == " ":
            self.raw[self.focus] = not v
        elif o.kind == "int" and (ch.isdigit() or (ch == "-" and not v)):
            self.raw[self.focus] = v + ch
        elif o.kind == "text":
            self.raw[self.focus] = v + ch

    def backspace(self, clear=False):
        if self.action.options[self.focus].kind in ("int", "text"):
            self.raw[self.focus] = "" if clear else self.raw[self.focus][:-1]


class Pager:
    """Scrollable output; wrapped lines are cached so a frame never re-wraps old output."""

    def __init__(self, title, result=None, job=None):
        self.title, self.result, self.job = title, result, job
        self.top = 0
        self.follow = job is not None     # tail a running job until the user scrolls
        self._width = None
        self._start = 0                   # absolute index of the first cached raw line
        self._chunks = []                 # wrapped pieces per raw line
        self._flat = (None, [])
        self._final = None                # ((width, id(result)), wrapped lines)

    @property
    def running(self):
        return self.job is not None and not self.job.done

    def final(self):
        if self.result is None:
            self.result = self.job.result()
        return self.result

    def lines(self, width):
        if not self.running:
            result = self.final()
            key = (width, id(result))
            if self._final is None or self._final[0] != key:
                self._final = (key, wrap([clean(r) for r in result.text.splitlines()], width))
            return self._final[1]
        raw, dropped = self.job.snapshot()
        if width != self._width:
            self._width, self._start, self._chunks = width, dropped, []
        del self._chunks[:max(dropped - self._start, 0)]     # lines that fell off the job's buffer
        self._start = max(self._start, dropped)
        done = len(self._chunks)
        self._chunks += [wrap([clean(r)], width) for r in raw[done:]]
        key = (width, self._start, len(self._chunks))
        if self._flat[0] != key:
            self._flat = (key, [piece for chunk in self._chunks for piece in chunk])
        head = [truncation_note(dropped)] if dropped else []
        return head + self._flat[1]

    def move(self, delta, total, body_h):
        """Scroll by `delta` lines (clamped); re-enables follow when the end is reached."""
        max_top = max(total - body_h, 0)
        self.top = max(0, min(self.top + delta, max_top))
        self.follow = self.top >= max_top

    def view_top(self, total, body_h):
        """First visible line for this frame (the tail while following)."""
        max_top = max(total - body_h, 0)
        self.top = max_top if self.follow else max(0, min(self.top, max_top))
        return self.top


class App:
    accent = curses.A_BOLD

    def __init__(self, scr):
        self.scr = scr
        self.acts = actions.registry()
        self.screen = "menu"
        self.sel = 0
        self.top = 0
        self.filter = ""
        self.filtering = False
        self.help = False
        self.form = None
        self.pager = None
        self.tick = 0
        self.init_colors()

    def init_colors(self):
        """Green-on-black; plain bold/reverse when the terminal has no colours."""
        self.primary, self.dim, self.sel_attr, self.err = curses.A_BOLD, curses.A_NORMAL, curses.A_REVERSE, curses.A_BOLD
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
            curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
        except curses.error:
            return
        self.primary = curses.color_pair(1) | curses.A_BOLD
        self.dim = curses.color_pair(1)
        self.sel_attr = curses.color_pair(2) | curses.A_BOLD
        self.err = curses.color_pair(3) | curses.A_BOLD
        self.accent = curses.color_pair(4) | curses.A_BOLD
        self.scr.bkgd(" ", curses.color_pair(1))

    # --- drawing helpers ---------------------------------------------------------

    def size(self):
        return self.scr.getmaxyx()

    def put(self, y, x, text, attr=None):
        h, w = self.size()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        try:
            self.scr.addstr(y, x, text[: w - x], self.dim if attr is None else attr)
        except curses.error:
            pass    # writing the bottom-right cell raises although the text is drawn

    def header(self, right=""):
        _, w = self.size()
        self.put(0, 1, TITLE, self.primary)
        if right:
            self.put(0, max(w - len(right) - 1, len(TITLE) + 3), right, self.accent)
        self.put(1, 0, "─" * w)

    def footer(self, keys):
        h, w = self.size()
        self.put(h - 3, 0, "─" * w)
        url, n = hub.url(), len(actions.PROCESSES.running())
        self.put(h - 2, 1, f"live viewer: {url or 'off'}   background processes: {n}")
        self.put(h - 1, 1, keys, self.primary)

    # --- menu --------------------------------------------------------------------

    def visible(self):
        q = fold(self.filter)
        return [a for a in self.acts if not q or q in fold(f"{a.title} {a.group} {a.key} {a.description}")]

    def draw_menu(self):
        h, w = self.size()
        self.header()
        vis = self.visible()
        self.sel = min(self.sel, max(len(vis) - 1, 0))
        rows, group = [], None
        for a in vis:
            if a.group != group:
                group = a.group
                rows.append(("hdr", a))
            rows.append(("act", a))
        lw, body_h = min(36, w // 2), h - 5
        sel_row = next((i for i, (k, a) in enumerate(rows) if k == "act" and a is vis[self.sel]), 0) if vis else 0
        if sel_row < self.top:
            self.top = sel_row - 1 if sel_row > 0 and rows[sel_row - 1][0] == "hdr" else sel_row
        elif sel_row >= self.top + body_h:
            self.top = sel_row - body_h + 1
        self.top = max(0, min(self.top, max(len(rows) - body_h, 0)))
        for i in range(body_h):
            self.put(2 + i, lw, "│")
            if self.top + i >= len(rows):
                continue
            kind, a = rows[self.top + i]
            if kind == "hdr":
                self.put(2 + i, 1, f"[ {a.group.upper()} ]", self.primary)
            else:
                self.put(2 + i, 0, f"  {a.title}".ljust(lw)[:lw], self.sel_attr if a is vis[self.sel] else self.dim)
        if vis:
            self.draw_description(vis[self.sel], lw + 2, w - lw - 3, body_h)
        else:
            self.put(2, 2, "No actions match the filter.", self.err)
        keys = "up/down move  Enter options  / filter  ? help  q quit"
        if self.filtering:
            keys = f"filter> {self.filter}_   (Enter accept, Esc clear)"
        elif self.filter:
            keys += f"   [filter: {self.filter}]"
        self.footer(keys)

    def draw_description(self, a, x, width, height):
        lines = [a.title.upper(), f"group: {a.group}", ""] + a.description.splitlines()
        if a.options:
            lines += ["", "Options:"] + [
                f"  {o.label}" + (f" (default {o.default})" if o.default not in (None, "", False) else "")
                for o in a.options]
        else:
            lines += ["", "No options."]
        for i, line in enumerate(wrap(lines, width)[:height]):
            self.put(2 + i, x, line, self.primary if i == 0 else self.dim)

    def key_menu(self, key):
        if self.filtering:
            if key == ESC:
                self.filter, self.filtering = "", False
            elif key == ENTER:
                self.filtering = False
            elif key in BACKSPACES:
                self.filter = self.filter[:-1]
            elif key == CTRL_U:
                self.filter = ""
            elif isinstance(key, str):
                self.filter += key
            if key not in (curses.KEY_UP, curses.KEY_DOWN):
                self.sel = 0
                return None
        vis = self.visible()
        n = len(vis)
        if key in (curses.KEY_DOWN, "j"):
            self.sel = min(self.sel + 1, n - 1)
        elif key in (curses.KEY_UP, "k"):
            self.sel = max(self.sel - 1, 0)
        elif key == curses.KEY_NPAGE:
            self.sel = min(self.sel + 10, n - 1)
        elif key == curses.KEY_PPAGE:
            self.sel = max(self.sel - 10, 0)
        elif key in ("g", curses.KEY_HOME):
            self.sel = 0
        elif key in ("G", curses.KEY_END):
            self.sel = max(n - 1, 0)
        elif key == "/":
            self.filtering = True
        elif key == "?":
            self.help = True
        elif key == ESC and self.filter:
            self.filter, self.sel = "", 0
        elif key in (ENTER, curses.KEY_ENTER) and vis:
            self.form = Form(vis[self.sel])
            self.screen = "form"
        elif key == "q":
            return "quit"
        return None

    # --- form --------------------------------------------------------------------

    def draw_form(self):
        h, w = self.size()
        f = self.form
        self.header()
        self.put(2, 1, f"{f.action.title.upper()}  ({f.action.group})", self.primary)
        y = 4
        desc = wrap(f.action.description.splitlines(), w - 4)
        if len(desc) > 5:
            desc = desc[:4] + [desc[4][: max(w - 8, 1)].rstrip() + " …"]
        for line in desc:
            self.put(y, 2, line)
            y += 1
        y += 1
        if not f.action.options:
            self.put(y, 2, "No options. Press Enter to run.")
        for i, o in enumerate(f.action.options):
            hint = f"  {o.hint()}" if o.hint() else ""
            room = max(w - 38 - len(hint) - 6, 8)     # columns left for typed text
            row = f" {o.label}{' *' if o.required else ''}".ljust(38) + f"{f.display(i, room)}{hint}"
            self.put(y + i, 0, row.ljust(w)[:w], self.sel_attr if i == f.focus else self.dim)
        y += max(len(f.action.options), 1) + 1
        if f.error:
            for line in wrap(f.error.splitlines(), w - 4):
                self.put(y, 2, line, self.err)
                y += 1
        self.footer("up/down field  left/right change  type edit  Space toggle  Enter run  Esc back")

    def key_form(self, key):
        f = self.form
        n = len(f.action.options)
        if key == ESC:
            self.screen = "menu"
        elif key in (curses.KEY_DOWN, TAB) and n:
            f.focus = (f.focus + 1) % n
        elif key in (curses.KEY_UP, curses.KEY_BTAB) and n:
            f.focus = (f.focus - 1) % n
        elif key == curses.KEY_RIGHT and n:
            f.step(1)
        elif key == curses.KEY_LEFT and n:
            f.step(-1)
        elif key in BACKSPACES and n:
            f.backspace()
        elif key == CTRL_U and n:
            f.backspace(clear=True)
        elif key in (ENTER, curses.KEY_ENTER):
            self.run_form()
        elif isinstance(key, str) and n:
            f.type(key)

    def run_form(self):
        f = self.form
        out = actions.execute(f.action, f.values())
        if isinstance(out, actions.CaptureJob):
            self.pager = Pager(f.action.title, job=out)
        elif not out.ok and out.data is None:     # validation / start-up failure: fix it on the form
            f.error = out.text
            return
        else:
            f.error = ""
            self.pager = Pager(f.action.title, result=out)
        self.screen = "pager"

    # --- pager -------------------------------------------------------------------

    def draw_pager(self):
        h, w = self.size()
        p = self.pager
        if p.running:
            state, attr = f"RUNNING {SPINNER[self.tick % 4]} {p.job.elapsed:.0f}s", self.accent
        else:
            state, attr = ("OK", self.primary) if p.final().ok else ("FAILED", self.err)
        self.header(state)
        self.put(2, 1, p.title.upper(), attr)
        body_h = h - 6
        lines = p.lines(w - 3) or (["running…"] if p.running else [])
        p.view_top(len(lines), body_h)
        for i, line in enumerate(lines[p.top:p.top + body_h]):
            bad = line.startswith("error") or "Traceback" in line
            self.put(3 + i, 2, line, self.err if bad else self.dim)
        shown = min(p.top + body_h, len(lines))
        self.footer("up/down PgUp/PgDn g/G scroll  Esc back" + (" (cancels job)" if p.running else "")
                    + f"   lines {p.top + 1 if lines else 0}-{shown}/{len(lines)}")

    def key_pager(self, key):
        p = self.pager
        h, w = self.size()
        page = max(h - 7, 1)
        if key in (ESC, "q", curses.KEY_LEFT):
            if p.running:
                p.job.cancel()
            self.screen = "form" if self.form.action.options else "menu"
            return
        total, body_h = len(p.lines(w - 3)), h - 6
        if key in (curses.KEY_DOWN, "j"):
            p.move(1, total, body_h)
        elif key in (curses.KEY_UP, "k"):
            p.move(-1, total, body_h)
        elif key in (curses.KEY_NPAGE, " "):
            p.move(page, total, body_h)
        elif key in (curses.KEY_PPAGE, "b"):
            p.move(-page, total, body_h)
        elif key in ("g", curses.KEY_HOME):
            p.move(-total, total, body_h)
        elif key in ("G", curses.KEY_END):
            p.move(total, total, body_h)

    # --- main loop ---------------------------------------------------------------

    def draw_help(self):
        h, w = self.size()
        bw = min(max(len(x) for x in HELP) + 4, w)
        x0, y0 = max((w - bw) // 2, 0), max((h - len(HELP) - 2) // 2, 0)
        for i in range(len(HELP) + 2):
            self.put(y0 + i, x0, " " * bw)
        for i, line in enumerate(HELP):
            self.put(y0 + 1 + i, x0 + 2, line, self.primary if i == 0 else self.dim)

    def draw(self):
        h, w = self.size()
        self.scr.erase()
        if w < MIN_W or h < MIN_H:
            self.put(0, 0, f"Terminal too small: {w}x{h}", self.err)
            self.put(1, 0, f"Need at least {MIN_W}x{MIN_H}. Resize, or press q to quit.")
        else:
            getattr(self, f"draw_{self.screen}")()
            if self.help:
                self.draw_help()
        self.scr.refresh()

    def read_key(self):
        """int for special/control keys, str for printable characters, None on timeout."""
        try:
            ch = self.scr.get_wch()
        except curses.error:
            return None
        if isinstance(ch, str) and len(ch) == 1 and (ord(ch) < 32 or ord(ch) == 127):
            return ENTER if ch == "\r" else ord(ch)
        return ch

    def run(self):
        self.scr.timeout(100)
        while True:
            self.draw()
            self.tick += 1
            key = self.read_key()
            if key is None or key == curses.KEY_RESIZE:
                continue
            h, w = self.size()
            if w < MIN_W or h < MIN_H:
                if key == "q":
                    return
            elif self.help:
                self.help = False
            elif getattr(self, f"key_{self.screen}")(key) == "quit":
                return


def _quit_on(signum, frame):
    raise SystemExit(128 + signum)


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("seminar2.tui needs an interactive terminal.", file=sys.stderr)
        return 2
    os.environ.setdefault("ESCDELAY", "50")
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    # Closing the terminal (SIGHUP) or `kill` (SIGTERM) must still run the cleanup below.
    previous = {}
    log_dir = saved_fd = None
    interrupted = False
    stopped, viewer, kept = [], None, False
    try:
        previous = {sig: signal.signal(sig, _quit_on) for sig in (signal.SIGTERM, signal.SIGHUP)}
        # Hub handler threads write tracebacks to fd 2; keep them out of the curses screen.
        log_dir = Path(tempfile.mkdtemp(prefix="seminar2-tui-stderr-"))
        log = log_dir / "stderr.log"
        sys.stderr.flush()
        saved_fd = os.dup(2)
        log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.dup2(log_fd, 2)
        finally:
            os.close(log_fd)
        try:
            curses.wrapper(lambda scr: App(scr).run())
        except KeyboardInterrupt:
            interrupted = True
        finally:
            try:
                stopped = actions.PROCESSES.terminate_all()
                viewer = hub.url()
                hub.stop()
            finally:
                sys.stderr.flush()
    finally:
        if saved_fd is not None:
            os.dup2(saved_fd, 2)
            os.close(saved_fd)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if log_dir is not None:
            kept = log.stat().st_size > 0 if log.exists() else False
            if not kept:
                shutil.rmtree(log_dir, ignore_errors=True)
        if stopped:
            print("Stopped background processes: " + ", ".join(stopped))
        if viewer:
            print(f"Stopped the live viewer ({viewer}).")
        if kept:
            print(f"Errors were logged to {log}")
    return 130 if interrupted else 0
