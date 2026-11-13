"""Unit tests for Pandolf metabolism, O2 conversion, piecewise V(theta), and T6 monotonicity."""

from __future__ import annotations

import math

import pytest

from redsight_engine.metabolism import (
    HIDH_MIN_WATTS,
    pandolf_watts,
    speed_mps,
    watts_to_o2_l_per_h,
)


def test_pandolf_hand_checks() -> None:
    """Verify against hand calculations in docs/research/routing-options.md §3.6 & review §1.3."""
    # Level walking: W=80, L=30, V=0.9, G=0, eta=1.0 -> 284.6 W
    w_level = pandolf_watts(80.0, 30.0, 0.9, 0.0, eta=1.0, clamp_min=False)
    assert math.isclose(w_level, 284.625, abs_tol=0.1)

    # 11.9 deg ridge diagonal: G = 21.2% -> ~1019 W
    w_ridge = pandolf_watts(80.0, 30.0, 0.9, 21.2, eta=1.0, clamp_min=False)
    assert 1015.0 <= w_ridge <= 1025.0

    # Suited O2 at kappa=1.3 (~63 L/h on 284.6 W)
    o2_l_h = watts_to_o2_l_per_h(w_level, kappa=1.30, kj_per_l=21.1)
    assert 62.0 <= o2_l_h <= 64.5


def test_downhill_hidh_floor() -> None:
    """Ensure steep downhill clamp prevents non-physical negative watts."""
    w_down = pandolf_watts(80.0, 30.0, 0.9, -30.0, eta=1.0, clamp_min=True)
    assert w_down == HIDH_MIN_WATTS


def test_piecewise_speed_asymmetry_f5() -> None:
    """Verify Review F5: piecewise V(theta) is asymmetric (uphill != downhill) and monotone on each branch."""
    v0 = speed_mps(0.0, v_max=1.10)
    v_up5 = speed_mps(5.0, v_max=1.10)
    v_up15 = speed_mps(15.0, v_max=1.10)
    v_dn5 = speed_mps(-5.0, v_max=1.10)
    v_dn20 = speed_mps(-20.0, v_max=1.10)

    assert math.isclose(v0, 1.10, abs_tol=1e-6)
    assert v_dn5 > v0 > v_up5 > v_up15
    assert v_dn5 > v_dn20
    assert v_up15 >= 0.30 * 1.10 - 1e-9


def test_t6_monotonicity_load_and_kappa() -> None:
    """T6: Increasing load L or suit overhead kappa strictly increases O2 consumption."""
    loads = [10.0, 20.0, 30.0, 40.0, 50.0]
    watts_list = [pandolf_watts(80.0, l, 0.9, 5.0, eta=1.2) for l in loads]
    assert all(watts_list[i] < watts_list[i + 1] for i in range(len(watts_list) - 1))

    kappas = [1.20, 1.30, 1.40, 1.50]
    o2_list = [watts_to_o2_l_per_h(watts_list[2], kappa=k) for k in kappas]
    assert all(o2_list[i] < o2_list[i + 1] for i in range(len(o2_list) - 1))
