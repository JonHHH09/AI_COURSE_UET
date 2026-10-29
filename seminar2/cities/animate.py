"""Seminar 2, U1: animate building the city graph and the Dijkstra search.

    uv run python -m seminar2.cities.animate [--from Shkodër --to Korçë] [--show] [--out PATH] [--fps N]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

from seminar2 import animation
from seminar2.cities.graph import load_graph
from seminar2.graph_search import Graph
from seminar2.layout import CITY_POS
from seminar2.text import fold, printable

OUT = Path(__file__).resolve().parent.parent / "images" / "cities" / "route.gif"
DEFAULT_FROM, DEFAULT_TO = "Shkodër", "Korçë"


def resolve_city(name, cities):
    """Match a city ignoring case and accents; ValueError lists the valid names."""
    matches = [c for c in cities if fold(c) == fold(name)]
    if not matches:
        raise ValueError(f"unknown city {name!r}; valid cities: {', '.join(cities)}")
    return matches[0]


def make_scene(graph, start, goal):
    return animation.Scene(
        adjacency=graph, weighted=True, pos=CITY_POS, start=start, goal=goal,
        title="Intercity graph: 8 Albanian cities (driving distance, km)",
        algorithm="Dijkstra", unit="km", node_size=1900, font_size=8.5,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Animate Dijkstra on the intercity graph.")
    parser.add_argument("--from", dest="start", default=DEFAULT_FROM)
    parser.add_argument("--to", dest="goal", default=DEFAULT_TO)
    parser.add_argument("--show", action="store_true", help="open a live window instead of saving a GIF")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--fps", type=int, default=2)
    args = parser.parse_args(argv)
    if args.fps < 1:
        parser.error("--fps must be at least 1")
    graph = load_graph()
    try:
        start = resolve_city(args.start, list(graph))
        goal = resolve_city(args.goal, list(graph))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    path, cost = Graph(graph, weighted=True).shortest_path(start, goal)
    print(printable(f"{' → '.join(path)}: {cost} km" if path else f"no route from {start} to {goal}"))
    scene = make_scene(graph, start, goal)
    if args.show:
        animation.show(scene, args.fps)
    else:
        matplotlib.use("Agg")
        frames = animation.save_gif(scene, args.out, args.fps)
        print(f"saved {args.out} ({frames} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
