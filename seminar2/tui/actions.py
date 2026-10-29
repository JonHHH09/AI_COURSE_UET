"""UI-free action registry for the terminal UI (no Textual imports here).

Every feature of the project is an `Action`: a key, a group, a title, a
description, a list of `Option`s (what the form asks for) and a `run(values)`
callable. `run` returns either a `Result` (in-process work, already finished)
or a `Spawn` (a subprocess to start, `capture` or `detached`). `execute` is the
single entry point the UI uses: it coerces/validates the raw form values, runs
the action and starts any subprocess through the `ProcessManager`.
"""

import collections
import contextlib
import functools
import inspect
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seminar2 import mcp_server as srv
from seminar2.live import hub
from seminar2.text import fold

ROOT = Path(__file__).resolve().parent.parent.parent

G_MCP, G_LIVE, G_ANIM = "MCP tools", "Live viewer", "Animations"
G_DATA, G_DEV = "Figures & data", "Dev & tools"

# MCP tool parameters that get dataset-aware choices.
CITY_PARAMS = {"city": "Shkodër", "from_city": "Shkodër", "to_city": "Korçë"}
ROOM_PARAMS = ("room", "from_room", "to_room")


class UserError(Exception):
    """Bad input; the message is shown to the user as is."""


@dataclass(frozen=True)
class Option:
    name: str
    label: str
    kind: str = "text"            # 'choice' | 'int' | 'bool' | 'text'
    choices: tuple = ()
    default: Any = None
    required: bool = False
    min: int | None = None        # int options only
    max: int | None = None

    def hint(self):
        if self.kind == "int" and (self.min is not None or self.max is not None):
            return f"{'' if self.min is None else self.min}..{'' if self.max is None else self.max}"
        if self.kind == "choice":
            return f"{len(self.choices)} choices"
        return ""


@dataclass
class Result:
    text: str
    ok: bool = True
    data: Any = None
    summary: str = ""     # one-line digest of a route/path result (shown above the JSON)
    head: str = ""        # tool results: everything before the JSON (numbered lists, error + choices)
    json: str = ""        # tool results: the JSON part, for syntax highlighting; "" = nothing to highlight


@dataclass
class Spawn:
    argv: list
    mode: str = "capture"         # 'capture' | 'detached'
    title: str = ""
    cwd: Path = ROOT


@dataclass(frozen=True)
class Action:
    key: str
    group: str
    title: str
    description: str
    options: tuple
    run: Callable[[dict], Result | Spawn]


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(values):
        try:
            return fn(values)
        except UserError as exc:
            return Result(str(exc), ok=False)
    return wrapper


# --- value coercion / validation ---------------------------------------------

def coerce(options, raw):
    """Turn raw form values into typed ones. Returns (values, error-messages)."""
    values, errors = {}, []
    for opt in options:
        v = raw.get(opt.name, opt.default)
        if opt.kind == "bool":
            values[opt.name] = bool(v)
            continue
        blank = v is None or (isinstance(v, str) and not v.strip())
        if blank:
            if opt.required:
                errors.append(f"{opt.label} is required")
            values[opt.name] = None
            continue
        if opt.kind == "choice":
            match = next((c for c in opt.choices if c == v or fold(str(c)) == fold(str(v))), None)
            if match is None:
                errors.append(f"{opt.label}: {v!r} is not valid; choose one of {', '.join(map(str, opt.choices))}")
            values[opt.name] = match
        elif opt.kind == "int":
            try:
                n = int(str(v).strip())
            except ValueError:
                errors.append(f"{opt.label}: {v!r} is not a whole number")
                values[opt.name] = None
                continue
            if (opt.min is not None and n < opt.min) or (opt.max is not None and n > opt.max):
                errors.append(f"{opt.label}: {n} is out of range ({opt.hint()})")
            values[opt.name] = n
        else:
            values[opt.name] = str(v).strip()
    return values, errors


def _city(name):
    for city in srv.graph:
        if fold(city) == fold(str(name)):
            return city
    raise UserError(f"unknown city {name!r}; valid cities: {', '.join(srv.graph)}")


def _room(value):
    try:
        room = int(value)
    except (TypeError, ValueError):
        raise UserError(f"room {value!r} is not a whole number") from None
    if room not in srv.maze:
        raise UserError(f"room {room} does not exist, rooms are 1-{len(srv.maze)}")
    return room


def _fps(value):
    try:
        fps = int(value)
    except (TypeError, ValueError):
        raise UserError(f"fps {value!r} is not a whole number") from None
    if fps < 1:
        raise UserError("fps must be at least 1")
    return fps


# --- MCP tool actions -----------------------------------------------------------

def summarize(data):
    """One line for route/path results, e.g. 'A → B → C · 267 km' or '1 → 2 → … → 25 · 12 doors'; else ''."""
    if not isinstance(data, dict) or "error" in data:
        return ""
    if isinstance(data.get("route"), list) and "total_km" in data:
        route = data["route"]
        return f"{' → '.join(map(str, route))} · {data['total_km']} km" if route else "no route"
    if isinstance(data.get("path"), list) or ("path" in data and "doors_passed" in data):
        path = data["path"] or []
        if not path:
            return "no path"
        shown = path if len(path) <= 8 else [*path[:3], "…", *path[-2:]]
        return f"{' → '.join(map(str, shown))} · {data['doors_passed']} doors"
    return ""


def _numbered(rest):
    """Pop the build/steps lists (trace tools) out of `rest`; returns the numbered text lines."""
    parts = []
    for key, title in (("build", "Build the graph"), ("steps", "Search steps")):
        items = rest.get(key)
        if isinstance(items, list):
            del rest[key]
            parts.append(f"{title} ({len(items)})")
            parts += [f"{i:>4}. {m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)}"
                      for i, m in enumerate(items, 1)]
            parts.append("")
    return parts


def format_tool_result(data):
    """Numbered build/steps lists (trace tools) followed by the rest as JSON."""
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, indent=2)
    rest = dict(data)
    parts = _numbered(rest)
    if "error" in rest:
        parts.append(f"error: {rest['error']}")
    parts.append(json.dumps(rest, ensure_ascii=False, indent=2))
    return "\n".join(parts)


def tool_parts(data):
    """(head, json) for display: text before the JSON, and the JSON to highlight ('' for error results).

    An error result becomes `error: ...` plus the valid choices (when the tool lists them) and no JSON.
    """
    if not isinstance(data, dict):
        return "", json.dumps(data, ensure_ascii=False, indent=2)
    rest = dict(data)
    parts = _numbered(rest)
    if "error" in rest:
        parts.append(f"error: {rest['error']}")
        if isinstance(rest.get("cities"), list):
            parts.append("valid choices: " + ", ".join(map(str, rest["cities"])))
        return "\n".join(parts), ""
    return "\n".join(parts).rstrip("\n"), json.dumps(rest, ensure_ascii=False, indent=2)


def _tool_option(param):
    name, ann = param.name, param.annotation
    required = param.default is inspect.Parameter.empty
    default = None if required else param.default
    label = name.replace("_", " ").capitalize()
    if name in CITY_PARAMS:
        cities = tuple(srv.graph)
        first = CITY_PARAMS[name] if CITY_PARAMS[name] in cities else cities[0]
        return Option(name, label, "choice", cities, first, required)
    if ann is bool:
        return Option(name, label, "bool", default=bool(default))
    if ann is int:
        if name in ROOM_PARAMS:
            return Option(name, label, "int", default=default if default is not None else srv.ENTRANCE,
                          required=required, min=1, max=len(srv.maze))
        return Option(name, label, "int", default=default, required=required)
    return Option(name, label, "text", default=default, required=required)


def _tool_action(name, fn, doc):
    options = tuple(_tool_option(p) for p in inspect.signature(fn).parameters.values())

    @_safe
    def run(values):
        kwargs = {}
        for opt in options:
            v = values.get(opt.name)
            if opt.name in CITY_PARAMS and v is not None:
                v = _city(v)
            elif opt.name in ROOM_PARAMS and v is not None:
                v = _room(v)
            if v is not None:
                kwargs[opt.name] = v
        data = fn(**kwargs)
        ok = not (isinstance(data, dict) and "error" in data)
        head, body = tool_parts(data)
        return Result(format_tool_result(data), ok, data, summarize(data), head, body)

    paragraphs = [" ".join(p.split()) for p in (doc or name).split("\n\n")]
    return Action(name, G_MCP, name, "\n\n".join(paragraphs), options, run)


FALLBACK_TOOLS = ("list_cities", "get_roads", "shortest_route", "trace_route", "get_maze",
                  "get_doors", "find_path", "trace_maze", "live_viewer")


def discover_tools():
    """[(name, function, doc)] for every tool registered on the MCP server.

    Uses the MCPServer's tool manager (private `_tool_manager`); if a future SDK
    drops it, falls back to the explicit FALLBACK_TOOLS names on the module.
    """
    try:
        return [(t.name, t.fn, t.description) for t in srv.mcp._tool_manager.list_tools()]
    except AttributeError:
        return [(n, getattr(srv, n), inspect.getdoc(getattr(srv, n))) for n in FALLBACK_TOOLS]


# --- live viewer ----------------------------------------------------------------

def open_browser(url):
    """Open `url` without blocking the UI (webbrowser.open can wait on the launcher)."""
    threading.Thread(target=webbrowser.open, args=(url,), name="tui-browser", daemon=True).start()
    return True


@_safe
def _start_viewer(values):
    url = hub.url()
    lines = []
    if url:
        lines.append(f"Live viewer already running: {url}")
    else:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):     # hub logs to stderr; keep the screen clean
            url = hub.start(port=values.get("port"))
        if url is None:
            return Result(f"Could not start the live viewer (port busy or invalid?)\n{err.getvalue().strip()}", False)
        lines.append(f"Live viewer started: {url}")
    lines.append("MCP-tool actions (shortest_route, find_path, trace_*) now publish to it.")
    if values.get("open_browser"):
        lines.append("Opening it in the browser." if open_browser(url) else "Could not open a browser; open the URL by hand.")
    return Result("\n".join(lines), True, url)


@_safe
def _stop_viewer(values):
    if hub.url() is None:
        return Result("Live viewer is not running.")
    url = hub.url()
    hub.stop()
    return Result(f"Live viewer stopped ({url}).")


@_safe
def _open_viewer(values):
    url = hub.url()
    if url is None:
        return Result("Live viewer is not running. Start it first (Live viewer > Start live viewer).", False)
    return Result(f"Opening {url} in the browser" if open_browser(url) else f"Could not open a browser; open {url} by hand.")


# --- subprocess actions ---------------------------------------------------------

def _module(*args, title, mode="capture"):
    return Spawn([sys.executable, "-m", *args], mode, title)


def _animate_argv(start, goal, fps, show, out):
    argv = ["--from", str(start), "--to", str(goal), "--fps", str(fps)]
    if show:
        argv.append("--show")
    elif out:
        argv.append(f"--out={out}")     # '=' form: a path starting with '-' is not read as an option
    return argv


def _animate_spawn(module, title, start, goal, fps, values):
    show, out = values.get("show"), values.get("out")
    if show and out:
        raise UserError("Output GIF path is only used when 'show a window' is off")
    return _module(module, *_animate_argv(start, goal, fps, show, out), title=title,
                   mode="detached" if show else "capture")


@_safe
def _cities_animate(values):
    a, b, fps = _city(values["from"]), _city(values["to"]), _fps(values["fps"])
    return _animate_spawn("seminar2.cities.animate", f"cities animate {a} → {b}", a, b, fps, values)


@_safe
def _maze_animate(values):
    a, b, fps = _room(values["from"]), _room(values["to"]), _fps(values["fps"])
    return _animate_spawn("seminar2.maze.animate", f"maze animate {a} → {b}", a, b, fps, values)


@_safe
def _hermes_check(values):
    exe = shutil.which("hermes")
    if exe is None:
        return Result("The `hermes` command was not found on PATH. Install Hermes or add it to PATH, "
                      "then run: hermes mcp test seminar2", False)
    return Spawn([exe, "mcp", "test", "seminar2"], "capture", "hermes mcp test seminar2")


@_safe
def _inspector(values):
    exe = shutil.which("npx")
    if exe is None:
        return Result("`npx` was not found on PATH. Install Node.js (https://nodejs.org) to use the MCP Inspector.", False)
    return Spawn([exe, "@modelcontextprotocol/inspector", sys.executable, "seminar2/mcp_server.py"],
                 "detached", "MCP Inspector")


@_safe
def _demo_viewer(values):
    argv = ["seminar2.live"]
    port = values.get("port")
    if port is not None:
        argv += ["--port", str(port)]
    if not values.get("open_browser"):
        argv.append("--no-browser")
    return _module(*argv, title="standalone demo viewer", mode="detached")


@_safe
def _processes(values):
    return Result(PROCESSES.describe())


# --- process management --------------------------------------------------------

MAX_LINES = 5000
GRACE = 2.0      # seconds between SIGTERM and SIGKILL
TASKKILL_TIMEOUT = 10      # seconds before a hung `taskkill` is abandoned
WINDOWS = sys.platform == "win32"


class CaptureJob:
    """A subprocess whose combined output is collected on a background thread.

    Only the last MAX_LINES lines are kept; `dropped` counts the older ones.
    """

    def __init__(self, spec):
        self.spec = spec
        self.lines = collections.deque(maxlen=MAX_LINES)
        self.dropped = 0
        self.returncode = None
        self.error = None
        self.cancelled = False
        self.started = time.monotonic()
        self.finished = None
        self._lock = threading.Lock()
        self._proc = None
        self._killer = None
        self._grace = GRACE
        self._thread = threading.Thread(target=self._run, name="tui-capture", daemon=True)
        self._thread.start()

    def _add(self, line):
        with self._lock:
            if len(self.lines) == self.lines.maxlen:
                self.dropped += 1
            self.lines.append(line)

    def snapshot(self):
        """(lines, dropped) taken atomically; safe while the reader thread appends."""
        with self._lock:
            return list(self.lines), self.dropped

    def _run(self):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            with subprocess.Popen(
                    self.spec.argv, cwd=self.spec.cwd, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", **_group_kwargs()) as proc:
                self._proc = proc
                if self.cancelled:      # cancel() ran before the process existed
                    _terminate(proc, self._grace)
                for line in proc.stdout or ():
                    self._add(line.rstrip("\n"))
                self.returncode = proc.wait()
        except OSError as exc:
            self.error = f"could not start {self.spec.argv[0]}: {exc}"
        finally:
            self.finished = time.monotonic()

    @property
    def done(self):
        return self.finished is not None

    @property
    def elapsed(self):
        return (self.finished or time.monotonic()) - self.started

    def cancel(self, grace=GRACE):
        """Stop the job without blocking the caller (the UI thread)."""
        self.cancelled = True
        self._grace = grace
        proc = self._proc
        if proc is not None and self._killer is None:
            self._killer = threading.Thread(target=_terminate, args=(proc, grace), name="tui-cancel", daemon=True)
            self._killer.start()

    def wait(self, timeout=None):
        self._thread.join(timeout)

    def result(self):
        lines, dropped = self.snapshot()
        if dropped:
            lines.insert(0, truncation_note(dropped))
        text = "\n".join(lines)
        if self.error:
            return Result(self.error, False)
        if self.cancelled:
            return Result(text + "\n[cancelled]", False)
        ok = self.returncode == 0
        return Result(f"{text}\n[exit code {self.returncode}]" if text else f"[exit code {self.returncode}]", ok)


def truncation_note(dropped):
    return f"[output truncated: the first {dropped} lines were dropped]"


def _group_kwargs():
    """Popen kwargs that put the child in its own process group (so the whole tree can be stopped)."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _taskkill(proc):
    """Windows: force-kill the process and its children (`taskkill /T`); plain kill() if that fails."""
    try:
        done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=TASKKILL_TIMEOUT, check=False)
        if done.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        pass
    with contextlib.suppress(OSError):
        proc.kill()


def _sigterm(proc):
    """Ask a still-running process (group) to stop; False if it had already exited (never signal a reaped pid).

    POSIX: SIGTERM to the group. Windows has no graceful group signal for console children,
    so the whole tree is killed right away.
    """
    if proc is None or proc.poll() is not None:
        return False
    if WINDOWS:
        _taskkill(proc)
        return True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    return True


def _sigkill(proc, grace):
    """Force-kill the group (grandchildren such as npx -> node may outlive the leader), then reap."""
    if WINDOWS:
        if proc.poll() is None:     # the tree is only reachable through a live leader
            _taskkill(proc)
    else:
        # Also runs after the leader was reaped, on purpose: surviving grandchildren keep the group alive.
        # An empty group just gives ESRCH; the pid-reuse window is tiny (we signalled it moments ago).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(grace)
    except subprocess.TimeoutExpired:
        pass


def _concurrently(fn, items, timeout):
    """Run fn(item) for every item on its own thread; join them all on one shared deadline.

    Returns {index: result} for the calls that finished in time (a slow call is left running).
    """
    results = {}

    def call(i, item):
        results[i] = fn(item)

    threads = [threading.Thread(target=call, args=(i, item), name="tui-signal", daemon=True)
               for i, item in enumerate(items)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(deadline - time.monotonic(), 0))
    return results


def _terminate(proc, grace=GRACE):
    """SIGTERM the process group, wait `grace`, then SIGKILL the group (Windows: kill the tree).

    Does nothing when the process had already exited (its pid may be reused).
    """
    if not _sigterm(proc):
        return
    try:
        proc.wait(grace)
    except subprocess.TimeoutExpired:
        pass
    _sigkill(proc, grace)


class ProcessManager:
    """Tracks detached processes (log files in a temp dir) and capture jobs."""

    def __init__(self):
        self._dir = None
        self.detached = []     # (title, Popen, log path)
        self.jobs = []
        self.viewer_owned = False     # the live viewer that is running now was started by an action run here

    def _log_path(self, title):
        if self._dir is None:
            self._dir = Path(tempfile.mkdtemp(prefix="seminar2-tui-"))
        slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:30]
        return self._dir / f"{len(self.detached) + 1}-{slug}.log"

    def spawn_detached(self, spec):
        log = self._log_path(spec.title)
        try:
            with open(log, "wb") as fh:
                proc = subprocess.Popen(spec.argv, cwd=spec.cwd, stdin=subprocess.DEVNULL, stdout=fh,
                                        stderr=subprocess.STDOUT, **_group_kwargs())
        except OSError as exc:
            return Result(f"could not start {spec.argv[0]}: {exc}", False)
        self.detached.append((spec.title, proc, log))
        return Result(f"Started {spec.title} in the background (pid {proc.pid}).\n"
                      f"Output goes to {log}\n"
                      "It is stopped automatically when you quit the TUI. "
                      "See Dev & tools > Detached processes.", True, proc.pid)

    def start_capture(self, spec):
        job = CaptureJob(spec)
        self.jobs = [j for j in self.jobs if not j.done] + [job]
        return job

    def running(self):
        return [(t, p, log) for t, p, log in self.detached if p.poll() is None]

    def describe(self):
        if not self.detached:
            return "No detached processes were started in this session."
        out = []
        for title, proc, log in self.detached:
            rc = proc.poll()
            out.append(f"{title}: pid {proc.pid}, {'running' if rc is None else f'exited with code {rc}'}")
            out.append(f"  log: {log}")
            try:
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
            except OSError:
                tail = []
            out += [f"  | {line}" for line in tail]
            out.append("")
        return "\n".join(out).rstrip()

    def terminate_all(self, grace=GRACE):
        """Stop everything we started and delete the log dir. Returns the titles that were still running.

        All jobs are cancelled and all live detached processes SIGTERMed first, so
        the grace periods overlap; we then wait for every killer to finish (they
        are daemon threads and would otherwise die with the interpreter).
        """
        stopped = []
        # Windows runs one taskkill subprocess per process: do them concurrently so the grace periods overlap.
        signalled = _concurrently(_sigterm, [p for _, p, _ in self.detached], TASKKILL_TIMEOUT + 1)
        live = [(t, p) for i, (t, p, _) in enumerate(self.detached) if signalled.get(i)]
        stopped += [t for t, _ in live]
        pending = [j for j in self.jobs if not j.done]
        for job in pending:
            job.cancel(grace)
            stopped.append(job.spec.title)
        deadline = time.monotonic() + 2 * grace + 1
        for job in pending:
            if job._killer is not None:
                job._killer.join(max(deadline - time.monotonic(), 0))
            # cancelled before Popen: the job thread kills the child itself
            job._thread.join(max(deadline - time.monotonic(), 0))
        end = time.monotonic() + grace

        def finish(proc):
            try:
                proc.wait(max(end - time.monotonic(), 0))
            except subprocess.TimeoutExpired:
                pass
            _sigkill(proc, grace)

        _concurrently(finish, [p for _, p in live], 2 * grace + TASKKILL_TIMEOUT + 1)
        self.remove_logs()
        return stopped

    def remove_logs(self):
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None


PROCESSES = ProcessManager()


def execute(action, raw, manager=None):
    """Validate raw form values and run the action.

    Returns a Result, or a CaptureJob for a capture-mode subprocess (poll it).
    """
    manager = manager or PROCESSES
    values, errors = coerce(action.options, raw)
    if errors:
        return Result("\n".join(errors), False)
    viewer_before = hub.url()
    out = action.run(values)
    viewer_now = hub.url()
    if viewer_now is None:          # per start, not a snapshot: a viewer restarted from here is ours again
        manager.viewer_owned = False
    elif viewer_before is None:
        manager.viewer_owned = True
    if isinstance(out, Spawn):
        return manager.start_capture(out) if out.mode == "capture" else manager.spawn_detached(out)
    return out


# --- registry -------------------------------------------------------------------

@functools.cache
def registry():
    cities, n_rooms = tuple(srv.graph), len(srv.maze)
    city = lambda name, label, default: Option(name, label, "choice", cities,
                                                default if default in cities else cities[0], True)
    room = lambda name, label, default: Option(name, label, "int", default=default, required=True,
                                                min=1, max=n_rooms)
    fps = lambda default: Option("fps", "Frames per second", "int", default=default, required=True,
                                 min=1, max=60)
    show = Option("show", "Show a window (instead of saving)", "bool", default=False)
    out = Option("out", "Output GIF path (blank = default)", "text")
    port = Option("port", "Port (blank = default)", "int", min=0, max=65535)
    browser = Option("open_browser", "Open in the browser", "bool", default=False)

    acts = [_tool_action(*t) for t in discover_tools()]
    acts += [
        Action("live_start", G_LIVE, "Start live viewer",
               "Start the live viewer hub inside this TUI process and show its URL. While it runs, the MCP-tool "
               "actions above publish their searches to it, so a browser animates them. Blank port = 8765 "
               "(falls back to a free port if busy).",
               (port, browser), _start_viewer),
        Action("live_stop", G_LIVE, "Stop live viewer", "Stop the live viewer started from this TUI and forget its history.",
               (), _stop_viewer),
        Action("live_open", G_LIVE, "Open viewer in browser", "Open the running live viewer in your web browser.",
               (), _open_viewer),
        Action("cities_animate", G_ANIM, "Cities animate",
               "Animate building the city graph and the Dijkstra search (GIF). With 'show' it opens a "
               "matplotlib window as a background process; otherwise it saves the GIF and shows the output.",
               (city("from", "From city", "Shkodër"), city("to", "To city", "Korçë"), fps(2), show, out),
               _cities_animate),
        Action("maze_animate", G_ANIM, "Maze animate",
               "Animate building the maze and the BFS search (GIF). With 'show' it opens a matplotlib "
               "window as a background process; otherwise it saves the GIF and shows the output.",
               (room("from", "From room", srv.ENTRANCE), room("to", "To room", srv.EXIT), fps(4), show, out),
               _maze_animate),
        Action("cities_draw", G_DATA, "Cities draw", "Write seminar2/images/cities/graph.png.", (),
               (lambda v: _module("seminar2.cities.draw", title="cities draw"))),
        Action("maze_draw", G_DATA, "Maze draw", "Write seminar2/images/maze/maze.png.", (),
               (lambda v: _module("seminar2.maze.draw", title="maze draw"))),
        Action("cities_check", G_DATA, "Cities graph check",
               "Print the city graph with its symmetric/connected checks (python -m seminar2.cities.graph).", (),
               (lambda v: _module("seminar2.cities.graph", title="cities graph check"))),
        Action("maze_check", G_DATA, "Maze check",
               "Print the maze with its validation result (python -m seminar2.maze.maze).", (),
               (lambda v: _module("seminar2.maze.maze", title="maze check"))),
        Action("run_tests", G_DEV, "Run tests",
               "Run the unittest suite: python -m unittest discover -s seminar2/tests -t .", (),
               (lambda v: _module("unittest", "discover", "-s", "seminar2/tests", "-t", ".", title="run tests"))),
        Action("hermes_check", G_DEV, "Hermes check",
               "Run `hermes mcp test seminar2` to check the server registered in Hermes.", (), _hermes_check),
        Action("inspector", G_DEV, "MCP Inspector",
               "Start the MCP Inspector (npx @modelcontextprotocol/inspector) against seminar2/mcp_server.py "
               "as a background process; it prints a URL in its log.", (), _inspector),
        Action("demo_viewer", G_DEV, "Standalone demo viewer",
               "Run `python -m seminar2.live` as a separate background process with two demo sessions.",
               (port, browser), _demo_viewer),
        Action("processes", G_DEV, "Detached processes",
               "List background processes started from this TUI with their log files and last output.", (),
               _processes),
    ]
    return acts


def find(key):
    return next(a for a in registry() if a.key == key)
