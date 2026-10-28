"""Build JSON-serialisable 'sessions' (one tool call = one animation) for the live viewer.

Pure stdlib. Node ids are strings so the browser sees consistent keys.
"""

import itertools
import time

from seminar2.graph_search import Graph
from seminar2.layout import CITY_POS, maze_position
from seminar2.maze.maze import grid_width

# Start from the clock so ids keep growing across server restarts (a browser that
# stays open would otherwise see a new process reuse ids); stays below 2**53.
_ids = itertools.count(int(time.time() * 1000) * 1000)


def _session(tool, problem, title, algorithm, graph, nodes, start, goal, unit):
    build = list(graph.build_steps())
    steps = list(graph.search_steps(start, goal))
    last = steps[-1]
    found = last["type"] == "found"
    return {
        "id": next(_ids),
        "tool": tool,
        "problem": problem,
        "title": title,
        "algorithm": algorithm,
        "weighted": graph.weighted,
        "nodes": nodes,
        "build": build,
        "steps": steps,
        "result": {"path": last["path"] if found else None,
                   "cost": last["cost"] if found else None, "unit": unit},
    }


def city_session(adjacency, start, goal, tool):
    """Dijkstra session over the cities graph."""
    nodes = [{"id": str(c), "label": str(c), "x": CITY_POS[c][0], "y": CITY_POS[c][1],
              "role": "start" if c == start else "goal" if c == goal else "normal"}
             for c in adjacency]
    return _session(tool, "cities", f"{tool}: {start} → {goal} (Dijkstra)", "Dijkstra",
                    Graph(adjacency, weighted=True), nodes, start, goal, "km")


def maze_session(adjacency, start, goal, entrance, exit_, tool):
    """BFS session over the maze; entrance/exit roles win over start/goal."""
    width = grid_width(len(adjacency))
    nodes = []
    for r in sorted(adjacency):
        x, y = maze_position(r, width)
        role = ("entrance" if r == entrance else "exit" if r == exit_
                else "start" if r == start else "goal" if r == goal else "normal")
        nodes.append({"id": str(r), "label": str(r), "x": x, "y": y, "role": role})
    return _session(tool, "maze", f"{tool}: room {start} → room {goal} (BFS)", "BFS",
                    Graph(adjacency, weighted=False), nodes, start, goal, "doors")
