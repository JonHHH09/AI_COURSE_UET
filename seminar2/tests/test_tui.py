import json
import os
import sys
import time
import types
import unittest
import urllib.request
from unittest import mock

from seminar2 import mcp_server as srv
from seminar2.live import hub
from seminar2.tui import actions, app
from seminar2.tui.actions import Spawn, execute, find, registry


def run(key, **values):
    """Run an action through the same validation path as the form."""
    action = find(key)
    return execute(action, {o.name: values.get(o.name, o.default) for o in action.options})


class RegistryTests(unittest.TestCase):
    def test_every_mcp_tool_has_an_action(self):
        tools = {t.name for t in srv.mcp._tool_manager.list_tools()}
        self.assertEqual(len(tools), 9)
        self.assertEqual({a.key for a in registry() if a.group == actions.G_MCP}, tools)

    def test_fallback_list_matches_server(self):
        self.assertEqual({t.name for t in srv.mcp._tool_manager.list_tools()}, set(actions.FALLBACK_TOOLS))
        with mock.patch.object(srv.mcp, "_tool_manager", None):
            self.assertEqual({n for n, _, _ in actions.discover_tools()}, set(actions.FALLBACK_TOOLS))

    def test_every_command_is_listed(self):
        keys = {a.key for a in registry()}
        self.assertTrue({"live_start", "live_stop", "live_open", "cities_animate", "maze_animate",
                         "cities_draw", "maze_draw", "cities_check", "maze_check", "run_tests",
                         "hermes_check", "inspector", "demo_viewer"} <= keys)
        self.assertEqual(len(keys), len(registry()))

    def test_tool_forms_follow_signatures(self):
        opts = {o.name: o for o in find("trace_maze").options}
        self.assertEqual(list(opts), ["from_room", "to_room", "detail"])
        self.assertEqual((opts["from_room"].default, opts["to_room"].default), (srv.ENTRANCE, srv.EXIT))
        self.assertEqual((opts["from_room"].min, opts["from_room"].max), (1, len(srv.maze)))
        self.assertEqual(opts["detail"].kind, "bool")
        route = {o.name: o for o in find("shortest_route").options}
        self.assertEqual(route["from_city"].choices, tuple(srv.graph))
        self.assertEqual((route["from_city"].default, route["to_city"].default), ("Shkodër", "Korçë"))


class ToolActionTests(unittest.TestCase):
    def setUp(self):
        hub.stop()

    tearDown = setUp

    def test_shortest_route(self):
        r = run("shortest_route")
        self.assertTrue(r.ok)
        self.assertEqual(r.data["total_km"], 267)
        self.assertIn("267", r.text)
        self.assertEqual(json.loads(r.text)["route"][-1], "Korçë")

    def test_trace_maze_numbered_steps(self):
        r = run("trace_maze")
        self.assertTrue(r.ok)
        self.assertEqual(r.data["doors_passed"], 12)
        self.assertIn("   1. ", r.text)
        self.assertLess(r.text.index("Search steps"), r.text.index('"doors_passed"'))

    def test_trace_detail_events_render(self):
        r = run("trace_route", detail=True)
        self.assertTrue(r.ok)
        self.assertIn('"type"', r.text)

    def test_validation_errors(self):
        bad_room = run("find_path", from_room=99)
        self.assertFalse(bad_room.ok)
        self.assertIn("out of range", bad_room.text)
        self.assertFalse(run("get_doors", room=0).ok)
        self.assertIn("not a whole number", run("get_doors", room="x").text)
        # semantic checks also hold when the form layer is bypassed
        self.assertIn("unknown city", find("get_roads").run({"city": "Atlantis"}).text)
        self.assertIn("rooms are 1-25", find("get_doors").run({"room": 26}).text)
        self.assertFalse(find("shortest_route").run({"from_city": "Atlantis", "to_city": "Korçë"}).ok)

    def test_city_choice_is_accent_insensitive(self):
        self.assertEqual(run("get_roads", city="durres").data["city"], "Durrës")

    def test_tool_error_is_not_ok(self):
        r = find("live_viewer").run({})     # hub is stopped
        self.assertFalse(r.ok)
        self.assertIn("not running", r.text)


class SpawnTests(unittest.TestCase):
    def test_cities_animate_argv(self):
        spec = run_spawn("cities_animate", **{"from": "Durres", "to": "Korçë", "fps": 3, "show": True})
        self.assertEqual(spec.argv, [sys.executable, "-m", "seminar2.cities.animate",
                                     "--from", "Durrës", "--to", "Korçë", "--fps", "3", "--show"])
        self.assertEqual(spec.mode, "detached")

    def test_animate_save_mode_captures_with_out(self):
        spec = run_spawn("cities_animate", out="/tmp/x.gif")
        self.assertEqual(spec.mode, "capture")
        self.assertEqual(spec.argv[-1], "--out=/tmp/x.gif")
        self.assertNotIn("--show", spec.argv)

    def test_out_path_starting_with_dash_stays_one_argument(self):
        spec = run_spawn("maze_animate", out="-weird.gif")
        self.assertEqual(spec.argv[-1], "--out=-weird.gif")

    def test_show_with_out_is_an_error(self):
        r = run("cities_animate", show=True, out="/tmp/x.gif")
        self.assertFalse(r.ok)
        self.assertIn("only used when", r.text)
        self.assertIn("only used when", run("maze_animate", show=True, out="x.gif").text)

    def test_maze_animate_argv(self):
        spec = run_spawn("maze_animate", **{"from": 3, "to": 20, "fps": 5})
        self.assertEqual(spec.argv[2:], ["seminar2.maze.animate", "--from", "3", "--to", "20", "--fps", "5"])
        self.assertEqual(spec.mode, "capture")

    def test_animate_validation(self):
        self.assertIn("out of range", run("maze_animate", **{"to": 40}).text)
        self.assertIn("out of range", run("maze_animate", fps=0).text)
        self.assertIn("at least 1", find("maze_animate").run({"from": 1, "to": 2, "fps": 0}).text)
        self.assertIn("not valid", run("cities_animate", **{"from": "Atlantis"}).text)
        self.assertIn("unknown city", find("cities_animate").run({"from": "Atlantis", "to": "Korçë", "fps": 2}).text)

    def test_fixed_commands(self):
        expect = {
            "cities_draw": ["-m", "seminar2.cities.draw"],
            "maze_draw": ["-m", "seminar2.maze.draw"],
            "cities_check": ["-m", "seminar2.cities.graph"],
            "maze_check": ["-m", "seminar2.maze.maze"],
            "run_tests": ["-m", "unittest", "discover", "-s", "seminar2/tests", "-t", "."],
        }
        for key, args in expect.items():
            spec = find(key).run({})
            self.assertEqual((spec.argv, spec.mode), ([sys.executable, *args], "capture"), key)

    def test_demo_viewer_and_inspector(self):
        spec = find("demo_viewer").run({"port": 9001, "open_browser": False})
        self.assertEqual(spec.argv[2:], ["seminar2.live", "--port", "9001", "--no-browser"])
        self.assertEqual(spec.mode, "detached")
        with mock.patch.object(actions.shutil, "which", return_value="/bin/npx"):
            spec = find("inspector").run({})
        self.assertEqual(spec.argv, ["/bin/npx", "@modelcontextprotocol/inspector", sys.executable,
                                     "seminar2/mcp_server.py"])
        self.assertEqual(spec.mode, "detached")

    def test_missing_tools_give_friendly_errors(self):
        with mock.patch.object(actions.shutil, "which", return_value=None):
            for key, word in (("hermes_check", "hermes"), ("inspector", "npx")):
                r = find(key).run({})
                self.assertFalse(r.ok)
                self.assertIn(word, r.text)
        with mock.patch.object(actions.shutil, "which", return_value="/bin/hermes"):
            self.assertEqual(find("hermes_check").run({}).argv, ["/bin/hermes", "mcp", "test", "seminar2"])


SLEEPER = Spawn([sys.executable, "-c", "import time; time.sleep(30)"], "capture", "sleeper")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)


def run_spawn(key, **values):
    """Spawn spec of an action (validated like the form does) without starting it."""
    action = find(key)
    raw = {o.name: values.get(o.name, o.default) for o in action.options}
    typed, errors = actions.coerce(action.options, raw)
    assert not errors, errors
    spec = action.run(typed)
    assert isinstance(spec, Spawn), spec
    return spec


STUBBORN = Spawn([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
                 "capture", "stubborn")


class ProcessTests(unittest.TestCase):
    def test_capture_job_collects_output(self):
        manager = actions.ProcessManager()
        job = manager.start_capture(Spawn([sys.executable, "-c", "print('héllo'); print('x')"], "capture", "t"))
        job.wait(20)
        result = job.result()
        self.assertTrue(result.ok)
        self.assertEqual(list(job.lines), ["héllo", "x"])
        self.assertIn("[exit code 0]", result.text)

    def test_capture_failure_and_missing_binary(self):
        manager = actions.ProcessManager()
        job = manager.start_capture(Spawn([sys.executable, "-c", "raise SystemExit(3)"], "capture", "t"))
        job.wait(20)
        self.assertFalse(job.result().ok)
        missing = manager.start_capture(Spawn(["/no/such/binary"], "capture", "t"))
        missing.wait(20)
        self.assertIn("could not start", missing.result().text)

    def test_detached_logs_and_terminate(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.terminate_all)
        spec = Spawn([sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"], "detached", "sleeper")
        result = manager.spawn_detached(spec)
        self.assertTrue(result.ok)
        self.assertIn("sleeper", result.text)
        self.assertEqual(len(manager.running()), 1)
        log_dir = manager._dir
        self.assertTrue(log_dir.is_dir())
        self.assertEqual(manager.terminate_all(), ["sleeper"])
        self.assertEqual(manager.running(), [])
        self.assertIn("sleeper", manager.describe())
        self.assertFalse(log_dir.exists())      # temp dir removed with the processes

    def test_cancel_is_fast_and_kills_the_child(self):
        manager = actions.ProcessManager()
        job = manager.start_capture(SLEEPER)
        wait_for(lambda: job._proc is not None)
        pid = job._proc.pid
        t0 = time.monotonic()
        job.cancel()
        self.assertLess(time.monotonic() - t0, 0.5)
        job.wait(5)
        self.assertTrue(job.done and job.cancelled)
        wait_for(lambda: not pid_alive(pid), 3)
        self.assertFalse(pid_alive(pid))
        self.assertIn("[cancelled]", job.result().text)

    def test_cancel_right_after_start_still_kills(self):
        job = actions.ProcessManager().start_capture(SLEEPER)
        job.cancel()                       # may run before Popen has returned
        job.wait(8)
        self.assertTrue(job.done)
        self.assertLess(job.elapsed, 8)
        self.assertNotEqual(job.returncode, 0)

    def test_terminate_kills_grandchildren(self):
        code = ("import subprocess, sys, time\n"
                "c = subprocess.Popen([sys.executable, '-c', 'import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
                "print(c.pid, flush=True); time.sleep(60)")
        job = actions.ProcessManager().start_capture(Spawn([sys.executable, "-c", code], "capture", "t"))
        wait_for(lambda: job.lines)
        child = int(job.lines[0])
        job.cancel()
        job.wait(8)
        wait_for(lambda: not pid_alive(child), 6)
        self.assertFalse(pid_alive(child))

    def test_terminate_all_kills_sigterm_ignoring_capture_child(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.terminate_all, 0.2)
        job = manager.start_capture(STUBBORN)
        wait_for(lambda: job._proc is not None)
        pid = job._proc.pid
        time.sleep(0.3)                    # let the child install its SIGTERM handler
        manager.terminate_all(grace=0.3)
        self.assertTrue(job.done)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_terminate_all_skips_exited_detached_process(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.remove_logs)
        manager.spawn_detached(Spawn([sys.executable, "-c", "pass"], "detached", "quick"))
        manager.detached[0][1].wait(10)
        with mock.patch.object(os, "killpg") as killpg:
            self.assertEqual(manager.terminate_all(grace=0.2), [])
        killpg.assert_not_called()

    def test_terminate_all_overlaps_stubborn_processes(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.terminate_all, 0.2)
        for i in range(4):
            manager.spawn_detached(Spawn(STUBBORN.argv, "detached", f"stubborn{i}"))
        time.sleep(0.4)
        t0 = time.monotonic()
        manager.terminate_all(grace=0.5)
        self.assertLess(time.monotonic() - t0, 1.5)    # ~1 grace, not 4x
        self.assertEqual(manager.running(), [])

    def test_lines_are_capped(self):
        code = f"for i in range({actions.MAX_LINES + 50}): print(i)"
        job = actions.ProcessManager().start_capture(Spawn([sys.executable, "-c", code], "capture", "t"))
        job.wait(20)
        lines, dropped = job.snapshot()
        self.assertEqual((len(lines), dropped), (actions.MAX_LINES, 50))
        self.assertEqual(lines[0], "50")
        self.assertIn("first 50 lines were dropped", job.result().text)


class FormTests(unittest.TestCase):
    def form(self, key="trace_maze"):
        return app.Form(find(key))

    def test_defaults_and_values(self):
        f = self.form()
        self.assertEqual(f.values(), {"from_room": str(srv.ENTRANCE), "to_room": str(srv.EXIT), "detail": False})
        c = app.Form(find("shortest_route"))
        self.assertEqual(c.values(), {"from_city": "Shkodër", "to_city": "Korçë"})

    def test_choice_cycles_both_ways(self):
        f = app.Form(find("shortest_route"))
        n = len(find("shortest_route").options[0].choices)
        start = f.raw[0]
        f.step(1)
        self.assertEqual(f.raw[0], (start + 1) % n)
        for _ in range(n - 1):
            f.step(1)
        self.assertEqual(f.raw[0], start)
        f.raw[0] = 0
        f.step(-1)
        self.assertEqual(f.raw[0], n - 1)

    def test_int_stepping_clamps_to_range(self):
        f = self.form()
        f.raw[0] = "1"
        f.step(-1)
        self.assertEqual(f.raw[0], "1")
        f.raw[0] = str(len(srv.maze))
        f.step(1)
        self.assertEqual(f.raw[0], str(len(srv.maze)))
        f.raw[0] = ""
        f.step(1)                       # unparsable text falls back to the default
        self.assertEqual(f.raw[0], str(srv.ENTRANCE))

    def test_bool_toggle_and_int_typing(self):
        f = self.form()
        f.focus = 2
        f.type(" ")
        self.assertTrue(f.values()["detail"])
        f.step(1)
        self.assertFalse(f.values()["detail"])
        f.focus = 0
        f.backspace(clear=True)
        for ch in "1a2-":
            f.type(ch)
        self.assertEqual(f.raw[0], "12")
        f.backspace()
        self.assertEqual(f.raw[0], "1")
        f.backspace(clear=True)
        f.type("-")
        self.assertEqual(f.raw[0], "-")

    def test_text_editing(self):
        f = app.Form(find("cities_animate"))
        f.focus = next(i for i, o in enumerate(f.action.options) if o.name == "out")
        for ch in "a b/é":
            f.type(ch)
        self.assertEqual(f.values()["out"], "a b/é")
        f.backspace()
        self.assertEqual(f.values()["out"], "a b/")
        f.backspace(clear=True)
        self.assertEqual(f.values()["out"], "")

    def test_long_text_scrolls_to_keep_cursor_visible(self):
        f = app.Form(find("cities_animate"))
        i = next(i for i, o in enumerate(f.action.options) if o.name == "out")
        f.focus = i
        f.raw[i] = "x" * 50 + "END"
        shown = f.display(i, 10)
        self.assertTrue(shown.startswith("[ …"))
        self.assertIn("END_", shown)
        self.assertLessEqual(len(shown), 10 + 4)
        self.assertIn("END", f.display(i))           # no cap: unchanged


class HelperTests(unittest.TestCase):
    def test_clean_strips_escapes_and_controls(self):
        self.assertEqual(app.clean("\x1b[31mred\x1b[0m\x07 ok\r"), "red ok")
        self.assertEqual(app.clean("a\tb"), "a   b")

    def test_wrap_width_indent_and_blank_lines(self):
        out = app.wrap(["", "word " * 30, "  indented " * 10], 40)
        self.assertEqual(out[0], "")
        self.assertTrue(all(len(x) <= 40 for x in out))
        self.assertTrue(all(x.startswith("      ") for x in out[len(app.wrap(["word " * 30], 40)) + 1 + 1:]))
        self.assertEqual(app.wrap(["x" * 25], 5), ["x" * 10, "x" * 10, "x" * 5])   # min width 10


class FakeJob:
    def __init__(self):
        self.raw, self.dropped, self.done = [], 0, False

    def snapshot(self):
        return list(self.raw), self.dropped


class PagerTests(unittest.TestCase):
    def test_finished_result_wrap_is_cached(self):
        p = app.Pager("t", result=actions.Result("a\nb\nc", True))
        with mock.patch.object(app, "wrap", wraps=app.wrap) as w:
            first = p.lines(20)
            self.assertEqual(p.lines(20), first)
            self.assertEqual(w.call_count, 1)
            p.lines(30)
            self.assertEqual(w.call_count, 2)

    def test_scroll_clamps_and_follow_toggles(self):
        p = app.Pager("t", job=FakeJob())
        self.assertTrue(p.follow)
        self.assertEqual(p.view_top(100, 20), 80)
        p.move(-5, 100, 20)
        self.assertEqual((p.top, p.follow), (75, False))
        self.assertEqual(p.view_top(150, 20), 75)           # stays put while scrolled up
        p.move(1000, 150, 20)
        self.assertEqual((p.top, p.follow), (130, True))
        p.move(-1000, 150, 20)
        self.assertEqual((p.top, p.follow), (0, False))
        p.move(5, 10, 20)                                   # short output: nothing to scroll
        self.assertEqual(p.top, 0)

    def test_incremental_wrap_and_truncation_note(self):
        job = FakeJob()
        p = app.Pager("t", job=job)
        job.raw = ["a " * 20, "b"]
        with mock.patch.object(app, "wrap", wraps=app.wrap) as w:
            first = p.lines(20)
            job.raw.append("c")
            second = p.lines(20)
            self.assertEqual(second[:len(first)], first)
            self.assertEqual(second[-1], "c")
            self.assertEqual(w.call_count, 3)               # 2 + 1 new line, no re-wrap of old ones
            p.lines(20)
            self.assertEqual(w.call_count, 3)
        job.raw, job.dropped = job.raw[1:], 1
        lines = p.lines(20)
        self.assertEqual(lines[0], actions.truncation_note(1))
        self.assertEqual(lines[1:], ["b", "c"])
        self.assertEqual(len(p.lines(30)), 3)               # new width re-wraps


class LiveViewerTests(unittest.TestCase):
    def setUp(self):
        hub.stop()

    tearDown = setUp

    def test_start_publish_stop(self):
        self.assertIn("not running", run("live_open").text)
        started = run("live_start", port=0)
        self.assertTrue(started.ok, started.text)
        url = hub.url()
        self.assertEqual(started.data, url)
        self.assertIn(url, started.text)
        self.assertIn("already running", run("live_start", port=0).text)
        run("shortest_route")
        sessions = json.load(urllib.request.urlopen(url + "sessions", timeout=5))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["result"]["cost"], 267)
        with mock.patch.object(actions, "open_browser", return_value=True) as opened:
            self.assertTrue(run("live_open").ok)
            run("live_start", port=0, open_browser=True)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(run("live_stop").text, f"Live viewer stopped ({url}).")
        self.assertIsNone(hub.url())
        self.assertIn("not running", run("live_stop").text)

    def test_bad_port_rejected(self):
        self.assertIn("out of range", run("live_start", port=70000).text)
        self.assertIsNone(hub.url())


if __name__ == "__main__":
    unittest.main()
