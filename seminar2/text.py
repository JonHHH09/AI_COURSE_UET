"""Small stdlib text helpers shared by the server, animations and viewer."""

import sys
import unicodedata


def fold(s):
    """Case- and accent-insensitive key: 'Durrës ' and 'durres' fold the same."""
    decomposed = unicodedata.normalize("NFD", s.strip().casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def printable(s, stream=None):
    """`s` made safe to print on a stream whose encoding lacks some characters.

    A piped stdout on Windows is cp1252, which has no '→'; print() would raise
    UnicodeEncodeError. Arrows become '->', anything else unencodable becomes '?'.
    """
    encoding = getattr(stream or sys.stdout, "encoding", None) or "ascii"
    try:
        s.encode(encoding)
        return s
    except UnicodeEncodeError:
        return s.replace("→", "->").encode(encoding, "replace").decode(encoding)


def plural(n, word):
    """'1 door', '2 doors', '0 doors'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
