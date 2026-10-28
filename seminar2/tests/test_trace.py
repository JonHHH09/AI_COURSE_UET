import json
import unittest

from seminar2.cities.graph import load_graph
from seminar2.graph_search import (
    Graph,
    bfs,
    bfs_steps,
    build_steps,
    dijkstra,
    dijkstra_steps,
)
from seminar2.layout import CITY_POS, maze_position
from seminar2.maze.maze import load_maze
from seminar2.tests.test_graph_search import (
    UNWEIGHTED,
    WEIGHTED,
    unweighted_edges,
    weighted_edges,
)

# B is reached first via A (cost 5), then cheaper via C (cost 2+1); the old
# heap entry for B stays behind and is skipped when popped.
STALE = {
    "A": {"B": 5, "C": 2},
    "B": {"A": 5, "C": 1, "D": 5},
    "C": {"A": 2, "B": 1},
    "D": {"B": 5},
}


def check_events(test, events):
    test.assertTrue(events)
    for e in events:
        test.assertIsInstance(e["message"], str)
        test.assertTrue(e["message"])
        json.dumps(e)
    test.assertIn(events[-1]["type"], ("found", "fail"))
    test.assertEqual([e["type"] for e in events if e["type"] in ("found", "fail")],
                     [events[-1]["type"]])


class DijkstraStepsTests(unittest.TestCase):
    def test_agree_with_dijkstra(self):
        for goal in WEIGHTED:
            events = list(dijkstra_steps(weighted_edges, "A", goal))
            check_events(self, events)
            path, cost = dijkstra(weighted_edges, "A", goal)
            last = events[-1]
            if path is None:
                self.assertEqual(last["type"], "fail")
            else:
                self.assertEqual((last["path"], last["cost"]), (path, cost))

    def test_stale_skip_and_not_improved(self):
        events = list(dijkstra_steps(lambda n: STALE[n].items(), "A", "D"))
        check_events(self, events)
        skips = [e for e in events if e["type"] == "skip"]
        self.assertTrue(skips)
        self.assertEqual(skips[0]["node"], "B")
        self.assertEqual(skips[0]["cost"], 5)
        self.assertTrue(any(e["type"] == "relax" and not e["improved"] for e in events))
        self.assertEqual(events[-1]["path"], ["A", "C", "B", "D"])

    def test_relax_fields_and_independent_state(self):
        events = list(dijkstra_steps(weighted_edges, "A", "C"))
        relax = next(e for e in events if e["type"] == "relax")
        self.assertEqual((relax["from"], relax["to"], relax["edge"], relax["new_cost"],
                          relax["old_cost"], relax["improved"]), ("A", "B", 1, 1, None, True))
        self.assertEqual(events[0]["prev"], {"A": None})
        self.assertEqual(events[0]["dist"], {"A": 0})
        self.assertEqual(events[0]["frontier"], [[0, "A"]])

    def test_real_data(self):
        g = Graph(load_graph(), weighted=True)
        events = list(g.search_steps("Shkodër", "Korçë"))
        check_events(self, events)
        self.assertEqual(events[-1]["cost"], 267)
        self.assertEqual(events[-1]["path"], g.shortest_path("Shkodër", "Korçë")[0])


class BfsStepsTests(unittest.TestCase):
    def test_agree_with_bfs(self):
        for goal in UNWEIGHTED:
            events = list(bfs_steps(unweighted_edges, 1, goal))
            check_events(self, events)
            path = bfs(unweighted_edges, 1, goal)
            if path is None:
                self.assertEqual(events[-1]["type"], "fail")
            else:
                self.assertEqual(events[-1]["path"], path)
                self.assertEqual(events[-1]["cost"], len(path) - 1)

    def test_discover_not_new(self):
        events = list(bfs_steps(unweighted_edges, 1, 3))
        self.assertTrue(any(e["type"] == "discover" and not e["new"] for e in events))
        self.assertTrue(any(e["type"] == "discover" and e["new"] for e in events))

    def test_real_data(self):
        m = load_maze()
        g = Graph(m.adjacency, weighted=False)
        events = list(g.search_steps(m.entrance, m.exit))
        check_events(self, events)
        self.assertEqual(events[-1]["cost"], 12)
        self.assertEqual(events[-1]["path"], g.shortest_path(m.entrance, m.exit)[0])

    def test_one_door_is_singular(self):
        adj = {1: [2], 2: [1]}
        events = list(bfs_steps(lambda n: ((m, 1) for m in adj[n]), 1, 2))
        messages = [e["message"] for e in events]
        self.assertIn("Discover 2 from 1: new, 1 door; add it to the queue.", messages)
        self.assertFalse(any("1 doors" in m for m in messages))


class BuildStepsTests(unittest.TestCase):
    def test_small_with_isolated_node(self):
        events = list(build_steps(WEIGHTED, True))
        check_events_no_end(self, events)
        edges = [e for e in events if e["type"] == "add_edge"]
        self.assertEqual(len(edges), 3)
        self.assertEqual(events[-1]["type"], "add_node")
        self.assertEqual(events[-1]["node"], "X")
        self.assertEqual((events[-1]["nodes"], events[-1]["edges"]), (4, 3))

    def test_real_cities(self):
        adj = load_graph()
        events = list(build_steps(adj, True))
        check_events_no_end(self, events)
        self.assertEqual((events[-1]["nodes"], events[-1]["edges"]), (8, 9))
        self.assertEqual(sum(e["type"] == "add_edge" for e in events), 9)
        edge = next(e for e in events if e["type"] == "add_edge")
        self.assertEqual(edge["cost"], adj[edge["a"]][edge["b"]])

    def test_real_maze(self):
        m = load_maze()
        events = list(Graph(m.adjacency, weighted=False).build_steps())
        check_events_no_end(self, events)
        self.assertEqual((events[-1]["nodes"], events[-1]["edges"]), (25, 31))
        self.assertTrue(all(e["cost"] == 1 for e in events if e["type"] == "add_edge"))


def check_events_no_end(test, events):
    pairs = set()
    nodes = set()
    for e in events:
        test.assertTrue(e["message"])
        json.dumps(e)
        if e["type"] == "add_node":
            test.assertNotIn(e["node"], nodes)
            nodes.add(e["node"])
        else:
            key = frozenset((e["a"], e["b"]))
            test.assertNotIn(key, pairs)
            pairs.add(key)
            test.assertLessEqual({e["a"], e["b"]}, nodes)


class GraphStepsTests(unittest.TestCase):
    def test_unknown_node_single_fail(self):
        for g, args in ((Graph(WEIGHTED, True), ("A", "nope")),
                        (Graph(UNWEIGHTED, False), (99, 1))):
            events = list(g.search_steps(*args))
            self.assertEqual([e["type"] for e in events], ["fail"])
            check_events(self, events)


class LayoutTests(unittest.TestCase):
    def test_positions(self):
        self.assertEqual(set(CITY_POS), set(load_graph()))
        self.assertEqual(maze_position(1, 5), (0, 0))
        self.assertEqual(maze_position(25, 5), (4, -4))
