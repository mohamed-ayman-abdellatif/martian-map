"""Deterministic Pandolf (1977) + Norcross suit overhead + O2 conversion + piecewise speed V(theta)."""

from __future__ import annotations

import math

HIDH_MIN_WATTS = 144.0


def speed_mps(theta_deg: float, v_max: float = 1.10) -> float:
    """Piecewise walking speed V(theta) in degrees (Review F5).

    - Level / uphill (theta >= 0): V_max * max(0.30, cos(2*theta))
    - Gentle downhill (-12 <= theta < 0): 1.10 * V_max
    - Steep downhill (theta < -12): linear taper down to 0.30 * V_max
    """
    if theta_deg >= 0.0:
        return v_max * max(0.30, math.cos(math.radians(2.0 * theta_deg)))
    if theta_deg >= -12.0:
        return 1.10 * v_max
    return v_max * max(0.30, 1.10 - 0.05 * (abs(theta_deg) - 12.0))


def pandolf_watts(
    body_mass_kg: float,
    load_kg: float,
    vel_mps: float,
    grade_pct: float,
    eta: float = 1.0,
    clamp_min: bool = True,
) -> float:
    """Pandolf, Givoni & Goldman (1977) metabolic rate [W].

    M = 1.5*W + 2.0*(W+L)*(L/W)^2 + eta*(W+L)*(1.5*V^2 + 0.35*V*G)
    Negative grades are floored at 0 in the grade term or clamped to HIDH min 144 W.
    """
    w = float(body_mass_kg)
    l = float(load_kg)
    v = float(vel_mps)
    g = float(grade_pct)
    m = 1.5 * w + 2.0 * (w + l) * ((l / w) ** 2) + eta * (w + l) * (1.5 * (v ** 2) + 0.35 * v * g)
    if clamp_min:
        return max(HIDH_MIN_WATTS, m)
    return m


def watts_to_o2_l_per_s(watts: float, kappa: float = 1.30, kj_per_l: float = 21.1) -> float:
    """Convert metabolic power [W] with suit overhead kappa to O2 consumption [L/s]."""
    return (watts * kappa) / (kj_per_l * 1000.0)


def watts_to_o2_l_per_h(watts: float, kappa: float = 1.30, kj_per_l: float = 21.1) -> float:
    """Convert metabolic power [W] with suit overhead kappa to O2 consumption [L/h]."""
    return watts_to_o2_l_per_s(watts, kappa=kappa, kj_per_l=kj_per_l) * 3600.0
