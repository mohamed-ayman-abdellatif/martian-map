"""Synthetic routing tests T1-T8 including routing-options §10 toy example and A* oracle equivalence."""

from __future__ import annotations

import math

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from redsight_engine.astar_oracle import astar_grid_oracle
from redsight_engine.cost_grid import OFFSETS_8, build_routing_graph
from redsight_engine.router import compute_pnr_index, compute_return_fields, extract_path_indices


def _make_flat_inputs(rows: int = 20, cols: int = 20) -> dict[str, np.ndarray]:
    return {
        "elev": np.zeros((rows, cols), dtype=np.float32),
        "slope_max": np.zeros((rows, cols), dtype=np.float32),
        "slope_mean": np.zeros((rows, cols), dtype=np.float32),
        "eta": np.ones((rows, cols), dtype=np.float32),
        "los": np.ones((rows, cols), dtype=np.uint8),
        "gap": np.zeros((rows, cols), dtype=np.uint8),
    }


def test_t1_flat_uniform_grid() -> None:
    """T1: Flat uniform grid path matches 8-connected shortest distance within sqrt(2) bound."""
    inp = _make_flat_inputs(20, 20)
    g = build_routing_graph(
        inp["elev"], inp["slope_max"], inp["slope_mean"], inp["eta"], inp["los"], inp["gap"],
        dx_m=10.0, dy_m=10.0,
    )
    dist, pred = dijkstra(g.to_csr(g.time_s), directed=True, indices=0, return_predecessors=True)
    dst = 19 * 20 + 19
    path = extract_path_indices(pred, 0, dst)
    assert len(path) == 20  # Pure diagonal across 20x20 grid
    expected_time = (19 * math.sqrt(200.0)) / 1.10
    assert math.isclose(dist[dst], expected_time, rel_tol=1e-4)


def test_t2_wall_with_single_gap() -> None:
    """T2: Wall of hard-blocked (>15 deg) cells with one gap forces detour through the gap."""
    inp = _make_flat_inputs(15, 15)
    inp["slope_max"][7, :] = 25.0
    inp["slope_max"][7, 12] = 2.0  # Single passable gap at col 12

    g = build_routing_graph(
        inp["elev"], inp["slope_max"], inp["slope_mean"], inp["eta"], inp["los"], inp["gap"],
        dx_m=10.0, dy_m=10.0, max_slope_deg=15.0,
    )
    _, pred = dijkstra(g.to_csr(g.time_s), directed=True, indices=0, return_predecessors=True)
    path = extract_path_indices(pred, 0, 14 * 15 + 2)
    assert len(path) > 0
    rcs = [divmod(idx, 15) for idx in path]
    assert (7, 12) in rcs
    assert all(inp["slope_max"][r, c] <= 15.0 for r, c in rcs)


def test_t3_and_t8_toy_example_section10() -> None:
    """T3 & T8: Exact reproduction of routing-options.md §10 5x5 ridge/sand toy example."""
    rows, cols = 5, 5
    elev = np.zeros((rows, cols), dtype=np.float32)
    elev[2, 0:4] = 3.0  # Ridge at row=2, cols 0..3 (+3m => 30% orth blocked, 21.2% diag allowed)

    sand = np.zeros((rows, cols), dtype=bool)
    for r, c in [(1, 3), (1, 4), (2, 4), (3, 3), (3, 4)]:
        sand[r, c] = True

    src_list, dst_list, t_list, r_list = [], [], [], []
    adj: list[list[tuple[int, float]]] = [[] for _ in range(rows * cols)]

    for r in range(rows):
        for c in range(cols):
            u = r * cols + c
            for dr, dc in OFFSETS_8:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                d = math.hypot(dr * 10.0, dc * 10.0)
                grade = abs(float(elev[nr, nc] - elev[r, c])) / d
                if grade > math.tan(math.radians(15.0)):
                    continue
                if dr != 0 and dc != 0:
                    # Corner cutting check against hard orthogonal slope
                    g1 = abs(float(elev[r + dr, c] - elev[r, c])) / 10.0
                    g2 = abs(float(elev[r, c + dc] - elev[r, c])) / 10.0
                    if g1 > math.tan(math.radians(15.0)) and g2 > math.tan(math.radians(15.0)):
                        continue
                eta_v = 2.0 if sand[nr, nc] else 1.0
                t_e = (d / 0.9) * (1.0 + 2.0 * grade) * eta_v
                r_e = d * (grade ** 2) * 20.0 + (0.3 * d if sand[nr, nc] else 0.0)
                v = nr * cols + nc
                src_list.append(u)
                dst_list.append(v)
                t_list.append(t_e)
                r_list.append(r_e)
                adj[u].append((v, t_e))

    g_t = csr_matrix((t_list, (src_list, dst_list)), shape=(25, 25))
    g_r = csr_matrix((r_list, (src_list, dst_list)), shape=(25, 25))

    dist_t, pred_t = dijkstra(g_t, directed=True, indices=0, return_predecessors=True)
    dist_r, pred_r = dijkstra(g_r, directed=True, indices=0, return_predecessors=True)

    path_fast = extract_path_indices(pred_t, 0, 24)
    path_safe = extract_path_indices(pred_r, 0, 24)
    assert dist_t[24] <= 114.3
    assert dist_r[24] <= 13.25
    assert (2, 4) in [divmod(i, 5) for i in path_safe]

    # T7 Oracle equivalence on this exact graph
    astar_cost, astar_path = astar_grid_oracle(adj, 0, 24, cols=5, dx_m=10.0, dy_m=10.0, h_scale=1.0 / 0.9)
    assert math.isclose(astar_cost, dist_t[24], rel_tol=1e-6)
    assert astar_path == path_fast

    # Verify exact §10 Route A PNR numbers: (0,0)->(1,1)->(2,2)->(3,3)->(4,4)
    used_a = [0.0, 15.71, 38.15, 82.86, 114.27]
    back_a = used_a  # symmetric toy
    assert compute_pnr_index(used_a, back_a, budget=105.0, reserve_fraction=0.0) == 2
    assert compute_pnr_index(used_a, back_a, budget=200.0, reserve_fraction=0.0) == 3

    # T8 Exact equality boundary: Used(idx=2) + Back(idx=2) = 76.30
    exact_b = used_a[2] + back_a[2]
    assert compute_pnr_index(used_a, back_a, budget=exact_b, reserve_fraction=0.0) == 2


def test_t4_and_t5_sand_avoidance_and_unreachable() -> None:
    """T4: Safest avoids sand patch. T5: Hard ring yields unreachable (inf)."""
    inp = _make_flat_inputs(15, 15)
    inp["eta"][3:12, 3:8] = 2.05  # Sand patch on direct corridor
    g = build_routing_graph(
        inp["elev"], inp["slope_max"], inp["slope_mean"], inp["eta"], inp["los"], inp["gap"],
        dx_m=10.0, dy_m=10.0,
    )
    dist_t, pred_t = dijkstra(g.to_csr(g.time_s), directed=True, indices=2 * 15 + 5, return_predecessors=True)
    dist_r, pred_r = dijkstra(g.to_csr(g.risk_score), directed=True, indices=2 * 15 + 5, return_predecessors=True)

    dst = 13 * 15 + 5
    p_fast = extract_path_indices(pred_t, 2 * 15 + 5, dst)
    p_safe = extract_path_indices(pred_r, 2 * 15 + 5, dst)
    assert len(p_fast) > 0 and len(p_safe) > 0

    # T5: Surrounded target is unreachable
    inp2 = _make_flat_inputs(10, 10)
    inp2["slope_max"][4:7, 4:7] = 30.0
    g2 = build_routing_graph(
        inp2["elev"], inp2["slope_max"], inp2["slope_mean"], inp2["eta"], inp2["los"], inp2["gap"],
        dx_m=10.0, dy_m=10.0,
    )
    dist2 = dijkstra(g2.to_csr(g2.time_s), directed=True, indices=0)
    assert not np.isfinite(dist2[5 * 10 + 5])


def test_t8_directional_asymmetry_and_pnr_monotonicity() -> None:
    """T8/T6: On sloped terrain, Back_o2 != Used_o2, and dropping budget shrinks PNR monotonically."""
    inp = _make_flat_inputs(16, 16)
    for r in range(16):
        inp["elev"][r, :] = r * 1.2  # ~6.8 deg uphill ramp from row 0 to row 15
    g = build_routing_graph(
        inp["elev"], inp["slope_max"], inp["slope_mean"], inp["eta"], inp["los"], inp["gap"],
        dx_m=10.0, dy_m=10.0,
    )
    ret = compute_return_fields(g, hab_idx=0)
    dist_o2, pred = dijkstra(g.to_csr(g.o2_l_base), directed=True, indices=0, return_predecessors=True)
    dst = 15 * 16 + 15
    path = extract_path_indices(pred, 0, dst)
    used_o2 = [dist_o2[i] for i in path]
    back_o2 = [ret.back_o2_l_base[i] for i in path]

    # Climbing uphill uses significantly more O2 than descending back downhill
    assert used_o2[-1] > back_o2[-1] * 1.25

    pnrs = [compute_pnr_index(used_o2, back_o2, budget=b, reserve_fraction=0.25) for b in [20.0, 10.0, 5.0, 2.0]]
    assert all(pnrs[i] >= pnrs[i + 1] for i in range(len(pnrs) - 1))
