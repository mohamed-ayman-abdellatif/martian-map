"""End-to-end offline engine pipeline: rasters, routing, tiles/overlays, and JSON contracts."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

import sys

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = ENGINE_DIR.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from redsight_engine.cost_grid import build_routing_graph
from redsight_engine.crs import DEFAULT_BBOX, cell_spacing_m, lonlat_to_rowcol, rowcol_to_lonlat
from redsight_engine.rasters import (
    aggregate_planning_grid,
    compute_hillshade,
    compute_sky_view_factor,
    compute_viewshed_los,
    load_dem_tiff,
    themis_to_surface_proxy,
)
from redsight_engine.router import compute_return_fields, solve_routes_for_targets

RAW_DIR = ROOT_DIR / "data" / "raw"
PROC_DIR = ROOT_DIR / "data" / "processed"
APP_PUBLIC = ROOT_DIR / "app" / "public"
DATA_OUT = APP_PUBLIC / "data"
ROUTES_OUT = DATA_OUT / "routes"
LAYERS_OUT = APP_PUBLIC / "layers"


def snap_to_walkable(
    lon: float,
    lat: float,
    slope_max_deg: np.ndarray,
    bbox: tuple[float, float, float, float],
    max_allowed_deg: float,
    search_radius_px: int = 20,
) -> tuple[int, int, float, float]:
    """Snap target/habitat to nearest cell below max_allowed_deg slope."""
    rows, cols = slope_max_deg.shape
    r0, c0 = lonlat_to_rowcol(lon, lat, bbox, (rows, cols))
    if slope_max_deg[r0, c0] <= max_allowed_deg:
        slon, slat = rowcol_to_lonlat(r0, c0, bbox, (rows, cols))
        return r0, c0, slon, slat

    best_rc = (r0, c0)
    best_d2 = 1e12
    for dr in range(-search_radius_px, search_radius_px + 1):
        for dc in range(-search_radius_px, search_radius_px + 1):
            rr, cc = r0 + dr, c0 + dc
            if 2 <= rr < rows - 2 and 2 <= cc < cols - 2:
                if slope_max_deg[rr, cc] <= max_allowed_deg:
                    d2 = dr * dr + dc * dc
                    if d2 < best_d2:
                        best_d2 = d2
                        best_rc = (rr, cc)
    slon, slat = rowcol_to_lonlat(best_rc[0], best_rc[1], bbox, (rows, cols))
    return best_rc[0], best_rc[1], slon, slat


def render_slope_rgba(slope_max_deg: np.ndarray) -> Image.Image:
    """Render RGBA slope hazard overlay: transparent <8 deg, amber 8-15 deg, crimson >15 deg."""
    h, w = slope_max_deg.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    caution = (slope_max_deg >= 8.0) & (slope_max_deg <= 15.0)
    hard = slope_max_deg > 15.0

    t_caut = np.clip((slope_max_deg[caution] - 8.0) / 7.0, 0.0, 1.0)
    rgba[caution, 0] = 245
    rgba[caution, 1] = (180 - 70 * t_caut).astype(np.uint8)
    rgba[caution, 2] = 35
    rgba[caution, 3] = (90 + 85 * t_caut).astype(np.uint8)

    rgba[hard, 0] = 239
    rgba[hard, 1] = 45
    rgba[hard, 2] = 58
    rgba[hard, 3] = 205
    return Image.fromarray(rgba, mode="RGBA")


def render_themis_rgba(ti_grid: np.ndarray) -> Image.Image:
    """Render 100 m blocky THEMIS thermal inertia proxy (low TI sand = orange, high TI rock = cyan-blue)."""
    norm = np.clip((ti_grid - 140.0) / 240.0, 0.0, 1.0)
    h, w = ti_grid.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    # Low TI (0.0 -> loose sand proxy) = warm orange (245, 130, 32); High TI (1.0 -> bedrock) = cool slate-cyan (46, 168, 214)
    rgba[..., 0] = (245 * (1.0 - norm) + 46 * norm).astype(np.uint8)
    rgba[..., 1] = (130 * (1.0 - norm) + 168 * norm).astype(np.uint8)
    rgba[..., 2] = (32 * (1.0 - norm) + 214 * norm).astype(np.uint8)
    rgba[..., 3] = 170
    return Image.fromarray(rgba, mode="RGBA")


def render_viewshed_rgba(los: np.ndarray) -> Image.Image:
    """Render geometric LOS layer: subtle cyan where visible, violet shadow where occluded."""
    h, w = los.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    vis = los == 1
    occ = ~vis
    rgba[vis] = [34, 211, 238, 65]
    rgba[occ] = [88, 28, 135, 145]
    return Image.fromarray(rgba, mode="RGBA")


def render_reachability_rgba(back_o2_l_base: np.ndarray, kappa: float = 1.30, budget_l: float = 420.0, reserve: float = 0.25) -> Image.Image:
    """Render round-trip reachable envelope contour from backward-Dijkstra O2 field."""
    h, w = back_o2_l_base.shape
    usable = (1.0 - reserve) * budget_l
    roundtrip_est = 2.0 * back_o2_l_base * kappa  # approximate round-trip ring proxy for visual backdrop
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    finite = np.isfinite(roundtrip_est)
    frac = np.where(finite, roundtrip_est / usable, 2.0)

    inner = finite & (frac <= 0.50)
    mid = finite & (frac > 0.50) & (frac <= 0.85)
    outer = finite & (frac > 0.85) & (frac <= 1.00)
    beyond = (~finite) | (frac > 1.00)

    rgba[inner] = [16, 185, 129, 75]
    rgba[mid] = [56, 189, 248, 70]
    rgba[outer] = [245, 158, 11, 85]
    rgba[beyond] = [15, 23, 42, 130]
    return Image.fromarray(rgba, mode="RGBA")


def clean_crism_png(src_path: Path, dst_path: Path) -> None:
    """Make near-black nodata background pixels transparent in CRISM browse PNGs."""
    with Image.open(src_path) as im:
        arr = np.array(im.convert("RGBA"))
    dark = (arr[..., 0] < 18) & (arr[..., 1] < 18) & (arr[..., 2] < 18)
    arr[dark, 3] = 0
    arr[~dark, 3] = 195
    Image.fromarray(arr, mode="RGBA").save(dst_path, format="PNG")


def build_solar_curve() -> list[dict[str, float]]:
    """Compute representative Gale Crater (-4.7 deg lat, Ls ~101 deg) daylight elevation profile."""
    lat_rad = math.radians(-4.70)
    decl_rad = math.radians(24.5)  # near northern summer solstice (Ls ~101 deg)
    pts = []
    for hour in np.linspace(5.5, 18.5, 27):
        ha = math.radians((hour - 12.0) * 15.0)
        sin_el = math.sin(lat_rad) * math.sin(decl_rad) + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(ha)
        el_deg = math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))
        pts.append({"local_solar_hour": round(float(hour), 2), "sun_elevation_deg": round(el_deg, 1)})
    return pts


def main() -> None:
    t_start = time.perf_counter()
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    ROUTES_OUT.mkdir(parents=True, exist_ok=True)
    LAYERS_OUT.mkdir(parents=True, exist_ok=True)

    constants_raw = (ENGINE_DIR / "config" / "constants.json").read_bytes()
    constants_hash = "sha256:" + hashlib.sha256(constants_raw).hexdigest()[:16]
    constants_cfg = json.loads(constants_raw.decode("utf-8"))
    targets_cfg = json.loads((ENGINE_DIR / "config" / "targets.json").read_text(encoding="utf-8"))

    bbox = tuple(float(x) for x in constants_cfg["ops_bbox_lonlat"])
    c_vals = constants_cfg["constants"]
    max_slope = float(c_vals["max_slope_deg"]["value"])
    body_mass = float(c_vals["crew_body_mass_kg"]["value"])
    load_kg = float(c_vals["carried_load_default_kg"]["value"])
    v_max = float(c_vals["walk_v_max_mps"]["value"])
    kj_per_l = float(c_vals["o2_energy_kj_per_l"]["value"])
    kappa_def = float(c_vals["suit_overhead_kappa"]["value"])
    budget_def = float(c_vals["nominal_o2_tank_liters"]["value"])
    reserve_def = float(c_vals["return_reserve_fraction"]["value"])

    # 1. Load & condition rasters
    dem_1200, nodata_1200 = load_dem_tiff(RAW_DIR / "gale_dem_1200.tif")
    grid = aggregate_planning_grid(dem_1200, nodata_1200, bbox, target_shape=(600, 600))
    elev = grid["elev"]
    slope_max = grid["slope_max_deg"]
    slope_mean = grid["slope_mean_deg"]
    data_gap = grid["data_gap"]

    dx_1200, dy_1200 = cell_spacing_m(bbox, (1200, 1200))
    dx_600, dy_600 = cell_spacing_m(bbox, (600, 600))
    hillshade_1200 = compute_hillshade(dem_1200, dx_1200, dy_1200)

    themis_60 = np.load(RAW_DIR / "themis_nir_60x60.npy")
    ti_grid, surf_eta = themis_to_surface_proxy(themis_60, target_shape=(600, 600))

    # 2. Snap habitat & targets to walkable cells
    hab_cfg = targets_cfg["habitat"]
    hab_r, hab_c, hab_lon, hab_lat = snap_to_walkable(
        hab_cfg["lon"], hab_cfg["lat"], slope_max, bbox, max_allowed_deg=6.0
    )
    hab_elev = float(elev[hab_r, hab_c])

    los = compute_viewshed_los(elev, (hab_r, hab_c), dx_600, dy_600)
    svf = compute_sky_view_factor(elev, dx_600, dy_600)

    snapped_targets: list[dict[str, Any]] = []
    for t in targets_cfg["targets"]:
        tr, tc, tlon, tlat = snap_to_walkable(t["lon"], t["lat"], slope_max, bbox, max_allowed_deg=11.0)
        snapped_targets.append(
            {
                **t,
                "row": tr,
                "col": tc,
                "lon": tlon,
                "lat": tlat,
                "elev_m": round(float(elev[tr, tc]), 1),
                "slope_max_deg": round(float(slope_max[tr, tc]), 1),
                "los_visible": bool(los[tr, tc] == 1),
                "sky_view_factor": round(float(svf[tr, tc]), 3),
            }
        )

    # 3. Build CSR graph & run Scipy Dijkstra (Review F2)
    t_graph0 = time.perf_counter()
    graph = build_routing_graph(
        elev=elev,
        slope_max_deg=slope_max,
        slope_mean_deg=slope_mean,
        surf_eta=surf_eta,
        los=los,
        data_gap=data_gap,
        dx_m=dx_600,
        dy_m=dy_600,
        max_slope_deg=max_slope,
        body_mass_kg=body_mass,
        load_kg=load_kg,
        v_max_mps=v_max,
        kj_per_l_o2=kj_per_l,
    )
    hab_idx = hab_r * 600 + hab_c
    ret_fields = compute_return_fields(graph, hab_idx)
    route_bundles = solve_routes_for_targets(
        graph=graph,
        return_fields=ret_fields,
        hab_rc=(hab_r, hab_c),
        targets=snapped_targets,
        elev=elev,
        slope_max_deg=slope_max,
        slope_mean_deg=slope_mean,
        surf_eta=surf_eta,
        los=los,
        data_gap=data_gap,
        bbox=bbox,
        constants_hash=constants_hash,
        max_slope_deg=max_slope,
        alpha=0.50,
        kappa_default=kappa_def,
    )
    print(f"Graph + Scipy Dijkstra (all fields + 12 routes) solved in {time.perf_counter() - t_graph0:.2f} s")

    # 4. Save processed NPZ for test verification
    np.savez_compressed(
        PROC_DIR / "planning_grid_600.npz",
        elev=elev,
        slope_max_deg=slope_max,
        slope_mean_deg=slope_mean,
        data_gap=data_gap,
        ti_grid=ti_grid,
        surf_eta=surf_eta,
        los=los,
        svf=svf,
        back_time_s=ret_fields.back_time_s.reshape(600, 600),
        back_o2_l_base=ret_fields.back_o2_l_base.reshape(600, 600),
    )

    # 5. Render raster overlays into app/public/layers/
    shutil.copy2(RAW_DIR / "hirise_ortho_1200.jpg", LAYERS_OUT / "hirise_base.jpg")
    Image.fromarray(hillshade_1200, mode="L").save(LAYERS_OUT / "hillshade.png", format="PNG")
    render_slope_rgba(slope_max).save(LAYERS_OUT / "slope_hazard.png", format="PNG")
    render_themis_rgba(ti_grid).save(LAYERS_OUT / "themis_ti_blocky.png", format="PNG")
    clean_crism_png(RAW_DIR / "crism_hydrated.png", LAYERS_OUT / "crism_hydrated.png")
    clean_crism_png(RAW_DIR / "crism_phyllosilicate.png", LAYERS_OUT / "crism_phyllosilicate.png")
    shutil.copy2(RAW_DIR / "sim3292_overlay.png", LAYERS_OUT / "sim3292_geology.png")
    render_viewshed_rgba(los).save(LAYERS_OUT / "viewshed_los.png", format="PNG")
    render_reachability_rgba(
        ret_fields.back_o2_l_base.reshape(600, 600),
        kappa=kappa_def,
        budget_l=budget_def,
        reserve=reserve_def,
    ).save(LAYERS_OUT / "reachability_field.png", format="PNG")

    # 6. Export JSON contracts into app/public/data/
    (DATA_OUT / "constants.json").write_text(constants_raw.decode("utf-8"), encoding="utf-8")

    for (goal_id, mode_name), bundle in route_bundles.items():
        (ROUTES_OUT / f"{goal_id}_{mode_name}.json").write_text(
            json.dumps(bundle, separators=(",", ":")), encoding="utf-8"
        )

    # Targets JSON
    targets_payload = {
        "habitat": {
            "id": hab_cfg["id"],
            "name": hab_cfg["name"],
            "lon": hab_lon,
            "lat": hab_lat,
            "elev_m": round(hab_elev, 1),
            "badge": "SCENARIO",
            "description": hab_cfg["description"],
        },
        "targets": snapped_targets,
    }
    (DATA_OUT / "targets.json").write_text(json.dumps(targets_payload, indent=2), encoding="utf-8")

    # Layers Manifest JSON (with full Provenance Inspector cards)
    layers_manifest = {
        "ops_bbox_lonlat": list(bbox),
        "grid_shape": [600, 600],
        "grid_resolution_m": round(0.5 * (dx_600 + dy_600), 2),
        "constants_hash": constants_hash,
        "layers": [
            {
                "id": "hirise_base",
                "title": "HiRISE 0.25 m Optical Basemap",
                "data_kind": "optical",
                "badge": "OBSERVED",
                "default_visible": True,
                "default_opacity": 1.0,
                "native_resolution": "0.25 m/px (exported at ~4.94 m/px for ops box)",
                "image_url": "/layers/hirise_base.jpg",
                "pixelated": False,
                "source_product": "NASA/JPL Mars Trek curiosity_hirise_mosaic (MRO HiRISE)",
                "source_url": "https://trek.nasa.gov/mars/",
                "acquisition_date": "2006-2024 (MRO HiRISE)",
                "license": "NASA/JPL-Caltech/Univ. of Arizona Public Domain",
                "credit": "NASA/JPL-Caltech/University of Arizona",
                "limitations": "Static orbital mosaic; does not resolve loose sand depth or transient ripples.",
            },
            {
                "id": "hillshade",
                "title": "1 m DEM Hillshade Relief",
                "data_kind": "topographic",
                "badge": "DERIVED",
                "default_visible": True,
                "default_opacity": 0.35,
                "native_resolution": "1 m/px Gale_DEM_SMG_1m (~4.94 m/px display)",
                "image_url": "/layers/hillshade.png",
                "pixelated": False,
                "source_product": "Horn hillshade (315 deg az, 45 deg alt) from Mars Trek Gale_DEM_SMG_1m",
                "source_url": "https://stac.astrogeology.usgs.gov/docs/data/mars/hirise_dtms/",
                "acquisition_date": "HiRISE stereo pairs (PDS MRO-M-HIRISE-5-DTM-V1.0)",
                "license": "NASA/JPL-Caltech Public Domain",
                "credit": "NASA/JPL-Caltech/University of Arizona",
                "limitations": "Stereo DTM precision ~0.25-1 m vertical; subtle stereo seam steps possible.",
            },
            {
                "id": "slope_hazard",
                "title": "Slope Hazard (>15 deg Hard Limit)",
                "data_kind": "topographic",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.72,
                "native_resolution": "~9.88 m planning cell (max of 2x2 sub-grid Horn slope)",
                "image_url": "/layers/slope_hazard.png",
                "pixelated": True,
                "source_product": "Dual-aggregated Horn slope (slope_max_deg enforces 15 deg block; slope_mean_deg feeds Pandolf)",
                "source_url": "https://ui.adsabs.harvard.edu/abs/2024EPSC...17..196I/abstract",
                "acquisition_date": "Derived from Gale_DEM_SMG_1m",
                "license": "Team Derived (Apache-2.0)",
                "credit": "RedSight Engine from NASA/JPL Gale_DEM_SMG_1m",
                "limitations": "15 deg is a configurable team Scenario limit (no official NASA suited Mars slope standard exists); sub-meter boulders are unresolved.",
            },
            {
                "id": "themis_ti_blocky",
                "title": "THEMIS Thermal Inertia Sand Proxy",
                "data_kind": "thermal",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.60,
                "native_resolution": "100 m/px native (60x60 blocks; nearest-neighbor display)",
                "image_url": "/layers/themis_ti_blocky.png",
                "pixelated": True,
                "source_product": "USGS ARD CC0 THEMIS Controlled NIR Mosaic (mc23_aeolis_nir) -> Pandolf eta [1.05..2.05]",
                "source_url": "https://astrogeo-ard.s3.us-west-2.amazonaws.com/mars/mo/themis/controlled_mosaics/mc23_aeolis_nir/provenance.txt",
                "acquisition_date": "Mars Odyssey THEMIS mosaic",
                "license": "CC0-1.0 (USGS Astrogeology ARD)",
                "credit": "NASA/JPL-Caltech/Arizona State University; USGS Astrogeology",
                "limitations": "100 m/px coarse indicator (~20% TI uncertainty, Fergason et al. 2006); TI->eta is a labeled team transfer function, not boot-scale ground truth.",
            },
            {
                "id": "crism_hydrated",
                "title": "CRISM Hydrated Minerals (Sulfates)",
                "data_kind": "spectral",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.65,
                "native_resolution": "36 m/px targeted MTRDR browse (HRL0000BABA brhydj)",
                "image_url": "/layers/crism_hydrated.png",
                "pixelated": False,
                "source_product": "MRO CRISM MTRDR HRL0000BABA_07_BRHYDJ_MTR3 (PDS Geosciences)",
                "source_url": "https://pds-geosciences.wustl.edu/missions/mro/crism.htm",
                "acquisition_date": "2008-07-20 (MRO orbit)",
                "license": "NASA/JPL/JHU-APL PDS Public Domain",
                "credit": "NASA/JPL-Caltech/JHU-APL/PDS",
                "limitations": "Maps sulfate-bearing host unit at 18-36 m/px; cm-scale boxwork veins are below CRISM pixel resolution and identified by Curiosity surface imaging.",
            },
            {
                "id": "crism_phyllosilicate",
                "title": "CRISM Phyllosilicates (Clays)",
                "data_kind": "spectral",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.65,
                "native_resolution": "36 m/px targeted MTRDR browse (HRL0000BABA brphyj)",
                "image_url": "/layers/crism_phyllosilicate.png",
                "pixelated": False,
                "source_product": "MRO CRISM MTRDR HRL0000BABA_07_BRPHYJ_MTR3 (PDS Geosciences)",
                "source_url": "https://pds-geosciences.wustl.edu/missions/mro/crism.htm",
                "acquisition_date": "2008-07-20 (MRO orbit)",
                "license": "NASA/JPL/JHU-APL PDS Public Domain",
                "credit": "NASA/JPL-Caltech/JHU-APL/PDS",
                "limitations": "Derived spectral summary parameter browse; indicates Fe/Mg-smectite clay affinity in lower Mount Sharp.",
            },
            {
                "id": "sim3292_geology",
                "title": "USGS SIM 3292 Geologic Units",
                "data_kind": "geologic",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.45,
                "native_resolution": "1:20M Global Geologic Map (regional context only)",
                "image_url": "/layers/sim3292_geology.png",
                "pixelated": False,
                "source_product": "USGS SIM 3292 Geologic Map of Mars (Tanaka et al. 2014) — Unit Htu",
                "source_url": "https://pubs.usgs.gov/sim/3292/",
                "acquisition_date": "2014 (Published interpretation)",
                "license": "USGS Public Domain",
                "credit": "USGS/NASA Planetary Geologic Mapping Program",
                "limitations": "1:20M global map (mound maps as unit Htu); regional stratigraphic context only, not walk-scale composition.",
            },
            {
                "id": "viewshed_los",
                "title": "Habitat Comms Line-of-Sight (LOS)",
                "data_kind": "comms",
                "badge": "DERIVED",
                "default_visible": False,
                "default_opacity": 0.60,
                "native_resolution": "~9.88 m DEM raycast (3.0 m mast -> 1.6 m suit)",
                "image_url": "/layers/viewshed_los.png",
                "pixelated": True,
                "source_product": "Curved-Mars geometric viewshed on Gale_DEM_SMG_1m (incl. d^2/2R drop)",
                "source_url": "https://gdal.org/en/stable/programs/gdal_viewshed.html",
                "acquisition_date": "Derived at build time",
                "license": "Team Derived (Apache-2.0)",
                "credit": "RedSight Engine",
                "limitations": "Geometric terrain LOS only; does not model UHF diffraction, multipath, or orbiter relay passes.",
            },
            {
                "id": "reachability_field",
                "title": "Backward-Dijkstra Returnability Envelope",
                "data_kind": "routing",
                "badge": "SCENARIO",
                "default_visible": False,
                "default_opacity": 0.50,
                "native_resolution": "~9.88 m planning grid (nominal 420 L O2, 25% reserve)",
                "image_url": "/layers/reachability_field.png",
                "pixelated": True,
                "source_product": "Scipy backward-Dijkstra return-cost field (Back_o2) from scenario habitat",
                "source_url": "https://ojs.aaai.org/index.php/AAAI/article/view/7803",
                "acquisition_date": "Modeled scenario field",
                "license": "Team Scenario (Apache-2.0)",
                "credit": "RedSight Engine (Sachenbacher & Artmeier backward-feasibility pattern)",
                "limitations": "Scenario estimate assuming Pandolf 1-g metabolism transferred to Mars and 25% team reserve policy.",
            },
        ],
    }
    (DATA_OUT / "layers_manifest.json").write_text(json.dumps(layers_manifest, indent=2), encoding="utf-8")

    # Environment Context JSON (RAD point, REMS climatology, Solar curve, Approx Curiosity photos)
    cached_photos = json.loads((RAW_DIR / "cached_photos_meta.json").read_text(encoding="utf-8"))
    approx_spots = [
        (137.416, -4.725, "Boxwork Ridges Corridor (approx)"),
        (137.434, -4.712, "Gediz Vallis Ridge Flank (approx)"),
        (137.419, -4.695, "Marker Band Approach (approx)"),
        (137.408, -4.678, "Upper Sulfate Slope (approx)"),
        (137.396, -4.668, "Clay-Sulfate Transition (approx)"),
        (137.412, -4.664, "Glen Torridon Floor (approx)"),
    ]
    photo_pins = []
    for i, ph in enumerate(cached_photos):
        plon, plat, plabel = approx_spots[i % len(approx_spots)]
        photo_pins.append(
            {
                **ph,
                "lon": plon,
                "lat": plat,
                "region_label": plabel,
                "badge": "OBSERVED",
                "location_accuracy": "Approximate (pinned by sol/region; raw images lack exact coordinates)",
            }
        )

    env_context = {
        "radiation": {
            "badge": "OBSERVED + SCENARIO",
            "gcr_baseline_msv_day": 0.64,
            "gcr_uncertainty_msv_day": 0.12,
            "source_citation": "Curiosity RAD (Hassler et al. 2014, Science 343:1244797) — ONLY surface dosimeter on Mars.",
            "spatial_map_status": "UNAVAILABLE",
            "spatial_note": "No fine-scale spatial radiation map exists for Gale or Mars. Terrain shielding below uses DEM sky-view factor as a labeled SCENARIO modulation (Guo et al. 2026).",
            "svf_summary": {
                "min": round(float(svf.min()), 3),
                "mean": round(float(svf.mean()), 3),
                "max": round(float(svf.max()), 3),
            },
            "sep_scenarios": [
                {
                    "id": "quiet_gcr",
                    "label": "Quiet GCR Solar Minimum/Nominal",
                    "extra_dose_msv": 0.0,
                    "multiplier": 1.0,
                    "source": "Hassler et al. (2014) RAD baseline ~0.64 mSv/day (~0.027 mSv/hr).",
                },
                {
                    "id": "sep_2017_09",
                    "label": "Sept 2017 SEP Event Scenario (RAD-observed ~369 uGy)",
                    "extra_dose_msv": 0.85,
                    "multiplier": 4.2,
                    "source": "Zeitlin et al. (2018, GRL 10.1029/2018GL077760) surface SEP event seed; no operational Mars SEP forecast exists.",
                },
            ],
        },
        "weather_rems": {
            "badge": "OBSERVED (ROVER-LOCAL) + SCENARIO",
            "pressure_range_pa": [700, 920],
            "air_temp_c_range": [-75, -5],
            "ground_temp_c_range": [-85, 15],
            "wind_typical_mps": [2, 10],
            "source_citation": "Curiosity REMS (PDS msl_rems_bundle; Gomez-Elvira et al. 2014). Straddles water triple point; unsuited human survival impossible.",
            "mcd_note": "Mars Climate Database v6.2 operates at 5.625 x 3.75 deg (~330x220 km cells) — climatology context only, not local weather.",
            "solar_curve": build_solar_curve(),
        },
        "curiosity_photos": photo_pins,
    }
    (DATA_OUT / "environment_context.json").write_text(json.dumps(env_context, indent=2), encoding="utf-8")

    # Decimated 150x150 terrain mesh for 60fps Three.js 3D & 1.6m HUD
    elev_150 = elev.reshape(150, 4, 150, 4).mean(axis=(1, 3))
    mesh_payload = {
        "rows": 150,
        "cols": 150,
        "bbox": list(bbox),
        "dx_m": round(dx_600 * 4.0, 2),
        "dy_m": round(dy_600 * 4.0, 2),
        "elev_min_m": round(float(elev_150.min()), 2),
        "elev_max_m": round(float(elev_150.max()), 2),
        "elev": np.round(elev_150, 2).tolist(),
    }
    (DATA_OUT / "terrain_mesh.json").write_text(json.dumps(mesh_payload, separators=(",", ":")), encoding="utf-8")

    print(f"Build complete in {time.perf_counter() - t_start:.2f} s. Outputs in {APP_PUBLIC}")


if __name__ == "__main__":
    main()
