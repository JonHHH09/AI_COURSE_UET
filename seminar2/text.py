"""Small stdlib text helpers shared by the server, animations and viewer."""

import unicodedata


def fold(s):
    """Case- and accent-insensitive key: 'Durrës ' and 'durres' fold the same."""
    decomposed = unicodedata.normalize("NFD", s.strip().casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def plural(n, word):
    """'1 door', '2 doors', '0 doors'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
