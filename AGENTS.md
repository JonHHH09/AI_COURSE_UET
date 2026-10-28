# AI_COURSE_UET

Seminar 2 exercises for the AI course (UET). Two graph problems share one search module and are exposed through an MCP server:

- **U1 cities**: 8 Albanian cities, weighted undirected graph (km), shortest route by Dijkstra.
- **U2 maze**: 25 rooms on a 5x5 grid, unweighted undirected graph, fewest-doors path by BFS.

## Dev environment

- Python >=3.14, managed with `uv` (`package = false`, so nothing is installed as a package). Deps: `matplotlib`, `mcp`.
- Setup: `uv sync`
- Run everything from the repo root. Imports are absolute (`from seminar2.graph_search import Graph`).

## Commands

```
uv run python -m unittest discover -s seminar2/tests -t .   # tests (stdlib unittest, no pytest)
uv run python -m seminar2.cities.draw                       # writes seminar2/images/cities/graph.png
uv run python -m seminar2.maze.draw                         # writes seminar2/images/maze/maze.png
uv run python -m seminar2.cities.animate [--from A --to B] [--show] [--out PATH] [--fps N]   # writes images/cities/route.gif
uv run python -m seminar2.maze.animate [--from 1 --to 25] [--show] [--out PATH] [--fps N]    # writes images/maze/path.gif
uv run python -m seminar2.cities.graph                      # prints graph + symmetric/connected checks
uv run python -m seminar2.maze.maze                         # prints maze + validation result
uv run python seminar2/mcp_server.py                        # MCP server over stdio + live viewer
uv run python -m seminar2.live [--port N] [--no-browser]    # live viewer alone, with two demo sessions
npx @modelcontextprotocol/inspector uv run python seminar2/mcp_server.py   # call tools by hand
uv run python -m seminar2.tui                               # curses TUI: menu of every feature, run with options
```

`--show` opens a matplotlib window instead of saving the GIF. No linter, formatter, type checker or CI is configured. Don't invent commands for them.

## Layout

- `seminar2/graph_search.py`: pure stdlib search. `dijkstra_steps`, `bfs_steps`, `build_steps` yield one dict per step (`type`, `message`, `frontier`, `visited`, `dist`, `prev`); `dijkstra`/`bfs` consume them, so traces and results can't drift. `Graph(adjacency, weighted)` adds `shortest_path`, `search_steps`, `build_steps`. Keep it free of MCP/CSV/dataset/matplotlib imports.
- `seminar2/text.py`: `fold` (case/accent-insensitive key) and `plural`.
- `seminar2/layout.py`: node positions (`CITY_POS`, `maze_position`) shared by draw, animate and the viewer.
- `seminar2/animation.py`: shared matplotlib frame code for `cities/animate.py` and `maze/animate.py`.
- `seminar2/cities/graph.py`, `seminar2/maze/maze.py`: CSV loaders plus validation (`load_graph`, `load_maze`).
- `seminar2/dataset/`: `cities.csv` (`city_a,city_b,km`), `maze_doors.csv` (`room_a,room_b`), `maze_config.csv` (`key,value`: rooms, entrance, exit).
- `seminar2/mcp_server.py`: 9 MCP tools: `list_cities`, `get_roads`, `shortest_route`, `get_maze`, `get_doors`, `find_path`, plus `trace_route`, `trace_maze` (step-by-step explanation; `detail=True` returns full events) and `live_viewer` (page URL). `shortest_route`, `find_path` and the trace tools publish their search to the viewer.
- `seminar2/live/`: live viewer. `hub.py` (stdlib HTTP + SSE: `/`, `/events`, `/sessions`, `/sessions/latest`), `session.py` (session payloads), `index.html` (vanilla JS/SVG), `__main__.py` (standalone demo).
- `seminar2/tui/`: stdlib-curses TUI. `actions.py` is the UI-free registry (`Action`, `Option`, validation, `ProcessManager` for subprocesses); `app.py` only renders. MCP tools are discovered from the server (`mcp._tool_manager`, private SDK API, with `FALLBACK_TOOLS`) and called in-process; scripts run as `sys.executable -m ...` subprocesses (captured, or detached with a temp log and stopped on exit). Add new scripts to the registry in `actions.py`.
- `seminar2/images/{cities,maze}/`: generated figures and GIFs, one subdir per problem.
- `seminar2/*/arsyetimi.md`: the written reports (Albanian).

## Conventions

- Graph shapes: cities `{city: {neighbour: km}}`, maze `{room: [neighbours]}`. Every edge is stored in both directions.
- Loaders validate and raise `ValueError` with the file path and line number; they never return partial data.
- Unweighted `Graph.edges` yields sorted neighbours, so BFS results are deterministic. Keep that, or `find_path` output changes.
- MCP tools return dicts. Bad input returns `{"error": ..., ...}` (with the valid choices) instead of raising. Tool names, signatures and output keys are the public API.
- City lookup is case- and accent-insensitive (`Durres` matches `Durrës`), via `text.fold`.
- CSVs are read with `utf-8-sig`; city names keep `ë`/`ç`.
- Step messages and viewer/animation captions are English.
- Server code never prints to stdout (it is the MCP stdio channel); the viewer logs to stderr and is best-effort.

## Live viewer and Hermes

- `mcp_server.py`'s `__main__` starts the viewer on http://127.0.0.1:8765 (`SEMINAR2_LIVE_PORT`; `SEMINAR2_LIVE=0` disables). If the default port is busy it falls back to a free port; an explicitly set busy port disables it. Importing `mcp_server` starts nothing.
- Each search tool call (`shortest_route`, `find_path`, `trace_route`, `trace_maze`) auto-plays: phase 1 builds the graph edge by edge from the CSV, phase 2 animates the search. History is in memory (last 20 sessions).
- Hermes runs the server from `~/.hermes/config.yaml` `mcp_servers.seminar2` (`uv run --quiet --project <repo> python <repo>/seminar2/mcp_server.py`); tools appear as `mcp_seminar2_<tool>`. Restart Hermes after changing the server or dataset; check with `hermes mcp test seminar2`.

## Pitfalls

- Run `graph.py`, `maze.py`, `draw.py`, `animate.py` and `seminar2.live` with `-m`, not by file path (`ModuleNotFoundError: No module named 'seminar2'`). Only `mcp_server.py` is run by path, because it inserts the repo root into `sys.path`.
- The server reads the CSVs once at startup. Restart it after changing the dataset.
- `maze/draw.py` loads the maze at import time, so a broken dataset fails on import.
- `layout.CITY_POS` must cover every city in `cities.csv`; add a position when adding a city.
- `arsyetimi.md` quotes counts (9 roads, 31 doors, 8 cities, 25 rooms). Update them when the CSVs change.
- Changing the dataset can change which equal-length path is returned. The tests pin the real-data results (Shkodër→Korçë 267 km; maze 1→25 in 12 doors).
- `test_live.py` and `test_mcp_server.py` start and stop the hub on port 0; don't run them in a process that hosts a real hub.
- `git` has no commits yet and everything is untracked.
