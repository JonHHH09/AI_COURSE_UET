import json
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from seminar2 import mcp_server as srv
from seminar2.live import hub


class ToolTests(unittest.TestCase):
    def setUp(self):
        hub.stop()

    tearDown = setUp

    def test_existing_tools_unchanged(self):
        r = srv.shortest_route("Shkodër", "Korçë")
        self.assertEqual(list(r), ["from", "to", "route", "total_km"])
        self.assertEqual((r["route"], r["total_km"]),
                         (["Shkodër", "Lezhë", "Tirana", "Elbasan", "Korçë"], 267))
        p = srv.find_path()
        self.assertEqual(list(p), ["from", "to", "path", "doors_passed"])
        self.assertEqual(p["doors_passed"], 12)

    def test_trace_route_accent_insensitive(self):
        r = srv.trace_route("shkoder", "KORCE")
        self.assertEqual((r["from"], r["to"], r["algorithm"]), ("Shkodër", "Korçë", "Dijkstra"))
        self.assertEqual(r["total_km"], 267)
        self.assertEqual(r["route"], srv.shortest_route("Shkodër", "Korçë")["route"])
        self.assertTrue(all(isinstance(m, str) for m in r["build"] + r["steps"]))
        self.assertTrue(r["steps"][0].startswith("Start at Shkodër"))
        self.assertIsNone(r["live_url"])
        json.dumps(r)

    def test_trace_route_detail(self):
        r = srv.trace_route("Shkoder", "Korce", detail=True)
        self.assertEqual(r["steps"][-1]["type"], "found")
        self.assertIn("frontier", r["steps"][0])
        self.assertEqual(r["build"][0]["type"], "add_node")
        json.dumps(r)

    def test_trace_route_errors(self):
        r = srv.trace_route("Atlantis", "Tirana")
        self.assertIn("Atlantis", r["error"])
        self.assertIn("Tirana", r["cities"])
        self.assertIn("error", srv.trace_route("Tirana", "Nowhere"))

    def test_trace_maze_defaults(self):
        r = srv.trace_maze()
        self.assertEqual((r["from"], r["to"], r["algorithm"]), (srv.ENTRANCE, srv.EXIT, "BFS"))
        self.assertEqual(r["doors_passed"], 12)
        self.assertEqual(r["path"], srv.find_path()["path"])
        self.assertTrue(all(isinstance(m, str) for m in r["build"] + r["steps"]))
        self.assertIsNone(r["live_url"])
        json.dumps(srv.trace_maze(detail=True))

    def test_trace_maze_bad_room(self):
        self.assertEqual(srv.trace_maze(0, 5), srv.find_path(0, 5))
        self.assertIn("error", srv.trace_maze(1, 99))

    def test_live_viewer_not_running(self):
        r = srv.live_viewer()
        self.assertEqual(r["error"], "live viewer is not running")
        self.assertIn("hint", r)

    def test_tools_publish_when_hub_runs(self):
        url = hub.start(port=0)
        self.assertEqual(srv.live_viewer(), {"url": url})
        self.assertEqual(srv.trace_route("Tirana", "Vlorë")["live_url"], url)
        srv.shortest_route("Tirana", "Fier")
        srv.find_path(1, 5)
        srv.trace_maze(1, 5)
        srv.shortest_route("Atlantis", "Fier")   # errors publish nothing
        srv.find_path(1, 99)
        with urllib.request.urlopen(url + "sessions", timeout=5) as r:
            history = json.load(r)
        self.assertEqual([s["tool"] for s in history],
                         ["trace_route", "shortest_route", "find_path", "trace_maze"])

    def test_plain_tools_skip_session_building_when_hub_stopped(self):
        with mock.patch.object(srv, "city_session") as cs, mock.patch.object(srv, "maze_session") as ms:
            self.assertEqual(srv.shortest_route("Shkodër", "Korçë")["total_km"], 267)
            self.assertEqual(srv.find_path()["doors_passed"], 12)
        cs.assert_not_called()
        ms.assert_not_called()

    def test_plain_tools_build_one_session_each_when_hub_runs(self):
        hub.start(port=0)
        with mock.patch.object(srv, "city_session", wraps=srv.city_session) as cs, \
                mock.patch.object(srv, "maze_session", wraps=srv.maze_session) as ms:
            self.assertEqual(srv.shortest_route("Shkodër", "Korçë")["total_km"], 267)
            self.assertEqual(srv.find_path()["doors_passed"], 12)
        self.assertEqual((cs.call_count, ms.call_count), (1, 1))


class ServerProcessTests(unittest.TestCase):
    def test_exits_when_stdio_client_closes(self):
        root = Path(__file__).resolve().parents[2]
        env = dict(os.environ, SEMINAR2_LIVE_PORT="0")
        proc = subprocess.Popen([sys.executable, str(root / "seminar2" / "mcp_server.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=root)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        try:
            self.assertIn(b"live viewer: http://", proc.stderr.readline())   # hub is up
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.fail("server process still alive 10 s after stdin closed")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
