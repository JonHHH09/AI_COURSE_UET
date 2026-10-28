"""Seminar 2, U2: maze of rooms on a square grid (25 rooms in the dataset).

Model: rooms are nodes, doors between rooms are edges.
Undirected (a door opens both ways) and unweighted (no distances given).
Stored as an adjacency list: {room: [neighbouring rooms]}.
The rooms, entrance and exit live in seminar2/dataset/maze_config.csv, the doors
in seminar2/dataset/maze_doors.csv; load_maze() reads both.

Assumption: the entrance and exit are doors to the outside. They are stored as
the entrance and exit room numbers, not as edges, so they do not count towards
a room's 2-4 doors.
"""

import csv
from math import isqrt
from pathlib import Path
from typing import NamedTuple

from seminar2.graph_search import Graph

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"
DEFAULT_DOORS_PATH = DATASET_DIR / "maze_doors.csv"
DEFAULT_CONFIG_PATH = DATASET_DIR / "maze_config.csv"

MIN_DOORS = 2
MAX_DOORS = 4

# Rooms are numbered 1..rooms, row by row, on a square grid whose width is
# isqrt(rooms) (5x5 for 25 rooms):
#    1  2  3  4  5
#    6  7  8  9 10
#   11 12 13 14 15
#   16 17 18 19 20
#   21 22 23 24 25
# Only rooms next to each other can share a door. Every room needs at least
# 2 doors, so the maze has loops and no dead ends.


class Maze(NamedTuple):
    rooms: int
    entrance: int
    exit: int
    doors: list
    adjacency: dict


def grid_width(rooms):
    """Width of the square grid; the room count must be a perfect square."""
    width = isqrt(rooms) if isinstance(rooms, int) and rooms > 0 else 0
    if width * width != rooms:
        raise ValueError(f"room count must be a positive perfect square, got {rooms!r}")
    return width


def build_maze(doors, rooms):
    """Adjacency list from the door list; each door is stored in both rooms."""
    if len({frozenset(d) for d in doors}) != len(doors):
        raise ValueError("duplicate door in the door list")
    g = {room: [] for room in range(1, rooms + 1)}
    for a, b in doors:
        for room in (a, b):
            if room not in g:
                raise ValueError(f"door {a}-{b} uses room {room}, which does not exist")
        g[a].append(b)
        g[b].append(a)
    return g


def is_symmetric(g):
    """Every door must be stored in both rooms."""
    return all(b in g and a in g[b] for a in g for b in g[a])


def is_connected(g):
    """True if every room can be reached from any other room."""
    return Graph(g, weighted=False).is_connected()


def is_grid_neighbour(a, b, width):
    """True if rooms a and b are next to each other on the grid."""
    (ra, ca), (rb, cb) = divmod(a - 1, width), divmod(b - 1, width)
    return abs(ra - rb) + abs(ca - cb) == 1


def validate(g, entrance, exit_, rooms):
    """Return a list of broken rules (empty list means the maze is valid)."""
    errors = []
    if set(g) != set(range(1, rooms + 1)):
        errors.append(f"rooms must be exactly the numbers 1-{rooms}")
        return errors
    width = grid_width(rooms)
    for room, doors in g.items():
        if any(d not in g for d in doors):
            errors.append(f"room {room} has a door to a room that does not exist")
            return errors
    for room, doors in g.items():
        if len(set(doors)) != len(doors):
            errors.append(f"room {room} lists the same door twice")
        if not MIN_DOORS <= len(doors) <= MAX_DOORS:
            errors.append(f"room {room} has {len(doors)} doors")
        if room in doors:
            errors.append(f"room {room} has a door to itself")
        for other in doors:
            if not is_grid_neighbour(room, other, width):
                errors.append(f"door {room}-{other} joins rooms that are not neighbours")
    if not is_symmetric(g):
        errors.append("a door is not stored in both rooms")
    if entrance not in g or exit_ not in g:
        errors.append("entrance or exit is not a room")
    elif entrance == exit_:
        errors.append("entrance and exit are the same room")
    if not is_connected(g):
        errors.append("maze is not connected")
    return errors


def _is_blank(row):
    """True if every cell of a csv.DictReader row is empty or whitespace."""
    cells = []
    for v in row.values():
        cells.extend(v if isinstance(v, list) else [v])
    return all(c is None or not c.strip() for c in cells)


def _int(path, line, what, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{path} line {line}: {what} must be an integer, got {raw!r}") from None


def _read_config(path):
    """Read the key,value file into {key: int}; entrance, exit and rooms are required."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"key", "value"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        config = {}
        for line, row in enumerate(reader, start=2):
            if _is_blank(row):
                continue
            key = (row["key"] or "").strip()
            if not key:
                raise ValueError(f"{path} line {line}: key must not be blank")
            if key in config:
                raise ValueError(f"{path} line {line}: duplicate key '{key}'")
            config[key] = _int(path, line, f"value of '{key}'", row["value"])
    for key in ("rooms", "entrance", "exit"):
        if key not in config:
            raise ValueError(f"{path}: missing key '{key}'")
    return config


def _read_doors(path):
    """Read the room_a,room_b file into a list of (a, b) tuples."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"room_a", "room_b"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        doors = []
        for line, row in enumerate(reader, start=2):
            if _is_blank(row):
                continue
            if None in row or row["room_b"] is None:
                raise ValueError(f"{path} line {line}: expected 2 values room_a,room_b")
            doors.append((_int(path, line, "room_a", row["room_a"]),
                          _int(path, line, "room_b", row["room_b"])))
    return doors


def load_maze(doors_path=DEFAULT_DOORS_PATH, config_path=DEFAULT_CONFIG_PATH):
    """Read the maze from two CSV files, validate it and return a Maze.

    Config file: header key,value with rows rooms, entrance, exit.
    Doors file: header room_a,room_b, one row per door.
    Raises ValueError on malformed rows or listing the broken rules if invalid.
    """
    config = _read_config(config_path)
    rooms, entrance, exit_ = config["rooms"], config["entrance"], config["exit"]
    doors = _read_doors(doors_path)
    grid_width(rooms)
    adjacency = build_maze(doors, rooms)
    problems = validate(adjacency, entrance, exit_, rooms)
    if problems:
        raise ValueError("invalid maze: " + "; ".join(problems))
    return Maze(rooms, entrance, exit_, doors, adjacency)


def door_table(doors):
    """Markdown table of all doors, for the report."""
    rows = ["| # | Room A | Room B |", "|---|---|---|"]
    for i, (a, b) in enumerate(sorted(doors), start=1):
        rows.append(f"| {i} | {a} | {b} |")
    return "\n".join(rows)


if __name__ == "__main__":
    loaded = load_maze()
    maze = loaded.adjacency
    for room in sorted(maze):
        print(f"{room}: {sorted(maze[room])}")
    print()
    print(door_table(loaded.doors))
    print()
    problems = validate(maze, loaded.entrance, loaded.exit, loaded.rooms)
    print(f"{len(maze)} rooms, {len(loaded.doors)} doors, "
          f"entrance {loaded.entrance}, exit {loaded.exit}")
    print("valid" if not problems else problems)
