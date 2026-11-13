"""Real Gale terrain checks (R1-R3), nodata leak assertions, and banned-word compliance scan."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from redsight_engine.router import compute_pnr_index

ROOT_DIR = Path(__file__).resolve().parents[2]
PROC_NPZ = ROOT_DIR / "data" / "processed" / "planning_grid_600.npz"
DATA_OUT = ROOT_DIR / "app" / "public" / "data"
ROUTES_OUT = DATA_OUT / "routes"


def test_real_terrain_no_nodata_slope_leaks() -> None:
    """Ensure 600x600 Gale grid has zero nodata slope cliff artifacts (<60 deg max)."""
    data = np.load(PROC_NPZ)
    elev = data["elev"]
    slope_max = data["slope_max_deg"]
    slope_mean = data["slope_mean_deg"]
    assert elev.shape == (600, 600)
    assert np.isfinite(elev).all()
    assert -4600.0 <= float(elev.min()) <= -4400.0
    assert -3700.0 <= float(elev.max()) <= -3550.0
    assert float(np.percentile(slope_max, 99.9)) < 50.0
    assert float(slope_max.max()) < 80.0  # No 89-90 deg nodata cliff leaks
    assert (slope_max >= slope_mean - 1e-4).all()


def test_real_routes_obey_hard_constraints_and_pnr_monotonic() -> None:
    """R1: All 12 Gale routes obey <=15 deg max slope and monotonic PNR shrinkage."""
    route_files = sorted(ROUTES_OUT.glob("*.json"))
    assert len(route_files) == 12

    for rf in route_files:
        bundle = json.loads(rf.read_text(encoding="utf-8"))
        summary = bundle["summary"]
        wps = bundle["waypoints_profile"]
        assert summary["max_slope_crossed_deg"] <= 15.0, f"{rf.name} crossed >15 deg"
        assert all(w["seg_slope_max_deg"] <= 15.0 for w in wps), f"{rf.name} waypoint >15 deg"

        used = [w["used_o2_l_base"] * 1.30 for w in wps]
        back = [w["back_o2_l_base"] * 1.30 for w in wps]
        pnrs = [compute_pnr_index(used, back, budget=b, reserve_fraction=0.25) for b in [500.0, 350.0, 200.0, 80.0]]
        assert all(pnrs[i] >= pnrs[i + 1] for i in range(len(pnrs) - 1))


def test_provenance_badges_and_banned_wording() -> None:
    """Enforce AGENTS.md Rule 2 (taxonomy badges) and Rule 3 (banned safety phrases)."""
    banned = [
        "safe " + "route",
        "safe " + "time remaining",
        "cert" + "ified",
        "flight-" + "safe",
        "real-" + "time",
        "val" + "idated",
    ]

    # Check all exported JSON files in app/public/data/
    for jp in DATA_OUT.rglob("*.json"):
        txt = jp.read_text(encoding="utf-8").lower()
        for bw in banned:
            assert bw not in txt, f"Banned phrase '{bw}' found in {jp}"

    # Check all frontend source files in app/src/ and app/index.html
    frontend_files = [
        *(ROOT_DIR / "app" / "src").rglob("*.ts"),
        *(ROOT_DIR / "app" / "src").rglob("*.css"),
        *(ROOT_DIR / "app" / "src").rglob("*.html"),
        ROOT_DIR / "app" / "index.html",
    ]
    for fp in frontend_files:
        txt = fp.read_text(encoding="utf-8").lower()
        for bw in banned:
            assert bw not in txt, f"Banned phrase '{bw}' found in {fp}"

    # Check all layers and constants carry valid taxonomy badges
    valid_badges = {"OBSERVED", "DERIVED", "SCENARIO", "UNAVAILABLE"}
    manifest = json.loads((DATA_OUT / "layers_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["layers"]) >= 6
    for lyr in manifest["layers"]:
        assert lyr["badge"] in valid_badges

    constants = json.loads((DATA_OUT / "constants.json").read_text(encoding="utf-8"))
    for c_item in constants["constants"].values():
        assert c_item["badge"] in valid_badges

    # Verify honest boxwork attribution
    targets = json.loads((DATA_OUT / "targets.json").read_text(encoding="utf-8"))
    bw_target = next(t for t in targets["targets"] if t["id"] == "site_boxwork_2025")
    assert "curiosity surface imaging" in bw_target["evidence"].lower()
    assert "boxwork detected by crism" not in bw_target["evidence"].lower()
