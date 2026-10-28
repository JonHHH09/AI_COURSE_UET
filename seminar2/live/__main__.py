"""Standalone viewer with two demo sessions:  uv run python -m seminar2.live [--port N] [--no-browser]"""

import argparse
import threading
import time
import webbrowser

from seminar2.cities.graph import load_graph
from seminar2.live import hub
from seminar2.live.session import city_session, maze_session
from seminar2.maze.maze import load_maze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=None, help="default: $SEMINAR2_LIVE_PORT or 8765")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = hub.start(port=args.port)
    if url is None:
        raise SystemExit("could not start the viewer (port busy?)")
    print(f"Live viewer: {url}  (Ctrl-C to stop)")
    if not args.no_browser:
        webbrowser.open(url)

    cities = load_graph()
    maze = load_maze()

    def demos():
        time.sleep(1.5)  # let the browser connect so it auto-plays the first one
        hub.publish(city_session(cities, "Shkodër", "Korçë", "demo"))
        hub.publish(maze_session(maze.adjacency, maze.entrance, maze.exit,
                                 maze.entrance, maze.exit, "demo"))

    threading.Thread(target=demos, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("bye")
        hub.stop()


if __name__ == "__main__":
    main()
