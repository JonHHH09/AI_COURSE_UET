"""Seminar 2, U1: draw the intercity graph with matplotlib only."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from seminar2.cities.graph import load_graph
from seminar2.layout import CITY_POS

POS = CITY_POS

OUT = Path(__file__).resolve().parent.parent / "images" / "cities" / "graph.png"


def draw(g, pos, out):
    fig, ax = plt.subplots(figsize=(10, 7))

    # Each road is stored twice in the dict; draw it once.
    drawn = set()
    for a, roads in g.items():
        for b, km in roads.items():
            if (b, a) in drawn:
                continue
            drawn.add((a, b))
            (x1, y1), (x2, y2) = pos[a], pos[b]
            ax.plot([x1, x2], [y1, y2], color="#555555", linewidth=2, zorder=1)
            ax.text(
                (x1 + x2) / 2, (y1 + y2) / 2, f"{km} km",
                ha="center", va="center", fontsize=10, color="#b00020",
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none"},
                zorder=3,
            )

    for city, (x, y) in pos.items():
        hub = len(g[city]) > 1
        ax.scatter(
            x, y, s=2100 if hub else 2000, zorder=2,
            color="#1f77b4" if hub else "#8fbce6", edgecolor="black",
        )
        ax.text(x, y, city, ha="center", va="center", fontsize=9,
                fontweight="bold", color="white" if hub else "black", zorder=4)

    ax.set_title("Intercity graph: 8 Albanian cities (driving distance, km)")
    ax.set_aspect("equal")
    ax.margins(0.12)
    ax.axis("off")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    graph = load_graph()
    assert set(POS) == set(graph), "POS and graph cities differ"
    draw(graph, POS, OUT)
    print(f"saved {OUT}")
