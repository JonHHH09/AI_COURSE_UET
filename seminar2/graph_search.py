"""Shared graph search for Seminar 2: Dijkstra, BFS and a small Graph class.

Pure Python (stdlib only). The searches take an `edges(node)` function that
yields (next_node, cost) pairs, so they work for any adjacency structure.
"""

import heapq
from collections import deque

from seminar2.text import plural


def _rebuild(prev, goal):
    """Walk the prev links back from goal and return the path start -> goal."""
    path = [goal]
    while prev.get(path[-1]) is not None:
        path.append(prev[path[-1]])
    return path[::-1]


def _event(kind, message, frontier, visited, dist, prev, **fields):
    """One trace step: a plain dict with fresh copies of the search state."""
    return {
        "type": kind,
        "message": message,
        **fields,
        "frontier": frontier,
        "visited": list(visited),
        "dist": dict(dist),
        "prev": dict(prev),
    }


def dijkstra_steps(edges, start, goal, unit="km"):
    """Dijkstra as a generator of JSON-serialisable step events.

    Types: start, pop, skip, relax, found (last), fail (last). Every event also
    has frontier (sorted [cost, node] heap contents), visited, dist and prev.
    """
    dist = {start: 0}
    prev = {start: None}
    visited = []
    heap = [(0, start)]

    def snap():
        return [list(item) for item in sorted(heap)]

    yield _event("start", f"Start at {start} with cost 0 {unit}; it is the only node on the frontier.",
                 snap(), visited, dist, prev, node=start)
    while heap:
        d, node = heapq.heappop(heap)
        if node == goal:
            visited.append(node)
            yield _event("pop", f"Pop {node} ({d} {unit}), the goal.",
                         snap(), visited, dist, prev, node=node, cost=d)
            path = _rebuild(prev, goal)
            yield _event("found", f"Goal reached: {' → '.join(map(str, path))} costs {d} {unit}.",
                         snap(), visited, dist, prev, path=path, cost=d)
            return
        if d > dist.get(node, float("inf")):
            yield _event("skip", f"Pop {node} ({d} {unit}), but a cheaper route ({dist[node]} {unit}) "
                                 "is already known, so this entry is stale; skip it.",
                         snap(), visited, dist, prev, node=node, cost=d)
            continue
        visited.append(node)
        yield _event("pop", f"Pop {node} ({d} {unit}), the cheapest node on the frontier.",
                     snap(), visited, dist, prev, node=node, cost=d)
        for nxt, cost in edges(node):
            nd = d + cost
            old = dist.get(nxt)
            improved = old is None or nd < old
            if improved:
                dist[nxt] = nd
                prev[nxt] = node
                heapq.heappush(heap, (nd, nxt))
                message = (f"Relax {node}→{nxt}: {d} + {cost} = {nd} {unit} is better than "
                           f"{'∞' if old is None else f'{old} {unit}'}, update.")
            else:
                message = (f"Relax {node}→{nxt}: {d} + {cost} = {nd} {unit} is not better than "
                           f"{old} {unit}, keep the old value.")
            yield _event("relax", message, snap(), visited, dist, prev,
                         **{"from": node, "to": nxt, "edge": cost, "new_cost": nd,
                            "old_cost": old, "improved": improved})
    yield _event("fail", f"The frontier is empty and {goal} was never reached: no route exists.",
                 [], visited, dist, prev)


def bfs_steps(edges, start, goal):
    """BFS as a generator of JSON-serialisable step events.

    Types: start, pop, discover, found (last), fail (last). dist is the depth in
    edges; frontier is the queue as a list of nodes.
    """
    prev = {start: None}
    dist = {start: 0}
    visited = []
    queue = deque([start])
    yield _event("start", f"Start at {start} ({plural(0, 'door')}); it is the only node in the queue.",
                 list(queue), visited, dist, prev, node=start)
    while queue:
        node = queue.popleft()
        visited.append(node)
        if node == goal:
            yield _event("pop", f"Take {node} ({plural(dist[node], 'door')}) from the queue, the goal.",
                         list(queue), visited, dist, prev, node=node, cost=dist[node])
            path = _rebuild(prev, goal)
            yield _event("found", f"Goal reached: {' → '.join(map(str, path))} in {plural(dist[node], 'door')}.",
                         list(queue), visited, dist, prev, path=path, cost=dist[node])
            return
        yield _event("pop", f"Take {node} ({plural(dist[node], 'door')}) from the front of the queue.",
                     list(queue), visited, dist, prev, node=node, cost=dist[node])
        for nxt, _ in edges(node):
            new = nxt not in prev
            if new:
                prev[nxt] = node
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
                message = f"Discover {nxt} from {node}: new, {plural(dist[nxt], 'door')}; add it to the queue."
            else:
                message = f"Look at {nxt} from {node}: already seen, ignore it."
            yield _event("discover", message, list(queue), visited, dist, prev,
                         **{"from": node, "to": nxt, "new": new})
    yield _event("fail", f"The queue is empty and {goal} was never reached: no path exists.",
                 [], visited, dist, prev)


def dijkstra(edges, start, goal):
    """Cheapest path by total cost. Returns (path, cost) or (None, None)."""
    for event in dijkstra_steps(edges, start, goal):
        if event["type"] == "found":
            return event["path"], event["cost"]
    return None, None


def bfs(edges, start, goal):
    """Path with the fewest edges (costs ignored). Returns the path or None.

    Ties are broken by the order in which `edges` yields neighbours.
    """
    for event in bfs_steps(edges, start, goal):
        if event["type"] == "found":
            return event["path"]
    return None


def build_steps(adjacency, weighted):
    """Trace reading an adjacency mapping into a graph, in insertion order.

    Yields add_node (node) and add_edge (a, b, cost; km if weighted else 1) once
    per undirected edge; every event carries the nodes and edges counts so far.
    """
    seen_nodes = []
    seen_edges = set()
    count = {"nodes": 0, "edges": 0}

    def node_event(node):
        seen_nodes.append(node)
        count["nodes"] += 1
        return {"type": "add_node", "message": f"Add node {node} to the graph.",
                "node": node, **count}

    for a, neighbours in adjacency.items():
        items = neighbours.items() if weighted else ((n, 1) for n in neighbours)
        for b, cost in items:
            key = frozenset((a, b))
            if key in seen_edges:
                continue
            for n in (a, b):
                if n not in seen_nodes:
                    yield node_event(n)
            seen_edges.add(key)
            count["edges"] += 1
            if weighted:
                message = f"Read road {a}–{b} ({cost} km); store it in both directions."
            else:
                message = f"Read door {a}–{b}; rooms {a} and {b} become neighbours."
            yield {"type": "add_edge", "message": message, "a": a, "b": b,
                   "cost": cost, **count}
    for n in adjacency:
        if n not in seen_nodes:
            yield node_event(n)


class Graph:
    """Undirected graph over an adjacency mapping.

    weighted=True:  adjacency is {node: {neighbour: cost}}.
    weighted=False: adjacency is {node: [neighbours]}, every edge costs 1.
    """

    def __init__(self, adjacency, weighted):
        self.adjacency = adjacency
        self.weighted = weighted

    def edges(self, node):
        """(neighbour, cost) pairs; unweighted neighbours come out sorted."""
        if self.weighted:
            return self.adjacency[node].items()
        return ((n, 1) for n in sorted(self.adjacency[node]))

    def shortest_path(self, start, goal):
        """(path, cost) or (None, None): Dijkstra if weighted, else BFS.

        An unknown start or goal gives (None, None).
        """
        if start not in self.adjacency or goal not in self.adjacency:
            return None, None
        if self.weighted:
            return dijkstra(self.edges, start, goal)
        path = bfs(self.edges, start, goal)
        return (path, len(path) - 1) if path else (None, None)

    def build_steps(self):
        """Trace of building this graph; see module-level build_steps."""
        return build_steps(self.adjacency, self.weighted)

    def search_steps(self, start, goal):
        """Step events of Dijkstra (weighted) or BFS; unknown node -> one fail."""
        for name, node in (("start", start), ("goal", goal)):
            if node not in self.adjacency:
                yield _event("fail", f"Unknown {name} node {node}: it is not in the graph.",
                             [], [], {}, {})
                return
        if self.weighted:
            yield from dijkstra_steps(self.edges, start, goal)
        else:
            yield from bfs_steps(self.edges, start, goal)

    def is_connected(self):
        """True if every node can be reached from any other (False if empty)."""
        if not self.adjacency:
            return False
        start = next(iter(self.adjacency))
        seen, stack = {start}, [start]
        while stack:
            for nxt, _ in self.edges(stack.pop()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return len(seen) == len(self.adjacency)

    def __contains__(self, node):
        return node in self.adjacency

    def __len__(self):
        return len(self.adjacency)

    def __iter__(self):
        return iter(self.adjacency)
