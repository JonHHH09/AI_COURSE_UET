"""MCP server for Seminar 2: exposes the intercity graph (U1) and the maze (U2).

Run over stdio (as a script):  uv run python seminar2/mcp_server.py

Running it as a script also starts a live web viewer (see seminar2/live) that
animates every route / path tool call; set SEMINAR2_LIVE=0 to turn it off and
SEMINAR2_LIVE_PORT to change the port (default 8765).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from seminar2.cities.graph import load_graph, load_roads
from seminar2.graph_search import Graph
from seminar2.live import hub
from seminar2.live.session import city_session, maze_session
from seminar2.maze.maze import load_maze
from seminar2.cities.quality import best_quality_route as _quality_route, cost_adjacency
from seminar2.text import fold

mcp = MCPServer("seminar2")

# Datasets are read once at startup from seminar2/dataset/*.csv.
graph = load_graph()
roads = load_roads()
_maze = load_maze()
maze, DOORS, ENTRANCE, EXIT = _maze.adjacency, _maze.doors, _maze.entrance, _maze.exit
city_graph = Graph(graph, weighted=True)
maze_graph = Graph(maze, weighted=False)


# --- helpers -----------------------------------------------------------------

def _match_city(name):
    """Case-insensitive lookup; also accepts names without ë/ç (Durres, Korce)."""
    for city in graph:
        if fold(city) == fold(name):
            return city
    return None


def _publish_cities(a, b, tool):
    session = city_session(graph, a, b, tool)
    hub.publish(session)
    return session


def _publish_maze(a, b, tool):
    session = maze_session(maze, a, b, ENTRANCE, EXIT, tool)
    hub.publish(session)
    return session


def _bad_room(*rooms):
    for r in rooms:
        if r not in maze:
            return {"error": f"room {r} does not exist, rooms are 1-{len(maze)}"}
    return None


def _events(events, detail):
    return events if detail else [e["message"] for e in events]


# --- cities (U1) -------------------------------------------------------------

@mcp.tool()
def list_cities() -> dict:
    """List the cities in the graph and how many roads each has."""
    return {"cities": {c: len(r) for c, r in graph.items()}}


@mcp.tool()
def get_roads(city: str) -> dict:
    """Direct roads from a city with their driving distance in km (approximate)."""
    found = _match_city(city)
    if found is None:
        return {"error": f"unknown city '{city}'", "cities": sorted(graph)}
    return {"city": found, "roads_km": graph[found]}


@mcp.tool()
def shortest_route(from_city: str, to_city: str) -> dict:
    """Shortest route between two cities by total driving km (Dijkstra)."""
    a, b = _match_city(from_city), _match_city(to_city)
    if a is None or b is None:
        bad = from_city if a is None else to_city
        return {"error": f"unknown city '{bad}'", "cities": sorted(graph)}
    if hub.url():
        result = _publish_cities(a, b, "shortest_route")["result"]
        path, km = result["path"], result["cost"]
    else:
        path, km = city_graph.shortest_path(a, b)
    return {"from": a, "to": b, "route": path, "total_km": km}


@mcp.tool()
def best_quality_route(from_city: str, to_city: str) -> dict:
    """Best route by quality-weighted cost (km × quality factor)."""
    a, b = _match_city(from_city), _match_city(to_city)
    if a is None or b is None:
        bad = from_city if a is None else to_city
        return {"error": f"unknown city '{bad}'", "cities": sorted(graph)}
    if hub.url():
        session = city_session(cost_adjacency(graph, roads), a, b, "best_quality_route", unit="cost")
        hub.publish(session)
        result = _quality_route(graph, roads, a, b)
    else:
        result = _quality_route(graph, roads, a, b)
    if result is None:
        return {"error": f"no route from {a} to {b}"}
    return {"from": a, "to": b, "route": result["route"], "total_km": result["total_km"],
            "quality_cost": result["quality_cost"], "legs": result["legs"],
            "worst_road": result["worst_road"]}


@mcp.tool()
def trace_route(from_city: str, to_city: str, detail: bool = False) -> dict:
    """Shortest route (Dijkstra) plus a step-by-step explanation of how the graph
    is built and how the search runs. build/steps are English sentences; with
    detail=true they are full event dicts (frontier, visited, dist, prev).
    Always share live_url with the user so they can watch the animation live.
    """
    a, b = _match_city(from_city), _match_city(to_city)
    if a is None or b is None:
        bad = from_city if a is None else to_city
        return {"error": f"unknown city '{bad}'", "cities": sorted(graph)}
    session = _publish_cities(a, b, "trace_route")
    return {"from": a, "to": b, "algorithm": "Dijkstra",
            "route": session["result"]["path"], "total_km": session["result"]["cost"],
            "build": _events(session["build"], detail), "steps": _events(session["steps"], detail),
            "live_url": hub.url()}


# --- maze (U2) ---------------------------------------------------------------

@mcp.tool()
def get_maze() -> dict:
    """The maze: entrance, exit, doors and each room's neighbours."""
    return {
        "rooms": len(maze),
        "entrance": ENTRANCE,
        "exit": EXIT,
        "doors": [list(d) for d in DOORS],
        "neighbours": {str(r): sorted(n) for r, n in maze.items()},
    }


@mcp.tool()
def get_doors(room: int) -> dict:
    """Rooms reachable through the doors of one room."""
    if room not in maze:
        return {"error": f"room {room} does not exist, rooms are 1-{len(maze)}"}
    return {"room": room, "doors_to": sorted(maze[room]),
            "is_entrance": room == ENTRANCE, "is_exit": room == EXIT}


@mcp.tool()
def find_path(from_room: int = ENTRANCE, to_room: int = EXIT) -> dict:
    """Fewest-doors path between two rooms (BFS). Defaults to entrance -> exit."""
    if (error := _bad_room(from_room, to_room)):
        return error
    if hub.url():
        path = _publish_maze(from_room, to_room, "find_path")["result"]["path"]
    else:
        path, _ = maze_graph.shortest_path(from_room, to_room)
    return {"from": from_room, "to": to_room, "path": path,
            "doors_passed": len(path) - 1 if path else None}


@mcp.tool()
def trace_maze(from_room: int = ENTRANCE, to_room: int = EXIT, detail: bool = False) -> dict:
    """Fewest-doors path (BFS) plus a step-by-step explanation of how the maze is
    built and how the search runs. build/steps are English sentences; with
    detail=true they are full event dicts (queue, visited, dist, prev).
    Always share live_url with the user so they can watch the animation live.
    """
    if (error := _bad_room(from_room, to_room)):
        return error
    session = _publish_maze(from_room, to_room, "trace_maze")
    path = session["result"]["path"]
    return {"from": from_room, "to": to_room, "algorithm": "BFS", "path": path,
            "doors_passed": len(path) - 1 if path else None,
            "build": _events(session["build"], detail), "steps": _events(session["steps"], detail),
            "live_url": hub.url()}


@mcp.tool()
def live_viewer() -> dict:
    """URL of the live web viewer that animates route and path searches in real
    time. Share it with the user, then call trace_route / trace_maze (or
    shortest_route / find_path) and the page plays them automatically.
    """
    url = hub.url()
    if url is None:
        return {"error": "live viewer is not running",
                "hint": "start the server as a script without SEMINAR2_LIVE=0, "
                        "or run: uv run python -m seminar2.live"}
    return {"url": url}


if __name__ == "__main__":
    if os.environ.get("SEMINAR2_LIVE") != "0":
        hub.start()
    mcp.run()
