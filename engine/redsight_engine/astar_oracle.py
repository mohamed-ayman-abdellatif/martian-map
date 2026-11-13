"""Reference A* oracle with mode-scaled admissible heuristic (Review F5 / Test T7)."""

from __future__ import annotations

import heapq
import math

import numpy as np


def astar_grid_oracle(
    adj_neighbors: list[list[tuple[int, float]]],
    src_idx: int,
    dst_idx: int,
    cols: int,
    dx_m: float,
    dy_m: float,
    h_scale: float = 0.0,
) -> tuple[float, list[int]]:
    """Run scalarized A* on adjacency list with mode-scaled heuristic h(c) = h_scale * euclid(c, dst).

    - For pure time (Fastest): h_scale = 1.0 / (1.10 * v_max)
    - For Balanced (alpha * t/t_ref + (1-alpha) * r/r_ref): h_scale = alpha / (1.10 * v_max * t_ref)
    - For Safest (no cheap admissible lower bound on risk): h_scale = 0.0 (Dijkstra)
    """
    n = len(adj_neighbors)
    dst_r, dst_c = divmod(dst_idx, cols)
    g = np.full(n, np.inf, dtype=np.float64)
    parent = np.full(n, -1, dtype=np.int32)
    g[src_idx] = 0.0

    def h(idx: int) -> float:
        if h_scale <= 0.0:
            return 0.0
        r, c = divmod(idx, cols)
        return h_scale * math.hypot((dst_r - r) * dy_m, (dst_c - c) * dx_m)

    pq: list[tuple[float, int]] = [(h(src_idx), src_idx)]
    closed = np.zeros(n, dtype=bool)

    while pq:
        _, u = heapq.heappop(pq)
        if closed[u]:
            continue
        closed[u] = True
        if u == dst_idx:
            path = []
            cur = dst_idx
            while cur != -1:
                path.append(cur)
                cur = int(parent[cur])
            path.reverse()
            return float(g[dst_idx]), path

        gu = g[u]
        for v, w in adj_neighbors[u]:
            if closed[v]:
                continue
            cand = gu + w
            if cand < g[v]:
                g[v] = cand
                parent[v] = u
                heapq.heappush(pq, (cand + h(v), v))

    return float("inf"), []
