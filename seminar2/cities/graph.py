"""Seminar 2, U1: intercity graph of 8 Albanian cities.

Undirected, weighted graph stored as an adjacency list.
Weights are approximate driving distances in km.
The roads live in seminar2/dataset/cities.csv and are read by load_graph().
"""

import csv
from pathlib import Path

from seminar2.graph_search import Graph

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "dataset" / "cities.csv"


def _is_blank(row):
    """True if every cell of a csv.DictReader row is empty or whitespace."""
    cells = []
    for v in row.values():
        cells.extend(v if isinstance(v, list) else [v])
    return all(c is None or not c.strip() for c in cells)


def load_graph(path=DEFAULT_PATH):
    """Read the roads from a CSV file and build the symmetric adjacency dict.

    File format: header city_a,city_b,km, then one row per road (each road once).
    Raises ValueError if the data is malformed or the graph is not connected.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"city_a", "city_b", "km"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        rows = [(reader.line_num, row) for row in reader]   # csv skips blank lines, so enumerate would drift
    if not rows:
        raise ValueError(f"{path}: no roads found")

    g = {}
    seen = set()
    for line, row in rows:
        if _is_blank(row):
            continue
        a, b, raw_km = (row["city_a"] or "").strip(), (row["city_b"] or "").strip(), row["km"]
        if not a or not b or raw_km is None or None in row:
            raise ValueError(f"{path} line {line}: expected 3 values city_a,city_b,km")
        try:
            km = int(raw_km)
        except ValueError:
            raise ValueError(f"{path} line {line}: km must be an integer, got {raw_km!r}") from None
        if km <= 0:
            raise ValueError(f"road {a}-{b} has a non-positive distance: {km}")
        if a == b:
            raise ValueError(f"road {a}-{b} joins a city to itself")
        if frozenset((a, b)) in seen:
            raise ValueError(f"duplicate road {a}-{b}")
        seen.add(frozenset((a, b)))
        g.setdefault(a, {})[b] = km
        g.setdefault(b, {})[a] = km

    if not g:
        raise ValueError(f"{path}: no roads found")
    if not is_connected(g):
        raise ValueError("the road network is not connected")
    return g


def is_symmetric(g):
    """Every road must be stored in both directions with the same weight."""
    return all(b in g and g[b].get(a) == w for a in g for b, w in g[a].items())


def is_connected(g):
    """True if every city can be reached from any other city."""
    return Graph(g, weighted=True).is_connected()


def edge_list(g):
    """Each road once, as (city_a, city_b, km), sorted by city_a then city_b."""
    return sorted(
        (a, b, km) for a, roads in g.items() for b, km in roads.items() if a < b
    )


def edge_table(g):
    """Markdown table of all roads, for the report."""
    rows = ["| # | City A | City B | Distance (km) |", "|---|---|---|---|"]
    for i, (a, b, km) in enumerate(edge_list(g), start=1):
        rows.append(f"| {i} | {a} | {b} | {km} |")
    return "\n".join(rows)


if __name__ == "__main__":
    graph = load_graph()
    for city, roads in graph.items():
        print(f"{city}: {roads}")
    print()
    print(edge_table(graph))
    print()
    edges = sum(len(r) for r in graph.values()) // 2
    print(f"{len(graph)} cities, {edges} roads")
    print("symmetric:", is_symmetric(graph))
    print("connected:", is_connected(graph))
