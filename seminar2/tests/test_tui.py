import asyncio
import json
import os
import sys
import time
import unittest
import urllib.request
from unittest import mock

from seminar2 import mcp_server as srv
from seminar2.live import hub
from seminar2.tui import actions
from seminar2.tui import app as app_module
from seminar2.tui.actions import Spawn, execute, find, registry
from seminar2.tui.app import HelpScreen, TuiApp, clean, matches


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
        self.assertIn("out of range", run("maze_animate", to=40).text)
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
    if sys.platform == "win32":     # os.kill(pid, 0) would terminate the process there
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259                        # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
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
        self.assertFalse(pid_alive(pid))

    def test_terminate_all_skips_exited_detached_process(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.remove_logs)
        manager.spawn_detached(Spawn([sys.executable, "-c", "pass"], "detached", "quick"))
        manager.detached[0][1].wait(10)
        with (mock.patch.object(actions, "_taskkill") as taskkill,
              mock.patch.object(os, "killpg", create=True) as killpg):
            self.assertEqual(manager.terminate_all(grace=0.2), [])
        killpg.assert_not_called()
        taskkill.assert_not_called()

    def test_terminate_all_overlaps_stubborn_processes(self):
        manager = actions.ProcessManager()
        self.addCleanup(manager.terminate_all, 0.2)
        for i in range(4):
            manager.spawn_detached(Spawn(STUBBORN.argv, "detached", f"stubborn{i}"))
        time.sleep(0.4)
        t0 = time.monotonic()
        manager.terminate_all(grace=0.5)
        self.assertLess(time.monotonic() - t0, 2.5)    # ~1 grace, not 4x; the overlap itself is pinned below
        self.assertEqual(manager.running(), [])

    def test_terminate_all_signals_concurrently(self):
        """Windows runs a taskkill per process; 4 x 0.3 s sequentially would take 1.2 s, concurrently ~0.3 s."""
        manager = actions.ProcessManager()
        for i in range(4):
            proc = mock.Mock(pid=100 + i)
            proc.poll.return_value = None
            proc.wait.side_effect = lambda timeout=None: None
            manager.detached.append((f"p{i}", proc, None))
        with (mock.patch.object(actions, "WINDOWS", True),
              mock.patch.object(actions, "_taskkill", side_effect=lambda proc: time.sleep(0.3)) as taskkill):
            t0 = time.monotonic()
            self.assertEqual(manager.terminate_all(grace=0.1), ["p0", "p1", "p2", "p3"])
            took = time.monotonic() - t0
        self.assertGreaterEqual(taskkill.call_count, 4)
        self.assertLess(took, 1.0, took)

    def test_lines_are_capped(self):
        code = f"for i in range({actions.MAX_LINES + 50}): print(i)"
        job = actions.ProcessManager().start_capture(Spawn([sys.executable, "-c", code], "capture", "t"))
        job.wait(20)
        lines, dropped = job.snapshot()
        self.assertEqual((len(lines), dropped), (actions.MAX_LINES, 50))
        self.assertEqual(lines[0], "50")
        self.assertIn("first 50 lines were dropped", job.result().text)


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


class PlatformTests(unittest.TestCase):
    def test_process_group_kwargs_match_platform(self):
        with mock.patch.object(actions, "WINDOWS", True), \
                mock.patch.object(actions.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True):
            self.assertEqual(actions._group_kwargs(), {"creationflags": 512})
        with mock.patch.object(actions, "WINDOWS", False):
            self.assertEqual(actions._group_kwargs(), {"start_new_session": True})

    def test_windows_kills_the_tree_only_while_the_leader_runs(self):
        live, gone = mock.Mock(pid=7), mock.Mock(pid=8)
        live.poll.return_value, gone.poll.return_value = None, 0
        with mock.patch.object(actions, "WINDOWS", True), mock.patch.object(actions, "_taskkill") as taskkill:
            self.assertTrue(actions._sigterm(live))
            self.assertFalse(actions._sigterm(gone))
            actions._sigkill(gone, 0.1)
        taskkill.assert_called_once_with(live)

    def test_summaries_for_route_and_path_results(self):
        self.assertEqual(actions.summarize(srv.shortest_route("Shkodër", "Korçë")),
                         "Shkodër → Lezhë → Tirana → Elbasan → Korçë · 267 km")
        self.assertEqual(actions.summarize({"path": [1, 2, 3], "doors_passed": 2}), "1 → 2 → 3 · 2 doors")
        long = list(range(1, 26))
        self.assertEqual(actions.summarize({"path": long, "doors_passed": 24}), "1 → 2 → 3 → … → 24 → 25 · 24 doors")
        self.assertEqual(actions.summarize({"path": [], "doors_passed": None}), "no path")
        self.assertEqual(actions.summarize({"error": "x", "path": [1]}), "")
        self.assertEqual(actions.summarize({"cities": {}}), "")

    def test_error_result_lists_the_valid_choices(self):
        head, body = actions.tool_parts(srv.get_roads("Nowhere"))
        self.assertIn("error: unknown city 'Nowhere'", head)
        self.assertIn("valid choices: ", head)
        self.assertIn("Tirana", head)
        self.assertEqual(body, "")

    def test_filter_match_is_case_and_accent_insensitive(self):
        act = actions.Action("k", "Group", "Shkodër route", "Durrës to Korçë", (), lambda values: None)
        for query in ("shkoder", "SHKODËR", "durres", "korce", "group", "  ROUTE ", ""):
            self.assertTrue(matches(act, query), query)
        self.assertFalse(matches(act, "tirana"))

    def test_clean_strips_escapes_and_controls(self):
        self.assertEqual(clean("\x1b[31mred\x1b[0m\x07 ok\r"), "red ok")
        self.assertEqual(clean("a\tb"), "a   b")


# --- headless UI ----------------------------------------------------------------

SIZE = (120, 40)
CAPTURE_SLEEPER = actions.Action("sleeper", "Test", "Sleeper", "Sleeps for 30 s.", (), lambda values: SLEEPER)


async def until(pilot, cond, timeout=15):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the UI")
        await pilot.pause(0.05)


def output_text(app):
    return "\n".join(strip.text for strip in app.query_one("#output").lines)


def rows(app):
    """[(id, text, disabled)] of the action list; group headers have id None."""
    listing = app.query_one("#actions")
    return [(o.id, str(o.prompt).strip(), o.disabled) for o in (listing.get_option_at_index(i)
                                                                for i in range(listing.option_count))]


async def select(app, pilot, key):
    listing = app.query_one("#actions")
    listing.highlighted = next(i for i, (k, _, _) in enumerate(rows(app)) if k == key)
    await until(pilot, lambda: app.action is not None and app.action.key == key and app.form is not None
                and app.form.is_mounted and len(app.form.children) >= len(app.action.options))
    await pilot.pause()


class UiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)     # debug mode makes Textual's loop several times slower

    def setUp(self):
        hub.stop()
        self.manager = actions.ProcessManager()
        self.addCleanup(self.manager.terminate_all, 0.2)
        self.addCleanup(hub.stop)

    def app(self, *extra):
        app = TuiApp(self.manager)
        for action in extra:
            app.acts = [*app.acts, action]
            app.by_key[action.key] = action
        return app

    async def test_lists_every_action_grouped(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            listed = rows(app)
            self.assertEqual([k for k, _, _ in listed if k], [a.key for a in registry()])
            headers = [t for k, t, disabled in listed if k is None and disabled]
            groups = list(dict.fromkeys(a.group for a in registry()))
            self.assertEqual(headers, [g.upper() for g in groups])
            self.assertEqual(app.theme, "matrix")
            self.assertEqual(app.current_theme.background, "#000000")
            self.assertEqual(app.current_theme.primary, "#00FF41")
            self.assertEqual(app.action.key, "list_cities")      # first action is selected on start
            self.assertIs(app.focused, app.query_one("#actions"))

    async def test_filter_narrows_the_list_accent_insensitively(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("slash")
            self.assertIs(app.focused, app.query_one("#filter"))
            await pilot.press(*"MAZE")
            await pilot.pause()
            keys = [k for k, _, _ in rows(app) if k]
            self.assertTrue(keys)
            self.assertLess(len(keys), len(registry()))
            self.assertIn("maze_animate", keys)
            self.assertNotIn("cities_draw", keys)
            for key in keys:
                a = actions.find(key)
                self.assertIn("maze", f"{a.title} {a.group} {a.key} {a.description}".lower())
            self.assertIsNotNone(app.action)
            app.query_one("#filter").value = "zzzz-nothing"
            await pilot.pause()
            self.assertEqual([k for k, _, _ in rows(app)], [None])
            self.assertIsNone(app.action)
            self.assertTrue(app.query_one("#run").disabled)
            app.query_one("#filter").value = ""
            await pilot.pause()
            self.assertEqual(len([k for k, _, _ in rows(app) if k]), len(registry()))

    async def test_typing_in_the_filter_does_not_trigger_keys(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("slash", "q", "question_mark", "/")
            await pilot.pause()
            self.assertEqual(app.query_one("#filter").value, "q?/")
            self.assertNotIsInstance(app.screen, HelpScreen)
            self.assertFalse(app._quitting)

    async def test_f1_toggles_help_while_typing(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("slash", "f1")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertEqual(app.query_one("#filter").value, "")
            await pilot.press("f1")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)

    async def test_selecting_builds_the_form_widgets(self):
        from textual.widgets import Input, Select, Switch
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await select(app, pilot, "trace_maze")
            f = app.form.fields
            self.assertEqual(list(f), ["from_room", "to_room", "detail"])
            self.assertIsInstance(f["from_room"][1], Input)
            self.assertEqual((f["from_room"][1].value, f["to_room"][1].value), (str(srv.ENTRANCE), str(srv.EXIT)))
            self.assertIsInstance(f["detail"][1], Switch)
            self.assertFalse(f["detail"][1].value)
            await select(app, pilot, "shortest_route")
            f = app.form.fields
            self.assertIsInstance(f["from_city"][1], Select)
            self.assertEqual((f["from_city"][1].value, f["to_city"][1].value), ("Shkodër", "Korçë"))
            await select(app, pilot, "cities_animate")
            kinds = {name: type(w) for name, (_, w, _) in app.form.fields.items()}
            self.assertEqual(kinds, {"from": Select, "to": Select, "fps": Input, "show": Switch, "out": Input})
            await select(app, pilot, "run_tests")
            self.assertEqual(app.form.fields, {})
            self.assertIn("Run tests", str(app.query_one("#title").content))

    async def test_invalid_int_shows_inline_error_and_does_not_run(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await select(app, pilot, "trace_maze")
            _, field, error = app.form.fields["from_room"]
            self.assertFalse(error.display)
            field.value = "99"
            await pilot.pause()
            self.assertTrue(error.display)
            self.assertIn("out of range", str(error.content))
            with mock.patch.object(actions, "execute") as execute:
                await pilot.press("ctrl+r")
                await pilot.pause()
                execute.assert_not_called()
            self.assertFalse(app._busy)
            self.assertEqual(output_text(app).strip(), "")
            self.assertIs(app.focused, field)                  # focus jumps to the bad field
            field.value = "abc"
            await pilot.pause()
            self.assertIn("not a whole number", str(error.content))
            field.value = "3"
            await pilot.pause()
            self.assertFalse(error.display)
            await pilot.press("ctrl+r")
            await until(pilot, lambda: "doors_passed" in output_text(app))

    async def test_required_blank_field_is_an_error(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await select(app, pilot, "cities_animate")
            _, field, error = app.form.fields["fps"]
            field.value = ""
            await pilot.pause()
            self.assertIn("required", str(error.content))

    async def test_run_mcp_tool_shows_result_in_output(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertEqual(app.action.key, "list_cities")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: "Shkodër" in output_text(app) and not app._busy)
            self.assertIn("Korçë", output_text(app))
            await pilot.pause(0.3)
            self.assertIn("list_cities: OK", str(app.query_one("#runstatus").content))
            await pilot.press("ctrl+l")
            await pilot.pause()
            self.assertEqual(output_text(app).strip(), "")

    async def test_enter_on_list_opens_form_or_runs_directly(self):
        from textual.widgets import Input
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await select(app, pilot, "trace_maze")
            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.focused, app.form.fields["from_room"][1])
            self.assertIsInstance(app.focused, Input)
            await pilot.press("escape")                         # nothing running: back to the list
            self.assertIs(app.focused, app.query_one("#actions"))
            await select(app, pilot, "live_stop")                # no options: Enter runs it
            await pilot.press("enter")
            await until(pilot, lambda: "not running" in output_text(app))

    async def test_escape_cancels_a_running_capture_job(self):
        app = self.app(CAPTURE_SLEEPER)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await select(app, pilot, "sleeper")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: app._job is not None and app._job._proc is not None)
            job = app._job
            pid = job._proc.pid
            self.assertTrue(app._busy)
            await pilot.pause(0.3)
            self.assertIn("Running", str(app.query_one("#runstatus").content))
            await pilot.press("escape")
            await until(pilot, lambda: not app._busy)
            self.assertTrue(job.done and job.cancelled)
            self.assertIn("[cancelled]", output_text(app))
            self.assertIn("cancelled", str(app.query_one("#runstatus").content))
            await until(pilot, lambda: not pid_alive(pid), 5)
            await pilot.press("ctrl+r")                         # can run again after a cancel
            await until(pilot, lambda: app._job is not None)
            await pilot.press("escape")
            await until(pilot, lambda: not app._busy)

    async def test_second_run_is_refused_while_busy(self):
        app = self.app(CAPTURE_SLEEPER)
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "sleeper")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: app._job is not None)
            with mock.patch.object(actions, "execute") as execute:
                await pilot.press("ctrl+r")
                await pilot.pause()
                execute.assert_not_called()

    async def test_capture_output_streams_and_reports_exit_code(self):
        job_spec = Spawn([sys.executable, "-c", "print('héllo'); print('error: boom'); raise SystemExit(3)"],
                         "capture", "printer")
        printer = actions.Action("printer", "Test", "Printer", "Prints.", (), lambda values: job_spec)
        app = self.app(printer)
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "printer")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: not app._busy and "[exit code 3]" in output_text(app))
            self.assertIn("héllo", output_text(app))
            await pilot.pause(0.3)
            self.assertIn("exit code 3", str(app.query_one("#runstatus").content))

    async def test_blank_lines_of_subprocess_output_are_kept(self):
        spec = Spawn([sys.executable, "-c", "print('one'); print(); print(); print('two')"], "capture", "blanks")
        blanks = actions.Action("blanks", "Test", "Blanks", "Prints blank lines.", (), lambda values: spec)
        app = self.app(blanks)
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "blanks")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: not app._busy and "[exit code 0]" in output_text(app))
            lines = [line.strip() for line in output_text(app).splitlines()]
            i = lines.index("one")
            self.assertEqual(lines[i:i + 4], ["one", "", "", "two"])

    async def test_result_rendering_summary_json_and_separator(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "shortest_route")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: not app._busy and "total_km" in output_text(app))
            text = output_text(app)
            self.assertIn("shortest_route", text.splitlines()[0])             # separator rule names the action
            self.assertIn("Shkodër → Lezhë → Tirana → Elbasan → Korçë · 267 km", text)
            self.assertLess(text.index("267 km"), text.index("total_km"))     # summary comes first
            await select(app, pilot, "find_path")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: not app._busy and "doors_passed" in output_text(app))
            text = output_text(app)
            self.assertIn("267 km", text)                                      # history is kept
            self.assertIn("find_path", text)
            self.assertRegex(text, r"1 → .* → \d+ · \d+ doors")

    async def test_error_result_is_shown_in_the_error_colour_with_choices(self):
        bad = actions.Action("bad", "Test", "Bad", "Always fails.", (), lambda values: actions.Result(
            *(lambda d: (actions.format_tool_result(d), False, d, "", *actions.tool_parts(d)))(srv.get_roads("Nowhere"))))
        app = self.app(bad)
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "bad")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: not app._busy and "valid choices" in output_text(app))
            self.assertIn("unknown city 'Nowhere'", output_text(app))
            self.assertIn("Tirana", output_text(app))
            await pilot.pause(0.3)
            self.assertIn("failed", str(app.query_one("#runstatus").content))

    async def test_render_failure_does_not_leave_the_ui_busy(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            with mock.patch.object(TuiApp, "_show", side_effect=ValueError("render boom")):
                await pilot.press("ctrl+r")
                await until(pilot, lambda: not app._busy)
            self.assertIn("render boom", output_text(app))
            await pilot.pause(0.3)
            self.assertIn("failed", str(app.query_one("#runstatus").content))

    async def test_modal_blocks_app_level_bindings(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._outlog.write("keep me")
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            with mock.patch.object(actions, "execute") as execute:
                await pilot.press("ctrl+r", "ctrl+l", "slash")
                await pilot.pause()
                execute.assert_not_called()
            self.assertFalse(app._busy)
            self.assertIn("keep me", output_text(app))                      # ctrl+l did not clear
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)
            await pilot.press("ctrl+l")
            await pilot.pause()
            self.assertEqual(output_text(app).strip(), "")                  # works again once closed

    async def test_question_mark_opens_help(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertIn("Ctrl+R", " ".join(str(w.content) for w in app.screen.query("Static")))
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)
            await pilot.press("question_mark", "question_mark")      # second press closes it again
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)

    async def test_q_quits_and_terminates_processes(self):
        app = self.app(CAPTURE_SLEEPER)
        detached = Spawn([sys.executable, "-c", "import time; time.sleep(60)"], "detached", "bg sleeper")
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "sleeper")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: app._job is not None and app._job._proc is not None)
            self.manager.spawn_detached(detached)
            pids = [app._job._proc.pid, self.manager.detached[0][1].pid]
            self.assertTrue(all(pid_alive(p) for p in pids))
            log_dir = self.manager._dir
            await pilot.press("q")
            await until(pilot, lambda: app._exit, 15)
        self.assertEqual(app.return_code, 0)
        self.assertFalse(any(pid_alive(p) for p in pids))
        self.assertFalse(log_dir.exists())
        self.assertEqual(app.notices, ["Stopped background processes: bg sleeper, sleeper"])

    async def test_ctrl_q_quits_even_while_typing(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("slash", "a", "ctrl+q")
            await until(pilot, lambda: app._exit)
        self.assertTrue(app._cleaned)

    async def test_request_exit_after_the_loop_closed_raises_system_exit(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
        closed = asyncio.new_event_loop()
        closed.close()
        app._loop = closed
        with self.assertRaises(SystemExit) as caught:
            app.request_exit(143)
        self.assertEqual(caught.exception.code, 143)
        app._loop = None
        with self.assertRaises(SystemExit):
            app.request_exit(1)

    async def test_ctrl_c_quits(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+c")
            await until(pilot, lambda: app._exit)

    async def test_signal_request_exits_cleanly_with_the_code(self):
        app = self.app(CAPTURE_SLEEPER)
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "sleeper")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: app._job is not None and app._job._proc is not None)
            pid = app._job._proc.pid
            app.request_exit(143)
            await until(pilot, lambda: app._exit)
        self.assertEqual(app.return_code, 143)
        self.assertFalse(pid_alive(pid))

    async def test_viewer_started_from_the_tui_is_stopped_on_exit(self):
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "live_start")
            app.form.fields["port"][1].value = "0"
            await pilot.press("ctrl+r")
            await until(pilot, lambda: hub.url() is not None and not app._busy)
            url = hub.url()
            await pilot.pause(0.3)
            self.assertIn(url, str(app.query_one("#statusbar").content))
            self.assertIn(url, output_text(app))
            await pilot.press("q")
            await until(pilot, lambda: app._exit)
        self.assertIsNone(hub.url())
        self.assertEqual(app.notices, [f"Stopped the live viewer ({url})."])

    async def test_restarted_viewer_is_stopped_on_exit(self):
        hub.start(port=0)                               # already running when the TUI starts
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await select(app, pilot, "live_stop")
            await pilot.press("ctrl+r")
            await until(pilot, lambda: hub.url() is None and not app._busy)
            await select(app, pilot, "live_start")
            app.form.fields["port"][1].value = "0"
            await pilot.press("ctrl+r")
            await until(pilot, lambda: hub.url() is not None and not app._busy)
            url = hub.url()
            await pilot.press("q")
            await until(pilot, lambda: app._exit)
        self.assertIsNone(hub.url())
        self.assertEqual(app.notices, [f"Stopped the live viewer ({url})."])

    async def test_cleanup_leaves_a_viewer_that_was_already_running(self):
        hub.start(port=0)
        app = self.app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("q")
            await until(pilot, lambda: app._exit)
        self.assertIsNotNone(hub.url())
        self.assertEqual(app.notices, [])


POSIX_ONLY = unittest.skipIf(sys.platform == "win32", "Textual's POSIX driver draws on sys.__stderr__")


class MainTests(unittest.TestCase):
    def test_refuses_without_a_terminal(self):
        with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: False)):
            self.assertEqual(app_module.main(), 2)

    def test_stderr_goes_to_a_log_while_the_ui_runs(self):
        with app_module.stderr_to_log() as log:
            os.write(2, b"background thread noise\n")
        self.assertEqual(log.read_text(), "background thread noise\n")
        shutil_rmtree(log.parent)

    @POSIX_ONLY
    def test_posix_driver_stream_stays_on_the_real_terminal(self):
        """Textual's LinuxDriver writes the UI to sys.__stderr__: it must not follow fd 2 into the log."""
        import tempfile
        with tempfile.TemporaryFile() as fake_terminal:
            keep = os.dup(2)
            os.dup2(fake_terminal.fileno(), 2)        # stand-in for the tty on fd 2
            try:
                original = sys.__stderr__
                with app_module.stderr_to_log() as log:
                    ui = sys.__stderr__               # what the driver grabs at start-up
                    self.assertIsNot(ui, original)
                    self.assertNotEqual(ui.fileno(), 2)
                    ui.write("\x1b[?1049hUI frame")
                    ui.flush()
                    os.write(2, b"thread traceback\n")
                self.assertIs(sys.__stderr__, original)       # restored for the rest of the process
                os.write(2, b"after\n")
            finally:
                os.dup2(keep, 2)
                os.close(keep)
            fake_terminal.seek(0)
            self.assertEqual(fake_terminal.read(), b"\x1b[?1049hUI frameafter\n")    # UI + restore went to the tty
        self.assertEqual(log.read_text(), "thread traceback\n")                     # noise went to the log
        shutil_rmtree(log.parent)

    @unittest.skipUnless(sys.platform == "win32", "Windows branch")
    def test_windows_redirects_fd2_and_leaves_the_stream_object(self):
        original = sys.__stderr__
        with app_module.stderr_to_log() as log:
            self.assertIs(sys.__stderr__, original)
        shutil_rmtree(log.parent)


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
