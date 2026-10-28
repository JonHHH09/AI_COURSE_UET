"""Seminar 2, U2: animate building the maze graph and the BFS search.

    uv run python -m seminar2.maze.animate [--from 1 --to 25] [--show] [--out PATH] [--fps N]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

from seminar2 import animation
from seminar2.graph_search import Graph
from seminar2.layout import maze_position
from seminar2.maze.maze import grid_width, load_maze

OUT = Path(__file__).resolve().parent.parent / "images" / "maze" / "path.gif"


def make_scene(maze, start, goal):
    width = grid_width(maze.rooms)
    return animation.Scene(
        adjacency=maze.adjacency, weighted=False,
        pos={room: maze_position(room, width) for room in maze.adjacency},
        start=start, goal=goal,
        title=f"Maze graph: {maze.rooms} rooms, {len(maze.doors)} doors",
        algorithm="BFS", unit="doors", start_label="Entrance", goal_label="Exit",
        node_size=1300, font_size=11, color_endpoints=True,
    )


def parse_room(text, maze, option):
    """Room number in 1..rooms; ValueError names the option and the valid range."""
    try:
        room = int(text)
    except ValueError:
        room = 0
    if not 1 <= room <= maze.rooms:
        raise ValueError(f"{option}: unknown room {text!r}; rooms are numbered 1 to {maze.rooms}")
    return room


def main(argv=None):
    parser = argparse.ArgumentParser(description="Animate BFS on the maze graph.")
    parser.add_argument("--from", dest="start", help="start room (default: the entrance)")
    parser.add_argument("--to", dest="goal", help="goal room (default: the exit)")
    parser.add_argument("--show", action="store_true", help="open a live window instead of saving a GIF")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--fps", type=int, default=4)
    args = parser.parse_args(argv)
    if args.fps < 1:
        parser.error("--fps must be at least 1")
    maze = load_maze()
    try:
        start = maze.entrance if args.start is None else parse_room(args.start, maze, "--from")
        goal = maze.exit if args.goal is None else parse_room(args.goal, maze, "--to")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    path, doors = Graph(maze.adjacency, weighted=False).shortest_path(start, goal)
    print(f"{' → '.join(map(str, path))}: {doors} doors" if path else f"no path from {start} to {goal}")
    scene = make_scene(maze, start, goal)
    if args.show:
        animation.show(scene, args.fps)
    else:
        matplotlib.use("Agg")
        frames = animation.save_gif(scene, args.out, args.fps)
        print(f"saved {args.out} ({frames} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
