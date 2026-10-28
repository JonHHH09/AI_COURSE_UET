"""Tiny live hub: stdlib HTTP server + Server-Sent Events, run in a daemon thread.

Never writes to stdout (it is the MCP stdio channel); diagnostics go to stderr.
"""

import json
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HISTORY_LIMIT = 20
KEEPALIVE_S = 15
CLIENT_QUEUE_SIZE = 100
_INDEX = Path(__file__).with_name("index.html")

_lock = threading.Lock()
_server = None
_thread = None
_url = None
_history = []
_clients = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                self._send(200, _INDEX.read_bytes(), "text/html; charset=utf-8")
            elif path == "/sessions":
                with _lock:
                    snapshot = list(_history)
                self._json(snapshot)
            elif path == "/sessions/latest":
                with _lock:
                    latest = _history[-1] if _history else None
                if latest is None:
                    self._json({"error": "no sessions yet"}, 404)
                else:
                    self._json(latest)
            elif path == "/events":
                self._events()
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _events(self):
        q = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)
        with _lock:
            _clients.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=KEEPALIVE_S)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    if data is None:
                        break
                    self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with _lock:
                if q in _clients:
                    _clients.remove(q)


def _make_server(host, port):
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True   # request threads must never keep the process alive
    return server


def start(host="127.0.0.1", port=None):
    """Start the hub in a daemon thread. Returns its URL, or None if it cannot bind.

    A busy default port (no argument, no SEMINAR2_LIVE_PORT) falls back to a free
    one; an explicitly requested port that is busy returns None.
    """
    global _server, _thread, _url
    with _lock:
        if _server is not None:
            return _url
    explicit = port is not None or "SEMINAR2_LIVE_PORT" in os.environ
    if port is None:
        raw = os.environ.get("SEMINAR2_LIVE_PORT", "8765")
        try:
            port = int(raw)
        except ValueError:
            print(f"seminar2 live viewer disabled: bad SEMINAR2_LIVE_PORT {raw!r}", file=sys.stderr)
            return None
    try:
        server = _make_server(host, port)
    except (OSError, OverflowError) as exc:
        if explicit:
            print(f"seminar2 live viewer disabled: cannot bind {host}:{port} ({exc})", file=sys.stderr)
            return None
        print(f"seminar2 live viewer: port {port} busy ({exc}), using a free port", file=sys.stderr)
        try:
            server = _make_server(host, 0)
        except OSError as exc2:
            print(f"seminar2 live viewer disabled: cannot bind {host}:0 ({exc2})", file=sys.stderr)
            return None
    thread = threading.Thread(target=server.serve_forever, name="seminar2-live", daemon=True)
    thread.start()
    with _lock:
        _server, _thread = server, thread
        _url = f"http://{host}:{server.server_address[1]}/"
    print(f"seminar2 live viewer: {_url}", file=sys.stderr)
    return _url


def url():
    """The running URL, or None."""
    return _url


def _drain_and_close(q):
    """Make room and queue the stop signal so the client's handler thread ends."""
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass
    q.put_nowait(None)


def publish(session):
    """Store a session and push it to every connected viewer; no-op when not started."""
    if _server is None:
        return
    data = json.dumps(session, ensure_ascii=False).encode()
    with _lock:
        _history.append(session)
        del _history[:-HISTORY_LIMIT]
        for q in list(_clients):
            try:
                q.put_nowait(data)
            except queue.Full:   # stalled viewer: drop it, it reconnects and re-syncs
                _clients.remove(q)
                _drain_and_close(q)


def stop():
    """Shut the hub down and clear state (used by tests)."""
    global _server, _thread, _url
    with _lock:
        server, thread = _server, _thread
        _server = _thread = _url = None
        for q in _clients:
            _drain_and_close(q)
        _clients.clear()
        _history.clear()
    if server is not None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
