# AI_COURSE_UET

Seminar 2 exercises for the AI course (UET). Two graph problems that share one search module and are exposed through an MCP server:

- **U1, cities:** 8 Albanian cities, weighted undirected graph (driving km). Shortest route by Dijkstra.
- **U2, maze:** 25 rooms on a 5x5 grid, unweighted undirected graph. Fewest-doors path by BFS.

## Layout

- `seminar2/cities/` – U1: intercity graph (`graph.py`, `draw.py`, `arsyetimi.md`)
- `seminar2/maze/` – U2: 25-room maze (`maze.py`, `draw.py`, `arsyetimi.md`)
- `seminar2/images/` – generated figures, one subdir per problem: `cities/graph.png`, `maze/maze.png`
- `seminar2/dataset/` – the data as CSV: `cities.csv` (roads and km), `maze_doors.csv` (doors), `maze_config.csv` (rooms, entrance, exit)
- `seminar2/graph_search.py` – shared Dijkstra/BFS and `Graph` class used by cities and maze
- `seminar2/mcp_server.py` – MCP server (stdio) exposing both problems, plus the live viewer
- `seminar2/live/` – live web viewer that animates each search as it runs
- `seminar2/layout.py` – node positions shared by the drawings, animations and viewer
- `seminar2/animation.py` – shared matplotlib frame code for the animations
- `seminar2/tui/` – terminal UI that lists and runs every feature
- `seminar2/tests/` – unit tests

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

## Run (from the repo root)

```
uv run python -m seminar2.cities.draw   # writes seminar2/images/cities/graph.png
uv run python -m seminar2.maze.draw     # writes seminar2/images/maze/maze.png
uv run python -m seminar2.cities.animate  # writes seminar2/images/cities/route.gif (--from, --to, --show, --out, --fps)
uv run python -m seminar2.maze.animate    # writes seminar2/images/maze/path.gif (--from, --to, --show, --out, --fps)
uv run python -m seminar2.live          # live viewer at http://127.0.0.1:8765 with demo searches
uv run python seminar2/mcp_server.py    # MCP server over stdio, plus the live viewer
uv run python -m seminar2.cities.graph  # print the city graph (use -m, not the file path)
uv run python -m seminar2.maze.maze     # print the maze
```

`--show` opens a live matplotlib window instead of saving a GIF.

## Terminal UI

```
uv run python -m seminar2.tui
```

Lists everything above in one menu and runs it with options: the 9 MCP tools (called directly, with city/room pickers), the live viewer (start it here and searches run from the TUI play in the browser), the animations, figures and data checks, tests, the Hermes check and the MCP Inspector. Keys: ↑/↓ move, Enter opens the options form, Enter runs, Esc goes back or cancels a running job, `/` filters, `?` help, `q` quits (background processes are stopped).

## Live viewer

Each route or path search made through the MCP server appears in the viewer at http://127.0.0.1:8765 and plays automatically: first the graph is built edge by edge, then the search runs (frontier, distance table, final path).

- Port: `SEMINAR2_LIVE_PORT` (default 8765).
- Off: `SEMINAR2_LIVE=0`.
- If the default port is busy, the viewer picks a free port (ask the `live_viewer` tool for the URL). A busy port set through `SEMINAR2_LIVE_PORT` disables the viewer; the server keeps working.
- `uv run python -m seminar2.live --port N --no-browser` runs it on its own, without MCP.

## Test

```
uv run python -m unittest discover -s seminar2/tests -t .
```

## MCP server

Started over stdio. The data is read from `seminar2/dataset/` once at startup, so restart the server after editing the CSVs.

| Tool | Problem | Purpose |
|---|---|---|
| `list_cities` | cities | Cities and how many roads each has |
| `get_roads(city)` | cities | Direct roads from a city, in km (name matching ignores case and accents) |
| `shortest_route(from_city, to_city)` | cities | Shortest route by total km (Dijkstra) |
| `trace_route(from_city, to_city, detail=False)` | cities | Same route plus a step-by-step explanation; `detail=True` returns the raw events |
| `get_maze` | maze | Entrance, exit, doors and each room's neighbours |
| `get_doors(room)` | maze | Rooms reachable through one room's doors |
| `find_path(from_room=1, to_room=25)` | maze | Fewest-doors path (BFS) |
| `trace_maze(from_room=1, to_room=25, detail=False)` | maze | Same path plus a step-by-step explanation; `detail=True` returns the raw events |
| `live_viewer()` | both | URL of the live viewer |

`shortest_route` and `find_path` also show their search in the live viewer. Their output is unchanged.

Example client config:

```json
{
  "mcpServers": {
    "seminar2": {
      "command": "uv",
      "args": ["run", "python", "seminar2/mcp_server.py"],
      "cwd": "/path/to/AI_COURSE_UET"
    }
  }
}
```
