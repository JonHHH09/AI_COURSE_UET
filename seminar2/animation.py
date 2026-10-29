"""Shared step-by-step animation for Seminar 2 (matplotlib only).

Phase 1 builds the graph (one node or edge per frame), phase 2 replays the
search (Dijkstra or BFS) event by event. build_frames() turns the traces of
seminar2.graph_search into plain frame dicts; render_frame() draws one frame;
make_animation() / save_gif() / show() wrap them in a FuncAnimation.

The backend is not chosen here: the callers pick Agg (GIF) or an interactive one.
"""

import textwrap
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from seminar2.graph_search import Graph
from seminar2.text import plural

INF = "∞"
HOLD_SECONDS = 2.5

# Node fill colours by role.
IDLE = "#8fbce6"
FRONTIER = "#ffd92f"
VISITED = "#4c6a92"
CURRENT = "#ff7f0e"
START_COLOR = "#2ca02c"
GOAL_COLOR = "#d62728"
PATH_COLOR = "#d81b60"
IMPROVED = "#2ca02c"
NOT_IMPROVED = "#999999"
EDGE = "#555555"
LABEL_COLOR = "#b00020"


@dataclass
class Scene:
    """What differs between the two problems."""

    adjacency: dict
    weighted: bool
    pos: dict
    start: object
    goal: object
    title: str                      # graph title during phase 1
    algorithm: str                  # "Dijkstra" or "BFS"
    unit: str                       # "km" or "doors"
    start_label: str = "Start"
    goal_label: str = "Goal"
    node_size: int = 1700
    font_size: float = 8
    color_endpoints: bool = False   # maze: entrance green / exit red fill in phase 1
    figsize: tuple = (12, 6.5)
    hold: int = 0
    frames: list = field(default_factory=list)


def _frame(**fields):
    base = {"phase": 1, "kind": "", "heading": "", "title": "", "message": "",
            "nodes": [], "edges": [], "roles": {}, "highlight": None, "path": None,
            "frontier": None, "dist": None, "prev": None, "counts": None}
    base.update(fields)
    return base


def _edge_key(a, b):
    return frozenset((a, b))


def build_frames(scene, hold=0):
    """Frame dicts: one per build event, one per search event, then `hold` copies of the last."""
    graph = Graph(scene.adjacency, scene.weighted)
    frames = []
    nodes, edges = [], []
    for ev in graph.build_steps():
        if ev["type"] == "add_node":
            nodes = nodes + [ev["node"]]
        else:
            edges = edges + [(ev["a"], ev["b"], ev["cost"])]
        frames.append(_frame(
            phase=1, kind=ev["type"], heading="1. Building the graph from the CSV",
            title=scene.title, message=ev["message"], nodes=nodes, edges=edges,
            counts=(ev["nodes"], ev["edges"]),
        ))

    all_nodes = list(nodes)
    all_edges = list(edges)
    heading = f"2. {scene.algorithm} search"
    for ev in graph.search_steps(scene.start, scene.goal):
        kind = ev["type"]
        visited = list(ev["visited"])
        if scene.weighted:
            queue = [node for _, node in ev["frontier"]]
            frontier_lines = [f"{node} ({cost} {scene.unit})" for cost, node in ev["frontier"]]
        else:
            queue = list(ev["frontier"])
            frontier_lines = [str(node) for node in queue]
        current = None
        highlight = None
        path = None
        title = f"{scene.algorithm}: {scene.start} → {scene.goal}"
        if kind in ("start", "pop", "skip"):
            current = ev["node"]
        elif kind in ("relax", "discover"):
            current = ev["from"]
            good = ev["improved"] if kind == "relax" else ev["new"]
            highlight = (ev["from"], ev["to"], "good" if good else "bad")
        elif kind == "found":
            path = ev["path"]
            cost = f"{ev['cost']} km" if scene.weighted else plural(ev["cost"], "door")
            title = (f"Shortest {'route' if scene.weighted else 'path'} {scene.start} → "
                     f"{scene.goal}: {cost}")
        elif kind == "fail":
            title = f"No path from {scene.start} to {scene.goal}"
        roles = {}
        for node in queue:
            roles[node] = "frontier"
        for node in visited:
            roles[node] = "visited"
        if current is not None:
            roles[current] = "current"
        frames.append(_frame(
            phase=2, kind=kind, heading=heading, title=title, message=ev["message"],
            nodes=all_nodes, edges=all_edges, roles=roles, highlight=highlight, path=path,
            frontier=frontier_lines, dist=dict(ev["dist"]), prev=dict(ev["prev"]),
        ))
    frames.extend([frames[-1]] * hold)
    return frames


def hold_frames(fps):
    return round(HOLD_SECONDS * fps)


def _table_lines(scene, frame):
    """Monospace dist/prev table: one column for few nodes, three for many."""
    order = list(scene.adjacency)
    cells = []
    for node in order:
        d = frame["dist"].get(node)
        p = frame["prev"].get(node)
        dist = INF if d is None else str(d)
        parent = "–" if p is None else str(p)
        if scene.weighted:
            cells.append(f"{node!s:<8}{dist:>5}  ← {parent}")
        else:
            cells.append(f"{node!s:>2} {dist:>2} ←{parent:>2}")
    ncols = 1 if len(order) <= 10 else 3
    rows = -(-len(cells) // ncols)
    gap = "   "
    lines = []
    for r in range(rows):
        lines.append(gap.join(cells[r + c * rows] for c in range(ncols) if r + c * rows < len(cells)))
    header = "Node      km  ← prev" if scene.weighted else "Rm dr ←prv"
    if ncols > 1:
        header = gap.join([header] * ncols)
    return [header] + lines


def _draw_graph(ax, scene, frame):
    ax.clear()
    ax.set_aspect("equal")
    xs = [p[0] for p in scene.pos.values()]
    ys = [p[1] for p in scene.pos.values()]
    ax.set_xlim(min(xs) - 0.8, max(xs) + 0.8)
    ax.set_ylim(min(ys) - 0.8, max(ys) + 0.8)
    ax.axis("off")
    ax.set_title(frame["title"], fontsize=12, fontweight="bold")

    path_edges = set()
    if frame["path"]:
        path_edges = {_edge_key(a, b) for a, b in zip(frame["path"], frame["path"][1:], strict=False)}
    hl = frame["highlight"]
    hl_key = _edge_key(hl[0], hl[1]) if hl else None

    for a, b, cost in frame["edges"]:
        (x1, y1), (x2, y2) = scene.pos[a], scene.pos[b]
        key = _edge_key(a, b)
        color, width, style, z = EDGE, 2, "-", 1
        if key in path_edges:
            color, width, z = PATH_COLOR, 6, 1.5
        elif key == hl_key:
            color = IMPROVED if hl[2] == "good" else NOT_IMPROVED
            width, z = 5, 1.5
            style = "-" if hl[2] == "good" else (0, (3, 2))
        ax.plot([x1, x2], [y1, y2], color=color, linewidth=width, linestyle=style, zorder=z)
        if scene.weighted:
            ax.text((x1 + x2) / 2, (y1 + y2) / 2, f"{cost} km", ha="center", va="center",
                    fontsize=9, color=LABEL_COLOR, zorder=3,
                    bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none"})

    for node in frame["nodes"]:
        x, y = scene.pos[node]
        role = frame["roles"].get(node)
        fill = {"current": CURRENT, "frontier": FRONTIER, "visited": VISITED}.get(role, IDLE)
        text = "white" if role == "visited" else "black"
        ring, ring_w = "black", 1
        if frame["phase"] == 1 and scene.color_endpoints and node in (scene.start, scene.goal):
            fill = START_COLOR if node == scene.start else GOAL_COLOR
            text = "white"
        if frame["phase"] == 2 and node == scene.start:
            ring, ring_w = START_COLOR, 4
        elif frame["phase"] == 2 and node == scene.goal:
            ring, ring_w = GOAL_COLOR, 4
        ax.scatter(x, y, s=scene.node_size, color=fill, edgecolor=ring, linewidths=ring_w, zorder=2)
        ax.text(x, y, str(node), ha="center", va="center", fontsize=scene.font_size,
                fontweight="bold", color=text, zorder=4)
        if frame["phase"] == 2 and node in (scene.start, scene.goal):
            label, color = ((scene.start_label, START_COLOR) if node == scene.start
                            else (scene.goal_label, GOAL_COLOR))
            ax.text(x, y - 0.5, label, ha="center", va="top", fontsize=9,
                    fontweight="bold", color=color, zorder=4)


def _draw_panel(panel, scene, frame):
    panel.clear()
    panel.axis("off")
    panel.set_xlim(0, 1)
    panel.set_ylim(0, 1)
    height_pt = scene.figsize[1] * 72 * 0.86
    cursor = 0.99

    def put(lines, size, **kw):
        nonlocal cursor
        lines = list(lines)
        panel.text(0, cursor, "\n".join(lines), va="top", ha="left", fontsize=size, **kw)
        cursor -= len(lines) * size * 1.4 / height_pt + 0.025

    put([frame["heading"]], 13, fontweight="bold")
    put(textwrap.wrap(frame["message"], 46) or [""], 11)
    if frame["phase"] == 1:
        nodes, edges = frame["counts"]
        if scene.weighted:
            nodes_text = f"{nodes} {'city' if nodes == 1 else 'cities'}"
            edges_text = plural(edges, "road")
        else:
            nodes_text = plural(nodes, "room")
            edges_text = plural(edges, "door")
        put([f"{nodes_text}, {edges_text} so far"], 11, fontweight="bold")
        return
    queue_name = "priority queue, cheapest first" if scene.weighted else "FIFO queue, front first"
    put([f"Frontier ({queue_name}):"], 11, fontweight="bold")
    items = ", ".join(frame["frontier"]) if frame["frontier"] else "(empty)"
    put(textwrap.wrap(items, 46)[:4], 10.5)
    unit = scene.unit
    put([f"Distances ({unit}) and parents:"], 11, fontweight="bold")
    put(_table_lines(scene, frame), 9, family="monospace")
    handles = [
        Patch(fc=CURRENT, ec="black", label="current node"),
        Patch(fc=FRONTIER, ec="black", label="frontier"),
        Patch(fc=VISITED, ec="black", label="visited / settled"),
        Patch(fc=IDLE, ec="black", label="not seen yet"),
        Line2D([], [], color=IMPROVED, lw=4, label="edge: improved / new"),
        Line2D([], [], color=NOT_IMPROVED, lw=4, ls=(0, (3, 2)), label="edge: no gain / seen"),
        Line2D([], [], color=PATH_COLOR, lw=6, label="final path"),
    ]
    panel.legend(handles=handles, loc="lower left", ncol=2, fontsize=8.5, frameon=False,
                 bbox_to_anchor=(0, -0.02))


def render_frame(ax, panel, scene, frame):
    _draw_graph(ax, scene, frame)
    _draw_panel(panel, scene, frame)


def make_figure(scene):
    fig = plt.figure(figsize=scene.figsize)
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 2], left=0.02, right=0.98, top=0.93, bottom=0.04,
                          wspace=0.04)
    return fig, fig.add_subplot(gs[0]), fig.add_subplot(gs[1])


def make_animation(scene, fps, dpi=80):
    """Returns (fig, FuncAnimation); scene.frames is filled in."""
    scene.hold = hold_frames(fps)
    scene.frames = build_frames(scene, scene.hold)
    fig, ax, panel = make_figure(scene)
    fig.set_dpi(dpi)

    def update(i):
        render_frame(ax, panel, scene, scene.frames[i])
        return []

    anim = FuncAnimation(fig, update, frames=len(scene.frames), interval=1000 / fps,
                         repeat=True, blit=False)
    return fig, anim


def save_gif(scene, out, fps=3, dpi=80):
    """Render every frame to a GIF at `out`; returns the number of frames."""
    fig, anim = make_animation(scene, fps, dpi)
    out.parent.mkdir(parents=True, exist_ok=True)
    anim.save(out, writer=PillowWriter(fps=fps), dpi=dpi)
    plt.close(fig)
    return len(scene.frames)


def show(scene, fps=3):
    _fig, anim = make_animation(scene, fps, dpi=100)
    plt.show()
    return anim  # `anim` stays referenced until the window closes
