"""Shared node positions for drawings and viewers (pure stdlib)."""

# Hand-placed (x, y) positions, roughly following the real map.
CITY_POS = {
    "Shkodër": (0.0, 5.0),
    "Lezhë":   (1.0, 3.6),
    "Tirana":  (3.0, 3.0),
    "Durrës":  (1.6, 2.0),
    "Elbasan": (4.4, 1.8),
    "Fier":    (2.2, 0.4),
    "Vlorë":   (1.0, -0.8),
    "Korçë":   (6.4, 0.6),
}


def maze_position(room, width):
    """Room 1 is top left; rooms are numbered row by row. Returns (col, -row)."""
    row, col = divmod(room - 1, width)
    return col, -row
