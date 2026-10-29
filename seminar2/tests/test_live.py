import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from seminar2.cities.graph import load_graph
from seminar2.live import hub
from seminar2.live.session import city_session, maze_session
from seminar2.maze.maze import load_maze

CITIES = load_graph()
MAZE = load_maze()


def city():
    return city_session(CITIES, "Shkodër", "Korçë", "shortest_route")


def maze():
    return maze_session(MAZE.adjacency, MAZE.entrance, MAZE.exit, MAZE.entrance, MAZE.exit, "find_path")


class SessionTests(unittest.TestCase):
    def test_city_session(self):
        s = city()
        json.dumps(s)
        self.assertEqual((s["problem"], s["algorithm"], s["weighted"]), ("cities", "Dijkstra", True))
        self.assertEqual(s["result"], {"path": ["Shkodër", "Lezhë", "Tirana", "Elbasan", "Korçë"],
                                       "cost": 267, "unit": "km"})
        self.assertEqual({n["id"] for n in s["nodes"]}, set(CITIES))
        self.assertTrue(all(isinstance(n["x"], (int, float)) and isinstance(n["y"], (int, float))
                            for n in s["nodes"]))
        roles = {n["id"]: n["role"] for n in s["nodes"]}
        self.assertEqual((roles["Shkodër"], roles["Korçë"]), ("start", "goal"))
        self.assertIn("Shkodër", s["title"])
        self.assertEqual(s["steps"][-1]["type"], "found")
        self.assertEqual(s["build"][-1]["edges"], 9)

    def test_maze_session(self):
        s = maze()
        json.dumps(s)
        self.assertEqual((s["problem"], s["algorithm"], s["weighted"]), ("maze", "BFS", False))
        self.assertEqual(s["result"]["cost"], 12)
        self.assertEqual(s["result"]["unit"], "doors")
        self.assertEqual({n["id"] for n in s["nodes"]}, {str(r) for r in MAZE.adjacency})
        roles = {n["id"]: n["role"] for n in s["nodes"]}
        self.assertEqual((roles["1"], roles["25"]), ("entrance", "exit"))
        self.assertEqual((s["nodes"][0]["x"], s["nodes"][0]["y"]), (0, 0))

    def test_ids_increase(self):
        self.assertLess(city()["id"], city()["id"])

    def test_ids_are_clock_based_and_json_safe(self):
        # a restarted server must not hand out ids a long-open browser tab has already seen
        i = city()["id"]
        self.assertGreater(i, 10**15)
        self.assertLess(i, 2**53)

    def test_unreachable_goal_has_no_path(self):
        s = city_session({"Shkodër": {}, "Korçë": {}}, "Shkodër", "Korçë", "t")
        self.assertEqual(s["result"]["path"], None)


class HubTests(unittest.TestCase):
    def setUp(self):
        self.url = hub.start(port=0)
        self.assertIsNotNone(self.url)

    def tearDown(self):
        hub.stop()

    def get(self, path):
        with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=5) as r:
            return r.status, r.headers, r.read()

    def test_index(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"EventSource", body)

    def test_url_and_second_start(self):
        self.assertEqual(hub.url(), self.url)
        self.assertEqual(hub.start(port=0), self.url)

    def test_publish_and_history(self):
        self.assertEqual(json.loads(self.get("/sessions")[2]), [])
        s = city()
        hub.publish(s)
        history = json.loads(self.get("/sessions")[2])
        self.assertEqual([h["id"] for h in history], [s["id"]])
        self.assertEqual(json.loads(self.get("/sessions/latest")[2])["id"], s["id"])

    def test_latest_empty_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/sessions/latest")
        cm.exception.close()
        self.assertEqual(cm.exception.code, 404)

    def test_history_is_bounded(self):
        for i in range(hub.HISTORY_LIMIT + 5):
            hub.publish({"id": i})
        history = json.loads(self.get("/sessions")[2])
        self.assertEqual(len(history), hub.HISTORY_LIMIT)
        self.assertEqual(history[-1]["id"], hub.HISTORY_LIMIT + 4)

    def test_sse_receives_session_published_after_connect(self):
        port = int(self.url.rsplit(":", 1)[1].strip("/"))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/events")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("text/event-stream", resp.getheader("Content-Type"))
        s = maze()
        deadline = time.time() + 5
        while not hub._clients and time.time() < deadline:   # handler registered after the response head
            time.sleep(0.01)
        hub.publish(s)
        data = None
        while time.time() < deadline:
            line = resp.fp.readline().decode()
            if line.startswith("data: "):
                data = json.loads(line[6:])
                break
        conn.close()
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], s["id"])
        self.assertEqual(data["result"]["cost"], 12)

    def test_publish_when_stopped_is_noop(self):
        hub.stop()
        hub.publish(city())
        self.assertIsNone(hub.url())
        self.url = hub.start(port=0)
        self.assertEqual(json.loads(self.get("/sessions")[2]), [])

    def test_busy_port_returns_none(self):
        hub.stop()
        first = hub.start(port=0)
        port = int(first.rsplit(":", 1)[1].strip("/"))
        with socket.socket() as blocker:
            hub.stop()
            blocker.bind(("127.0.0.1", port))
            blocker.listen()
            self.assertIsNone(hub.start(port=port))
        hub.start(port=0)

    def test_second_hub_cannot_share_a_running_hubs_port(self):
        # On Windows SO_REUSEADDR lets two listeners share a port, so the busy-port
        # fallback never fired when another seminar2 server already held 8765.
        port = int(self.url.rsplit(":", 1)[1].strip("/"))
        with self.assertRaises(OSError):
            hub._make_server("127.0.0.1", port).server_close()

    def test_slow_client_is_dropped(self):
        full = hub.queue.Queue(maxsize=2)
        with hub._lock:
            hub._clients.append(full)
        for i in range(3):
            hub.publish({"id": i})
        self.assertNotIn(full, hub._clients)
        self.assertIsNone(full.get_nowait())   # told to hang up


class PortFallbackTests(unittest.TestCase):
    def setUp(self):
        hub.stop()
        self.blocker = socket.socket()
        self.blocker.bind(("127.0.0.1", 0))
        self.blocker.listen()
        self.port = self.blocker.getsockname()[1]
        self.addCleanup(hub.stop)
        self.addCleanup(self.blocker.close)

    def test_busy_default_port_falls_back(self):
        env = {k: v for k, v in os.environ.items() if k != "SEMINAR2_LIVE_PORT"}
        real = hub._make_server
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(hub, "_make_server",
                                  lambda host, port: real(host, self.port if port == 8765 else port)):
            url = hub.start()
        self.assertIsNotNone(url)
        self.assertNotIn(f":{self.port}/", url)
        self.assertEqual(hub.url(), url)

    def test_busy_env_port_returns_none(self):
        with mock.patch.dict(os.environ, {"SEMINAR2_LIVE_PORT": str(self.port)}):
            self.assertIsNone(hub.start())
        self.assertIsNone(hub.url())

    def test_busy_explicit_port_returns_none(self):
        self.assertIsNone(hub.start(port=self.port))


class StandaloneTests(unittest.TestCase):
    def test_url_line_is_flushed_when_stdout_is_a_pipe(self):
        # a block-buffered pipe or log file would otherwise never show the URL
        env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
        proc = subprocess.Popen([sys.executable, "-m", "seminar2.live", "--no-browser", "--port", "0"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                cwd=Path(__file__).resolve().parents[2], text=True, encoding="utf-8")
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        line = []
        reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(15)
        self.assertTrue(line and line[0].startswith("Live viewer: http://127.0.0.1:"), line)


if __name__ == "__main__":
    unittest.main()
