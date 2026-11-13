"""Vectorized 8-connected directed CSR graph builder for RedSight."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from .metabolism import HIDH_MIN_WATTS


OFFSETS_8 = [
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
]


def speed_mps_vec(theta_deg: np.ndarray, v_max: float = 1.10) -> np.ndarray:
    """Vectorized piecewise walking speed V(theta) in degrees (Review F5)."""
    v = np.empty_like(theta_deg, dtype=np.float64)
    up_mask = theta_deg >= 0.0
    gentle_dn = (theta_deg < 0.0) & (theta_deg >= -12.0)
    steep_dn = theta_deg < -12.0

    v[up_mask] = v_max * np.maximum(0.30, np.cos(np.radians(2.0 * theta_deg[up_mask])))
    v[gentle_dn] = 1.10 * v_max
    v[steep_dn] = v_max * np.maximum(0.30, 1.10 - 0.05 * (np.abs(theta_deg[steep_dn]) - 12.0))
    return v


@dataclass
class RoutingGraph:
    shape: tuple[int, int]
    dx_m: float
    dy_m: float
    src_rows: np.ndarray
    dst_rows: np.ndarray
    dist_m: np.ndarray
    time_s: np.ndarray
    o2_l_base: np.ndarray
    risk_score: np.ndarray
    theta_deg: np.ndarray
    blocked_cell: np.ndarray

    def to_csr(self, weights: np.ndarray) -> csr_matrix:
        n_nodes = self.shape[0] * self.shape[1]
        return csr_matrix((weights, (self.src_rows, self.dst_rows)), shape=(n_nodes, n_nodes))


def build_routing_graph(
    elev: np.ndarray,
    slope_max_deg: np.ndarray,
    slope_mean_deg: np.ndarray,
    surf_eta: np.ndarray,
    los: np.ndarray,
    data_gap: np.ndarray,
    dx_m: float,
    dy_m: float,
    max_slope_deg: float = 15.0,
    body_mass_kg: float = 80.0,
    load_kg: float = 30.0,
    v_max_mps: float = 1.10,
    kj_per_l_o2: float = 21.1,
    w_slope: float = 1.0,
    w_sand: float = 0.6,
    w_gap: float = 3.0,
    w_los: float = 0.35,
    block_gaps: bool = False,
) -> RoutingGraph:
    """Build directed 8-connected CSR edge arrays with hard slope & corner-cutting guards."""
    rows, cols = elev.shape
    blocked = slope_max_deg > max_slope_deg
    if block_gaps:
        blocked = blocked | (data_gap > 0)

    src_list = []
    dst_list = []
    dist_list = []
    time_list = []
    o2_list = []
    risk_list = []
    theta_list = []

    base_r, base_c = np.meshgrid(np.arange(rows, dtype=np.int32), np.arange(cols, dtype=np.int32), indexing="ij")

    for dr, dc in OFFSETS_8:
        r0_start = max(0, -dr)
        r0_end = rows - max(0, dr)
        c0_start = max(0, -dc)
        c0_end = cols - max(0, dc)

        r_from = base_r[r0_start:r0_end, c0_start:c0_end]
        c_from = base_c[r0_start:r0_end, c0_start:c0_end]
        r_to = r_from + dr
        c_to = c_from + dc

        valid = (~blocked[r_from, c_from]) & (~blocked[r_to, c_to])
        if dr != 0 and dc != 0:
            # Disallow diagonal corner-cutting across hard-blocked cardinal neighbors
            valid &= (~blocked[r_from + dr, c_from]) & (~blocked[r_from, c_from + dc])

        rf = r_from[valid]
        cf = c_from[valid]
        rt = r_to[valid]
        ct = c_to[valid]

        d_step = math.hypot(dr * dy_m, dc * dx_m)
        dz = elev[rt, ct].astype(np.float64) - elev[rf, cf].astype(np.float64)
        theta = np.degrees(np.arctan2(dz, d_step))
        grade_pct = 100.0 * (dz / d_step)

        eta_to = surf_eta[rt, ct].astype(np.float64)
        vel = speed_mps_vec(theta, v_max=v_max_mps)
        # Mild terrain slowdown from loose sand proxy eta
        t_step = (d_step / vel) * (0.65 + 0.35 * eta_to)

        # Pandolf metabolic power with mean cell slope correction when cell mean exceeds step grade
        g_eff = np.maximum(0.0, grade_pct)
        watts = (
            1.5 * body_mass_kg
            + 2.0 * (body_mass_kg + load_kg) * ((load_kg / body_mass_kg) ** 2)
            + eta_to * (body_mass_kg + load_kg) * (1.5 * (vel ** 2) + 0.35 * vel * g_eff)
        )
        watts = np.maximum(HIDH_MIN_WATTS, watts)
        o2_base = (watts * t_step) / (kj_per_l_o2 * 1000.0)

        slope_ref = np.maximum(np.abs(theta), slope_mean_deg[rt, ct].astype(np.float64))
        slope_term = w_slope * (np.maximum(0.0, slope_ref - 4.0) / 2.0) ** 2
        sand_term = w_sand * np.maximum(0.0, eta_to - 1.2)
        gap_term = w_gap * data_gap[rt, ct].astype(np.float64)
        los_term = w_los * (1.0 - los[rt, ct].astype(np.float64))
        risk_step = d_step * (0.05 + slope_term + sand_term + gap_term + los_term)

        src_list.append((rf * cols + cf).astype(np.int32))
        dst_list.append((rt * cols + ct).astype(np.int32))
        dist_list.append(np.full(rf.shape, d_step, dtype=np.float32))
        time_list.append(t_step.astype(np.float64))
        o2_list.append(o2_base.astype(np.float64))
        risk_list.append(risk_step.astype(np.float64))
        theta_list.append(theta.astype(np.float32))

    return RoutingGraph(
        shape=(rows, cols),
        dx_m=dx_m,
        dy_m=dy_m,
        src_rows=np.concatenate(src_list),
        dst_rows=np.concatenate(dst_list),
        dist_m=np.concatenate(dist_list),
        time_s=np.concatenate(time_list),
        o2_l_base=np.concatenate(o2_list),
        risk_score=np.concatenate(risk_list),
        theta_deg=np.concatenate(theta_list),
        blocked_cell=blocked,
    )
