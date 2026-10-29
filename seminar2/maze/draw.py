"""Seminar 2, U2: draw the 25-room maze with matplotlib only."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from seminar2.layout import maze_position
from seminar2.maze.maze import grid_width, load_maze

OUT = Path(__file__).resolve().parent.parent / "images" / "maze" / "maze.png"

loaded = load_maze()
ENTRANCE, EXIT, N_ROOMS, maze = loaded.entrance, loaded.exit, loaded.rooms, loaded.adjacency
WIDTH = grid_width(N_ROOMS)


def position(room):
    """Room 1 is top left; rooms are numbered row by row on a square grid."""
    return maze_position(room, WIDTH)


def draw(doors, out):
    fig, ax = plt.subplots(figsize=(8, 8))

    for a, b in doors:
        (x1, y1), (x2, y2) = position(a), position(b)
        ax.plot([x1, x2], [y1, y2], color="#555555", linewidth=3, zorder=1)

    for room in maze:
        x, y = position(room)
        if room == ENTRANCE:
            color, text = "#2ca02c", "white"
        elif room == EXIT:
            color, text = "#d62728", "white"
        else:
            color, text = "#8fbce6", "black"
        ax.scatter(x, y, s=1500, color=color, edgecolor="black", zorder=2)
        ax.text(x, y, str(room), ha="center", va="center", fontsize=12,
                fontweight="bold", color=text, zorder=3)

    # Entrance and exit are doors to the outside.
    ex, ey = position(ENTRANCE)
    ax.annotate("Entrance", (ex, ey), (ex - 0.9, ey + 0.6), ha="center",
                color="#2ca02c", fontsize=11, fontweight="bold",
                arrowprops={"arrowstyle": "->", "color": "#2ca02c", "lw": 2, "shrinkB": 22})
    xx, xy = position(EXIT)
    ax.annotate("Exit", (xx, xy), (xx + 0.9, xy - 0.6), ha="center",
                color="#d62728", fontsize=11, fontweight="bold",
                arrowprops={"arrowstyle": "->", "color": "#d62728", "lw": 2, "shrinkB": 22})

    ax.set_title(f"Maze graph: {N_ROOMS} rooms, {len(doors)} doors")
    ax.set_aspect("equal")
    ax.margins(0.18)
    ax.axis("off")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    draw(loaded.doors, OUT)
    print(f"saved {OUT}")
