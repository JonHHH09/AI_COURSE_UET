"""Tests for the step-by-step animation helper (Agg backend, no windows)."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from seminar2 import animation
from seminar2.cities import animate as cities_animate
from seminar2.cities.graph import load_graph
from seminar2.graph_search import Graph
from seminar2.maze import animate as maze_animate
from seminar2.maze.maze import load_maze

HOLD = 3


def city_scene():
    return cities_animate.make_scene(load_graph(), "Shkodër", "Korçë")


def maze_scene():
    maze = load_maze()
    return maze_animate.make_scene(maze, maze.entrance, maze.exit)


class FrameBuilderTest(unittest.TestCase):
    def check_counts(self, scene):
        graph = Graph(scene.adjacency, scene.weighted)
        build = len(list(graph.build_steps()))
        search = len(list(graph.search_steps(scene.start, scene.goal)))
        frames = animation.build_frames(scene, hold=HOLD)
        self.assertEqual(len(frames), build + search + HOLD)
        self.assertEqual([f["phase"] for f in frames].count(1), build)
        return frames

    def test_cities_frame_count_and_final_path(self):
        frames = self.check_counts(city_scene())
        last = frames[-1]
        self.assertEqual(last["path"], ["Shkodër", "Lezhë", "Tirana", "Elbasan", "Korçë"])
        self.assertIn("267 km", last["title"])
        self.assertEqual(frames[-HOLD - 1], last)

    def test_maze_frame_count_and_final_path(self):
        frames = self.check_counts(maze_scene())
        last = frames[-1]
        self.assertEqual(len(last["path"]) - 1, 12)
        self.assertEqual((last["path"][0], last["path"][-1]), (1, 25))
        self.assertIn("12 doors", last["title"])

    def test_build_phase_grows_one_item_at_a_time(self):
        frames = animation.build_frames(city_scene())
        build = [f for f in frames if f["phase"] == 1]
        sizes = [len(f["nodes"]) + len(f["edges"]) for f in build]
        self.assertEqual(sizes, list(range(1, len(build) + 1)))
        self.assertEqual(build[0]["heading"], "1. Building the graph from the CSV")
        self.assertEqual(frames[len(build)]["heading"], "2. Dijkstra search")

    def test_search_roles(self):
        frames = animation.build_frames(city_scene())
        pops = [f for f in frames if f["kind"] == "pop"]
        self.assertEqual(pops[0]["roles"]["Shkodër"], "current")
        relax = next(f for f in frames if f["kind"] == "relax")
        self.assertIsNotNone(relax["highlight"])
        self.assertEqual(relax["roles"][relax["highlight"][0]], "current")


class SingularTest(unittest.TestCase):
    def test_one_door_and_one_room_or_city_are_singular(self):
        adj = {1: [2], 2: [1]}
        scene = animation.Scene(adjacency=adj, weighted=False, pos={1: (0, 0), 2: (1, 0)},
                                start=1, goal=2, title="t", algorithm="BFS", unit="doors")
        frames = animation.build_frames(scene)
        self.assertEqual(frames[-1]["title"], "Shortest path 1 → 2: 1 door")
        fig, ax, panel = animation.make_figure(scene)
        animation.render_frame(ax, panel, scene, frames[0])
        self.assertIn("1 room, 0 doors so far", [t.get_text() for t in panel.texts])
        plt.close(fig)

        scene = city_scene()
        fig, ax, panel = animation.make_figure(scene)
        animation.render_frame(ax, panel, scene, animation.build_frames(scene)[0])
        self.assertIn("1 city, 0 roads so far", [t.get_text() for t in panel.texts])
        plt.close(fig)


class HelpersTest(unittest.TestCase):
    def test_city_lookup_ignores_accents_and_case(self):
        cities = list(load_graph())
        self.assertEqual(cities_animate.resolve_city("durres", cities), "Durrës")
        self.assertEqual(cities_animate.resolve_city("KORCE", cities), "Korçë")
        with self.assertRaises(ValueError) as ctx:
            cities_animate.resolve_city("Paris", cities)
        self.assertIn("Shkodër", str(ctx.exception))

    def test_room_lookup(self):
        maze = load_maze()
        self.assertEqual(maze_animate.parse_room("7", maze, "--from"), 7)
        for bad in ("0", "26", "x"):
            with self.assertRaises(ValueError):
                maze_animate.parse_room(bad, maze, "--to")

    def test_cli_errors_exit_non_zero(self):
        self.assertNotEqual(cities_animate.main(["--from", "Paris"]), 0)
        self.assertNotEqual(maze_animate.main(["--to", "99"]), 0)

    def test_cli_summary_prints_on_a_cp1252_stdout(self):
        # piped stdout on Windows is cp1252, which cannot encode the arrow
        for module, argv in ((cities_animate, []), (maze_animate, [])):
            raw = io.BytesIO()
            out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
            with mock.patch.object(animation, "save_gif", return_value=0), redirect_stdout(out):
                self.assertEqual(module.main(argv), 0)
            out.flush()
            self.assertIn("->", raw.getvalue().decode("cp1252"))


class GifTest(unittest.TestCase):
    def test_save_small_gif(self):
        scene = city_scene()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "route.gif"
            count = animation.save_gif(scene, out, fps=1, dpi=30)
            self.assertTrue(out.read_bytes().startswith(b"GIF8"))
            self.assertEqual(count, len(scene.frames))


if __name__ == "__main__":
    unittest.main()
