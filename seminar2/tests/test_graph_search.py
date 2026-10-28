import tempfile
import unittest
from pathlib import Path

from seminar2.cities.graph import load_graph
from seminar2.graph_search import Graph, bfs, dijkstra
from seminar2.maze.maze import _read_config, _read_doors, load_maze

# A-C direct costs 10, but A-B-C costs 3.
WEIGHTED = {
    "A": {"B": 1, "C": 10},
    "B": {"A": 1, "C": 2},
    "C": {"A": 10, "B": 2},
    "X": {},
}
# 1-2-3-4 chain plus a shortcut 1-4.
UNWEIGHTED = {1: [2, 4], 2: [1, 3], 3: [2, 4], 4: [3, 1], 5: []}


def weighted_edges(node):
    return WEIGHTED[node].items()


def unweighted_edges(node):
    return ((n, 1) for n in sorted(UNWEIGHTED[node]))


class DijkstraTests(unittest.TestCase):
    def test_prefers_cheaper_multi_hop_route(self):
        self.assertEqual(dijkstra(weighted_edges, "A", "C"), (["A", "B", "C"], 3))

    def test_unreachable(self):
        self.assertEqual(dijkstra(weighted_edges, "A", "X"), (None, None))

    def test_start_equals_goal(self):
        self.assertEqual(dijkstra(weighted_edges, "A", "A"), (["A"], 0))


class BfsTests(unittest.TestCase):
    def test_fewest_edges(self):
        self.assertEqual(bfs(unweighted_edges, 1, 4), [1, 4])

    def test_unreachable(self):
        self.assertIsNone(bfs(unweighted_edges, 1, 5))

    def test_start_equals_goal(self):
        self.assertEqual(bfs(unweighted_edges, 1, 1), [1])


class GraphTests(unittest.TestCase):
    def test_weighted_shortest_path(self):
        g = Graph(WEIGHTED, weighted=True)
        self.assertEqual(g.shortest_path("A", "C"), (["A", "B", "C"], 3))
        self.assertEqual(g.shortest_path("A", "X"), (None, None))

    def test_unweighted_cost_is_edge_count(self):
        g = Graph(UNWEIGHTED, weighted=False)
        self.assertEqual(g.shortest_path(1, 3), ([1, 2, 3], 2))
        self.assertEqual(g.shortest_path(1, 1), ([1], 0))
        self.assertEqual(g.shortest_path(1, 5), (None, None))

    def test_is_connected(self):
        self.assertTrue(Graph({1: [2], 2: [1]}, weighted=False).is_connected())
        self.assertFalse(Graph(UNWEIGHTED, weighted=False).is_connected())
        self.assertFalse(Graph(WEIGHTED, weighted=True).is_connected())
        self.assertFalse(Graph({}, weighted=False).is_connected())

    def test_container_protocol(self):
        g = Graph(UNWEIGHTED, weighted=False)
        self.assertIn(1, g)
        self.assertNotIn(9, g)
        self.assertEqual(len(g), 5)
        self.assertEqual(list(g), [1, 2, 3, 4, 5])


class RealDataTests(unittest.TestCase):
    def test_shkoder_to_korce(self):
        city_graph = Graph(load_graph(), weighted=True)
        self.assertEqual(
            city_graph.shortest_path("Shkodër", "Korçë"),
            (["Shkodër", "Lezhë", "Tirana", "Elbasan", "Korçë"], 267),
        )

    def test_maze_entrance_to_exit(self):
        maze_graph = Graph(load_maze().adjacency, weighted=False)
        path, doors = maze_graph.shortest_path(1, 25)
        self.assertEqual(path, [1, 2, 3, 8, 13, 18, 17, 16, 21, 22, 23, 24, 25])
        self.assertEqual(doors, 12)


class LoaderLineNumberTests(unittest.TestCase):
    """csv skips blank lines, so error line numbers must come from the reader."""

    def load(self, loader, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text(text, encoding="utf-8", newline="")
            with self.assertRaises(ValueError) as cm:
                loader(path)
        return str(cm.exception)

    def test_cities_error_names_the_real_line(self):
        message = self.load(load_graph, "city_a,city_b,km\nA,B,5\n\n\nB,C,x\n")
        self.assertIn("line 5", message)

    def test_doors_error_names_the_real_line(self):
        message = self.load(_read_doors, "room_a,room_b\n1,2\n\n3,x\n")
        self.assertIn("line 4", message)

    def test_config_error_names_the_real_line(self):
        message = self.load(_read_config, "key,value\nrooms,25\n\nentrance,x\n")
        self.assertIn("line 4", message)


if __name__ == "__main__":
    unittest.main()
