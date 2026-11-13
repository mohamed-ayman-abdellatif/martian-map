"""Scipy Dijkstra field solver (Review F2), mode presets, and Point-of-No-Return (PNR) computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.sparse.csgraph import dijkstra

from .cost_grid import RoutingGraph
from .crs import rowcol_to_lonlat


@dataclass
class ReturnFields:
    back_time_s: np.ndarray
    back_o2_l_base: np.ndarray


def compute_return_fields(graph: RoutingGraph, hab_idx: int) -> ReturnFields:
    """Run backward Dijkstra from habitat over reversed directed edges (Sachenbacher & Artmeier pattern)."""
    g_time_rev = graph.to_csr(graph.time_s).T.tocsr()
    g_o2_rev = graph.to_csr(graph.o2_l_base).T.tocsr()

    back_time = dijkstra(g_time_rev, directed=True, indices=hab_idx)
    back_o2 = dijkstra(g_o2_rev, directed=True, indices=hab_idx)
    return ReturnFields(back_time_s=back_time, back_o2_l_base=back_o2)


def extract_path_indices(predecessors: np.ndarray, src_idx: int, dst_idx: int) -> list[int]:
    """Reconstruct node path [src_idx, ..., dst_idx] from scipy predecessors array."""
    if src_idx == dst_idx:
        return [src_idx]
    if predecessors[dst_idx] < 0:
        return []
    path = []
    cur = int(dst_idx)
    guard = 0
    max_steps = len(predecessors)
    while cur != src_idx:
        path.append(cur)
        cur = int(predecessors[cur])
        if cur < 0 or guard > max_steps:
            return []
        guard += 1
    path.append(src_idx)
    path.reverse()
    return path


def compute_pnr_index(
    used: list[float] | np.ndarray,
    back: list[float] | np.ndarray,
    budget: float,
    reserve_fraction: float = 0.25,
) -> int:
    """Return farthest route waypoint index where Used(x) + Back(x) <= (1 - reserve) * budget."""
    usable = (1.0 - reserve_fraction) * budget
    pnr_idx = 0
    for i, (u, b) in enumerate(zip(used, back)):
        if np.isfinite(u) and np.isfinite(b) and (u + b) <= usable + 1e-9:
            pnr_idx = i
        else:
            break
    return pnr_idx


def solve_routes_for_targets(
    graph: RoutingGraph,
    return_fields: ReturnFields,
    hab_rc: tuple[int, int],
    targets: list[dict[str, Any]],
    elev: np.ndarray,
    slope_max_deg: np.ndarray,
    slope_mean_deg: np.ndarray,
    surf_eta: np.ndarray,
    los: np.ndarray,
    data_gap: np.ndarray,
    bbox: tuple[float, float, float, float],
    constants_hash: str,
    max_slope_deg: float = 15.0,
    alpha: float = 0.50,
    kappa_default: float = 1.30,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Solve Fastest, Safest, and Balanced routes for all targets via scipy Dijkstra (Review F2)."""
    rows, cols = graph.shape
    hab_idx = hab_rc[0] * cols + hab_rc[1]

    # Lookup map from (src, dst) -> edge index for exact attribute extraction
    edge_lookup: dict[tuple[int, int], int] = {}
    for e_i, (u, v) in enumerate(zip(graph.src_rows.tolist(), graph.dst_rows.tolist())):
        edge_lookup[(u, v)] = e_i

    g_fast = graph.to_csr(graph.time_s)
    g_safe = graph.to_csr(graph.risk_score)

    dist_fast, pred_fast = dijkstra(g_fast, directed=True, indices=hab_idx, return_predecessors=True)
    dist_safe, pred_safe = dijkstra(g_safe, directed=True, indices=hab_idx, return_predecessors=True)

    results: dict[tuple[str, str], dict[str, Any]] = {}

    for tgt in targets:
        t_id = tgt["id"]
        t_row, t_col = int(tgt["row"]), int(tgt["col"])
        dst_idx = t_row * cols + t_col

        t_ref = float(dist_fast[dst_idx])
        r_ref = float(dist_safe[dst_idx])
        if not np.isfinite(t_ref) or not np.isfinite(r_ref):
            raise RuntimeError(f"Target {t_id} at ({t_row},{t_col}) is unreachable under {max_slope_deg} deg limit")

        bal_weights = alpha * (graph.time_s / t_ref) + (1.0 - alpha) * (graph.risk_score / r_ref)
        g_bal = graph.to_csr(bal_weights)
        _, pred_bal = dijkstra(g_bal, directed=True, indices=hab_idx, return_predecessors=True)

        mode_specs = [
            ("fastest", pred_fast, 1.0, "Minimizes modeled excursion time using piecewise V(theta) and terrain factor eta."),
            ("balanced", pred_bal, alpha, "50% weight on modeled excursion time, 50% weight on modeled terrain hazard score."),
            ("safest", pred_safe, 0.0, "Lowest modeled hazard-score within available data (5-10 m slope, 100 m thermal proxy, LOS)."),
        ]

        for mode_name, preds, mode_alpha, caption in mode_specs:
            node_path = extract_path_indices(preds, hab_idx, dst_idx)
            if not node_path:
                raise RuntimeError(f"Empty path for {t_id} ({mode_name})")

            coords = []
            waypoints = []
            cum_dist = 0.0
            cum_time = 0.0
            cum_o2_base = 0.0
            slope_pen = 0.0
            sand_pen = 0.0
            gap_pen = 0.0
            los_pen = 0.0
            max_slope_crossed = 0.0
            slope_samples = []
            los_hits = 0

            for step_i, n_idx in enumerate(node_path):
                r, c = divmod(n_idx, cols)
                lon, lat = rowcol_to_lonlat(r, c, bbox, (rows, cols))
                z = float(elev[r, c])
                s_max = float(slope_max_deg[r, c])
                s_mean = float(slope_mean_deg[r, c])
                eta_val = float(surf_eta[r, c])
                los_val = int(los[r, c])
                gap_val = int(data_gap[r, c])
                max_slope_crossed = max(max_slope_crossed, s_max)
                slope_samples.append(s_mean)
                los_hits += los_val

                reason = "firm low-slope ground"
                if step_i > 0:
                    prev_idx = node_path[step_i - 1]
                    e_i = edge_lookup[(prev_idx, n_idx)]
                    d_step = float(graph.dist_m[e_i])
                    t_step = float(graph.time_s[e_i])
                    o2_step = float(graph.o2_l_base[e_i])
                    theta_step = float(graph.theta_deg[e_i])
                    cum_dist += d_step
                    cum_time += t_step
                    cum_o2_base += o2_step

                    s_term = d_step * (max(0.0, max(abs(theta_step), s_mean) - 4.0) / 2.0) ** 2
                    sa_term = d_step * 0.6 * max(0.0, eta_val - 1.2)
                    gp_term = d_step * 3.0 * gap_val
                    ls_term = d_step * 0.35 * (1 - los_val)
                    slope_pen += s_term
                    sand_pen += sa_term
                    gap_pen += gp_term
                    los_pen += ls_term

                    if s_term >= max(sa_term, ls_term, 0.5):
                        reason = f"{s_mean:.1f} deg slope grade"
                    elif sa_term >= max(s_term, ls_term, 0.5):
                        reason = f"100m THEMIS sand proxy (eta={eta_val:.2f})"
                    elif ls_term > 0.1:
                        reason = "beyond habitat geometric LOS"

                coords.append([lon, lat, round(z, 2)])
                waypoints.append(
                    {
                        "idx": step_i,
                        "row": r,
                        "col": c,
                        "lon": lon,
                        "lat": lat,
                        "elev_m": round(z, 2),
                        "cum_dist_m": round(cum_dist, 1),
                        "seg_slope_mean_deg": round(s_mean, 2),
                        "seg_slope_max_deg": round(s_max, 2),
                        "surf_eta": round(eta_val, 3),
                        "los": los_val,
                        "used_time_s": round(cum_time, 1),
                        "back_time_s": round(float(return_fields.back_time_s[n_idx]), 1),
                        "used_o2_l_base": round(cum_o2_base, 3),
                        "back_o2_l_base": round(float(return_fields.back_o2_l_base[n_idx]), 3),
                        "dominant_cost_reason": reason,
                    }
                )

            out_bundle = {
                "goal_id": t_id,
                "goal_name": tgt["name"],
                "mode": mode_name,
                "mode_caption": caption,
                "alpha": mode_alpha,
                "constants_hash": constants_hash,
                "reference_norms": {
                    "t_ref_s": round(t_ref, 1),
                    "r_ref_score": round(r_ref, 1),
                },
                "summary": {
                    "distance_m": round(cum_dist, 1),
                    "outbound_time_s": round(cum_time, 1),
                    "return_time_from_goal_s": round(float(return_fields.back_time_s[dst_idx]), 1),
                    "outbound_o2_liters_base": round(cum_o2_base, 2),
                    "return_o2_from_goal_liters_base": round(float(return_fields.back_o2_l_base[dst_idx]), 2),
                    "default_kappa": kappa_default,
                    "max_slope_crossed_deg": round(max_slope_crossed, 2),
                    "mean_slope_deg": round(float(np.mean(slope_samples)), 2),
                    "hard_limit_deg": max_slope_deg,
                    "los_coverage_pct": round(100.0 * los_hits / len(node_path), 1),
                    "hazard_breakdown": {
                        "slope_penalty": round(slope_pen, 1),
                        "sand_ti_penalty": round(sand_pen, 1),
                        "data_gap_penalty": round(gap_pen, 1),
                        "los_penalty": round(los_pen, 1),
                        "total_hazard_score": round(slope_pen + sand_pen + gap_pen + los_pen, 1),
                    },
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
                "waypoints_profile": waypoints,
            }
            results[(t_id, mode_name)] = out_bundle

    return results
