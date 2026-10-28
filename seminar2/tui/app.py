"""Textual front end: rendering and input only; all behaviour lives in actions.py."""

import asyncio
import contextlib
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import traceback
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.json import JSON
from rich.rule import Rule
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    Static,
    Switch,
)
from textual.widgets.option_list import Option as ListOption

from seminar2.live import hub
from seminar2.text import fold
from seminar2.tui import actions

TITLE = "Seminar 2 · AI Course UET"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b.")
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
OUTPUT_LINES = 20000
WINDOWS = sys.platform == "win32"
# App-level bindings that must not fire (behind the user's back) while a modal screen is open.
MODAL_BLOCKED = frozenset({"run", "escape", "focus_filter", "clear_output"})

MATRIX = Theme(
    name="matrix",
    primary="#00FF41",
    secondary="#00B82E",
    accent="#00FF41",
    warning="#FFB000",
    error="#FF4D4D",
    success="#00FF41",
    foreground="#C6FFD3",
    background="#000000",
    surface="#030803",
    panel="#0A180A",
    dark=True,
)

# (key, what it does): shown in the help screen and documented in the README.
KEYS = [
    ("Up / Down", "select an action in the list"),
    ("Enter", "open its form (runs at once if it has none)"),
    ("Tab / Shift+Tab", "move between filter, list, form fields and Run"),
    ("Ctrl+R", "run the selected action (from anywhere)"),
    ("Esc", "cancel the running job; otherwise back to the list"),
    ("/", "focus the filter box (type to narrow the list)"),
    ("Ctrl+L", "clear the output"),
    ("? / F1", "this help (F1 also works while typing)"),
    ("Ctrl+P", "command palette (switch theme, ...)"),
    ("q", "quit (not while typing in a text field)"),
    ("Ctrl+Q / Ctrl+C", "quit from anywhere"),
]


def clean(line):
    """Drop ANSI escapes and control characters so subprocess output can't garble the screen."""
    return CTRL.sub("", ANSI.sub("", line).expandtabs(4))


def matches(action, query):
    """Case/accent-insensitive filter over everything the list shows or hides about an action."""
    q = fold(query.strip())
    return not q or q in fold(f"{action.title} {action.group} {action.key} {action.description}")


class HelpScreen(ModalScreen):
    BINDINGS: ClassVar = [Binding(key, "close", show=False) for key in ("escape", "q", "question_mark", "enter", "f1")]

    def compose(self):
        with Vertical(id="help"):
            yield Static(Text("Keys", style="bold"), id="help-title")
            for key, what in KEYS:
                yield Static(Text.assemble((f"{key:<17}", "bold"), what), classes="help-row")
            yield Static("Mouse works everywhere. Background processes started here stop when you quit.",
                         id="help-note")
            yield Static("Press Esc to close.", id="help-note2")

    def action_close(self):
        self.dismiss()


class FilterInput(Input):
    BINDINGS: ClassVar = [Binding("down", "to_list", show=False)]

    def action_to_list(self):
        self.app.query_one("#actions").focus()


class ActionForm(Vertical):
    """The options form of one action: a widget per Option with an inline error line."""

    def __init__(self, action):
        super().__init__()
        self.action = action
        self.fields = {}      # option name -> (Option, widget, error Static)

    def compose(self):
        if not self.action.options:
            yield Static("No options. Press Run (Ctrl+R).", classes="muted")
        for opt in self.action.options:
            hint = f"  ({opt.hint()})" if opt.hint() else ""
            yield Label(Text(f"{opt.label}{' *' if opt.required else ''}{hint}"), classes="field-label")
            widget = self._widget(opt)
            error = Static("", classes="field-error")
            error.display = False
            self.fields[opt.name] = (opt, widget, error)
            yield widget
            yield error

    @staticmethod
    def _widget(opt):
        if opt.kind == "choice":
            value = opt.default if opt.default in opt.choices else opt.choices[0]
            return Select([(str(c), c) for c in opt.choices], value=value, allow_blank=False)
        if opt.kind == "bool":
            return Switch(value=bool(opt.default))
        return Input(value="" if opt.default is None else str(opt.default), placeholder=opt.hint())

    @staticmethod
    def _raw(opt, widget):
        return widget.value

    def raw(self):
        return {name: self._raw(opt, w) for name, (opt, w, _) in self.fields.items()}

    def check(self, name):
        """Validate one field and show/clear its inline message. Returns True when valid."""
        opt, widget, error = self.fields[name]
        _, errors = actions.coerce((opt,), {name: self._raw(opt, widget)})
        message = errors[0].removeprefix(f"{opt.label}: ") if errors else ""
        error.update(Text(message))
        error.display = bool(message)
        return not message

    def validate(self):
        """Check every field; focus the first bad one. Returns True when all are valid."""
        results = {name: self.check(name) for name in self.fields}
        bad = next((n for n, ok in results.items() if not ok), None)
        if bad is not None:
            self.fields[bad][1].focus()
        return bad is None

    def focus_first(self):
        if self.fields:
            next(iter(self.fields.values()))[1].focus()

    @on(Input.Changed)
    def _changed(self, event):
        for name, (_, widget, _) in self.fields.items():
            if widget is event.input:
                self.check(name)
                return


class TuiApp(App):
    TITLE = TITLE
    CSS_PATH = str(Path(__file__).with_name("app.tcss"))     # absolute: also works for subclasses elsewhere
    BINDINGS: ClassVar = [
        Binding("ctrl+r", "run", "Run", priority=True),
        Binding("escape", "escape", "Back / cancel"),
        Binding("slash", "focus_filter", "Filter"),
        Binding("ctrl+l", "clear_output", "Clear"),
        Binding("question_mark", "help", "Help"),
        Binding("f1", "help", "Help", show=False, priority=True),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, manager=None):
        super().__init__()
        self.manager = manager or actions.PROCESSES
        self.acts = actions.registry()
        self.by_key = {a.key: a for a in self.acts}
        self.action = None
        self.form = None
        self.notices = []
        self._busy = False
        self._job = None
        self.last_job = None
        self._seen = 0
        self._t0 = time.monotonic()
        self._title = ""
        self._frame = 0
        self._status = None            # (ok, text) of the last finished run
        self._cleaned = False
        self._quitting = False
        self._code = 0
        self._run_line = 0
        self._loop = None
        self._runstatus = self._statusbar = self._outlog = None     # set in on_mount

    # --- layout ------------------------------------------------------------------

    def check_action(self, action, parameters):
        if action in MODAL_BLOCKED and isinstance(self.screen, ModalScreen):
            return False
        return True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield FilterInput(placeholder="/ filter actions", id="filter")
                yield OptionList(id="actions")
            with Vertical(id="main"):
                with VerticalScroll(id="detail"):
                    yield Static(id="title")
                    yield Static(id="desc")
                    yield Vertical(id="form-host")
                    yield Button("Run  (Ctrl+R)", id="run", variant="success")
                with Vertical(id="output-box"):
                    yield Static(id="runstatus")
                    yield RichLog(id="output", wrap=True, markup=False, highlight=False, max_lines=OUTPUT_LINES)
        yield Static(id="statusbar")
        yield Footer()

    async def on_mount(self):
        self._loop = asyncio.get_running_loop()
        self._runstatus = self.query_one("#runstatus", Static)
        self._statusbar = self.query_one("#statusbar", Static)
        self._outlog = self.query_one("#output", RichLog)
        self.register_theme(MATRIX)
        self.theme = "matrix"
        self.query_one("#output-box").border_title = "Output"
        self.query_one("#sidebar").border_title = "Actions"
        await self.populate("")
        self.query_one("#actions").focus()
        self.set_interval(0.1, self._tick)

    def on_unmount(self):
        self.cleanup()

    # --- action list -------------------------------------------------------------

    async def populate(self, query):
        """Rebuild the grouped list for `query`, keeping the current action selected when it still matches."""
        listing = self.query_one("#actions", OptionList)
        visible = [a for a in self.acts if matches(a, query)]
        listing.clear_options()
        if not visible:
            listing.add_option(ListOption("No actions match the filter", disabled=True))
            await self.show_action(None)
            return
        rows, group, target = [], None, 0
        for a in visible:
            if a.group != group:
                group = a.group
                rows.append(ListOption(Text(group.upper(), style="bold"), disabled=True))
            if a is self.action:
                target = len(rows)
            rows.append(ListOption(Text("  " + a.title), id=a.key))
        if self.action not in visible:
            target = 1
        listing.add_options(rows)
        listing.highlighted = target

    async def show_action(self, action):
        if action is self.action and self.form is not None:
            return
        self.action = action
        host = self.query_one("#form-host")
        await host.remove_children()
        self.form = None
        run = self.query_one("#run", Button)
        run.disabled = action is None
        if action is None:
            self.query_one("#title", Static).update("")
            self.query_one("#desc", Static).update("")
            return
        self.query_one("#title", Static).update(Text.assemble((action.title, "bold"), f"   {action.group}"))
        self.query_one("#desc", Static).update(Text(action.description))
        self.form = ActionForm(action)
        await host.mount(self.form)

    @on(Input.Changed, "#filter")
    async def _filter_changed(self, event):
        await self.populate(event.value)

    @on(OptionList.OptionHighlighted, "#actions")
    async def _highlighted(self, event):
        action = self.by_key.get(event.option_id)
        if action is not None:
            await self.show_action(action)

    @on(OptionList.OptionSelected, "#actions")
    async def _selected(self, event):
        action = self.by_key.get(event.option_id)
        if action is None:
            return
        await self.show_action(action)
        if action.options:
            self.form.focus_first()
        else:
            self.action_run()

    @on(Input.Submitted)
    def _submitted(self, event):
        if event.input.id == "filter":
            self.query_one("#actions").focus()
        else:
            self.action_run()

    @on(Button.Pressed, "#run")
    def _run_pressed(self):
        self.action_run()

    # --- running -----------------------------------------------------------------

    def action_run(self):
        if self.action is None or self.form is None:
            return
        if self._busy:
            self.notify("Still running. Press Esc to cancel it first.", severity="warning")
            return
        if not self.form.validate():
            return
        self._busy = True
        self._title, self._status, self._t0 = self.action.title, None, time.monotonic()
        self._run_line = len(self._outlog.lines)
        self._outlog.write(Rule(self.action.title, style="dim"), expand=True)     # history stays; rule marks the run
        self.run_worker(partial(self._work, self.action, self.form.raw()), thread=True, group="action",
                        exit_on_error=False)

    def _work(self, action, raw):
        """Thread worker: in-process actions (MCP tools, viewer start) block here, never the UI."""
        try:
            out = actions.execute(action, raw, self.manager)
        except Exception:       # noqa: BLE001 - any failure must reach the output panel, not kill the worker
            out = actions.Result("Unexpected error:\n" + traceback.format_exc(), False)
        with contextlib.suppress(RuntimeError):     # the app may have exited meanwhile
            self.call_from_thread(self._after, out)

    def _after(self, out):
        if isinstance(out, actions.CaptureJob):
            self._job, self._seen = out, 0
            return
        ok = False
        try:
            self._show(out)
            ok = out.ok
            # show the result from its first line (the summary), not scrolled to its tail
            self.call_after_refresh(self._outlog.scroll_to, y=self._run_line, animate=False)
        except Exception:       # noqa: BLE001 - a rendering failure must not leave the UI stuck on "Running"
            self._write("Unexpected error:\n" + traceback.format_exc(), False)
        finally:
            self._finish(ok, "OK" if ok else "failed")

    def _show(self, out):
        """Write a finished result: summary line, then the tool's JSON with syntax highlighting."""
        if not (out.head or out.json):
            self._write(out.text, out.ok)
            return
        if out.summary:
            self._outlog.write(Text(clean(out.summary), style="bold"))
        if out.head:
            self._write_lines(out.head.split("\n"), out.ok)
        if out.json:
            self._outlog.write(JSON(out.json, indent=2, ensure_ascii=False))

    def _finish(self, ok, what):
        self._busy = False
        self._status = (ok, f"{what} · {time.monotonic() - self._t0:.1f}s")

    def _write(self, text, ok=True):
        self._write_lines(text.splitlines(), ok)

    def _write_lines(self, lines, ok=True):
        log = self._outlog
        error = self.current_theme.error
        for line in lines:
            bad = not ok or line.startswith("error") or "Traceback" in line
            log.write(Text(clean(line), style=f"bold {error}" if bad else ""))

    def _pump(self):
        """Move new lines of the running capture job into the output; finish when it is done."""
        job = self._job
        done = job.done
        lines, dropped = job.snapshot()
        total = dropped + len(lines)
        if total > self._seen:
            self._write_lines(lines[max(self._seen - dropped, 0):])     # not join+splitlines: keeps blank lines
            self._seen = total
        if not done:
            return
        if dropped:
            self._write(actions.truncation_note(dropped))
        if job.error:
            ok, note, what = False, job.error, "could not start"
        elif job.cancelled:
            ok, note, what = False, "[cancelled]", "cancelled"
        else:
            ok = job.returncode == 0
            note = f"[exit code {job.returncode}]"
            what = "OK" if ok else f"failed (exit code {job.returncode})"
        try:
            self._write(note, ok)
        finally:
            self.last_job, self._job = job, None
            self._finish(ok, what)

    def _tick(self):
        self._frame += 1
        if self._job is not None:
            self._pump()
        status = self._runstatus
        if self._busy:
            elapsed = time.monotonic() - self._t0
            hint = "  ·  Esc cancels" if self._job is not None else ""
            status.update(Text(f"{SPINNER[self._frame % len(SPINNER)]} Running {self._title} · {elapsed:.1f}s{hint}",
                               style=self.current_theme.warning))
        elif self._status is not None:
            ok, text = self._status
            theme = self.current_theme
            status.update(Text(f"{'✔' if ok else '✘'} {self._title}: {text}", style=theme.success if ok else theme.error))
        else:
            status.update(Text("Ready. Pick an action, fill in the form, press Ctrl+R.", style="dim"))
        url, running = hub.url(), self.manager.running()
        bg = f"{len(running)} background process{'es' if len(running) != 1 else ''}"
        if running:
            bg += " (" + ", ".join(t for t, _, _ in running) + ")"
        self._statusbar.update(Text(f" live viewer: {url or 'off'}  ·  {bg}"))

    # --- key actions -------------------------------------------------------------

    def action_escape(self):
        if self._job is not None and not self._job.done:
            self._job.cancel()
            self.notify("Cancelling…")
        else:
            self.query_one("#actions").focus()

    def action_focus_filter(self):
        self.query_one("#filter").focus()

    def action_clear_output(self):
        self._outlog.clear()

    def action_help(self):
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()       # F1 is a priority binding, so it also closes the help
        else:
            self.push_screen(HelpScreen())

    async def action_help_quit(self):       # Ctrl+C (Input handles it first when it has a selection)
        await self.action_quit()

    async def action_quit(self):
        if self._quitting:
            return
        self._quitting = True
        await asyncio.to_thread(self.cleanup)
        self.exit(return_code=self._code)

    def request_exit(self, code):
        """Ask the running app to quit; safe to call from a signal handler on the main thread."""
        loop = self._loop
        if loop is None:
            raise SystemExit(code)
        self._code = code
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.action_quit()))
        except RuntimeError:        # loop already closed: the app is gone, just leave (main() cleans up)
            raise SystemExit(code) from None

    # --- cleanup -----------------------------------------------------------------

    def cleanup(self):
        """Stop every process we started, the viewer we started and the temp logs. Idempotent."""
        if self._cleaned:
            return self.notices
        self._cleaned = True
        stopped = self.manager.terminate_all()
        viewer = hub.url()
        if viewer and self.manager.viewer_owned:
            hub.stop()
        else:
            viewer = None
        if stopped:
            self.notices.append("Stopped background processes: " + ", ".join(stopped))
        if viewer:
            self.notices.append(f"Stopped the live viewer ({viewer}).")
        return self.notices


@contextlib.contextmanager
def stderr_to_log():
    """Keep stray stderr output (hub threads, C code) off the screen by logging it. Yields the log path.

    fd 2 is pointed at a temp file while the UI runs. On POSIX Textual's driver draws the UI on
    `sys.__stderr__`, so that stream is first moved to a private dup of the real terminal fd; on
    Windows the driver uses stdout and fd 2 can simply be redirected.
    """
    log_dir = Path(tempfile.mkdtemp(prefix="seminar2-tui-stderr-"))
    log = log_dir / "stderr.log"
    saved, terminal, original = None, None, sys.__stderr__
    try:
        with contextlib.suppress(AttributeError, OSError, ValueError):
            sys.stderr.flush()
        saved = os.dup(2)
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.dup2(fd, 2)
        finally:
            os.close(fd)
    except OSError:
        if saved is not None:
            os.close(saved)
        saved = None        # no usable fd 2 (e.g. pythonw): leave stderr alone
    if saved is not None and not WINDOWS:
        # Own a second dup so `saved` stays valid for the restore even though closing `terminal` closes its fd.
        terminal = os.fdopen(os.dup(saved), "w", encoding=getattr(original, "encoding", None) or "utf-8",
                             errors="replace")
        sys.__stderr__ = terminal
    try:
        yield log
    finally:
        for stream in (sys.stderr, terminal):
            with contextlib.suppress(AttributeError, OSError, ValueError):
                stream.flush()
        if terminal is not None:
            sys.__stderr__ = original
            terminal.close()
        if saved is not None:
            os.dup2(saved, 2)
            os.close(saved)
        if not log.exists() or log.stat().st_size == 0:
            shutil.rmtree(log_dir, ignore_errors=True)


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("seminar2.tui needs an interactive terminal.", file=sys.stderr)
        return 2
    # Closing the terminal / `kill` must still run the cleanup (not every signal exists on every platform).
    names = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")
    previous = {}
    code = 0
    with stderr_to_log() as log:
        app = TuiApp()      # inside: Textual remembers sys.__stderr__ (the real terminal) at construction
        try:
            for sig in (getattr(signal, n) for n in names if hasattr(signal, n)):
                previous[sig] = signal.signal(sig, lambda signum, frame: app.request_exit(128 + signum))
            app.run()
            code = app.return_code or 0
        except (KeyboardInterrupt, SystemExit) as exc:
            code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 130
        finally:
            app._loop = None        # a late signal must not reach the closed event loop
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            app.cleanup()
    kept = log.exists() and log.stat().st_size > 0
    for notice in app.notices:
        print(notice)
    if kept:
        print(f"Errors were logged to {log}")
    return code
