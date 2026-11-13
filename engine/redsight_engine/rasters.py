"""DEM conditioning, dual Horn slope aggregation (F4), THEMIS TI->eta, curved LOS viewshed (F8), and sky-view."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .crs import MARS_RADIUS_M, cell_spacing_m


def load_dem_tiff(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load float32 TIFF and return (filled_dem, nodata_mask)."""
    with Image.open(path) as im:
        arr = np.array(im, dtype=np.float32)
    nodata = (~np.isfinite(arr)) | (arr < -10000.0) | (arr > 10000.0)
    if nodata.any():
        _, indices = distance_transform_edt(nodata, return_distances=True, return_indices=True)
        filled = arr[tuple(indices)]
    else:
        filled = arr.copy()
    return filled, nodata


def horn_slope_and_aspect(
    dem: np.ndarray,
    dx_m: float,
    dy_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute Horn 3x3 finite-difference slope (deg), dz/dx, and dz/dy (north-positive)."""
    padded = np.pad(dem.astype(np.float64), 1, mode="edge")
    z00 = padded[:-2, :-2]
    z01 = padded[:-2, 1:-1]
    z02 = padded[:-2, 2:]
    z10 = padded[1:-1, :-2]
    z12 = padded[1:-1, 2:]
    z20 = padded[2:, :-2]
    z21 = padded[2:, 1:-1]
    z22 = padded[2:, 2:]

    dz_dx = ((z02 + 2.0 * z12 + z22) - (z00 + 2.0 * z10 + z20)) / (8.0 * dx_m)
    dz_dy = ((z00 + 2.0 * z01 + z02) - (z20 + 2.0 * z21 + z22)) / (8.0 * dy_m)
    slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype(np.float32)
    return slope_deg, dz_dx.astype(np.float32), dz_dy.astype(np.float32)


def compute_hillshade(
    dem: np.ndarray,
    dx_m: float,
    dy_m: float,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
    z_factor: float = 1.5,
) -> np.ndarray:
    """Compute uint8 hillshade matching planetary convention (315 deg az, 45 deg alt)."""
    _, dz_dx, dz_dy = horn_slope_and_aspect(dem * z_factor, dx_m, dy_m)
    slope_rad = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect_rad = np.arctan2(-dz_dx, dz_dy)
    zenith_rad = math.radians(90.0 - altitude_deg)
    az_rad = math.radians(azimuth_deg)
    shaded = (
        math.cos(zenith_rad) * np.cos(slope_rad)
        + math.sin(zenith_rad) * np.sin(slope_rad) * np.cos(az_rad - aspect_rad)
    )
    return np.clip(shaded * 255.0, 0, 255).astype(np.uint8)


def aggregate_planning_grid(
    dem_1200: np.ndarray,
    nodata_1200: np.ndarray,
    bbox: tuple[float, float, float, float],
    target_shape: tuple[int, int] = (600, 600),
) -> dict[str, np.ndarray]:
    """Compute 1m/sub-grid Horn slope then aggregate into dual slope_max_deg and slope_mean_deg (Review F4)."""
    h_in, w_in = dem_1200.shape
    h_out, w_out = target_shape
    fh, fw = h_in // h_out, w_in // w_out
    assert h_out * fh == h_in and w_out * fw == w_in, "Target shape must divide input DEM evenly"

    dx_in, dy_in = cell_spacing_m(bbox, (h_in, w_in))
    slope_in, _, _ = horn_slope_and_aspect(dem_1200, dx_in, dy_in)

    elev_out = dem_1200.reshape(h_out, fh, w_out, fw).mean(axis=(1, 3)).astype(np.float32)
    slope_max = slope_in.reshape(h_out, fh, w_out, fw).max(axis=(1, 3)).astype(np.float32)
    slope_mean = slope_in.reshape(h_out, fh, w_out, fw).mean(axis=(1, 3)).astype(np.float32)
    data_gap = nodata_1200.reshape(h_out, fh, w_out, fw).any(axis=(1, 3)).astype(np.uint8)

    return {
        "elev": elev_out,
        "slope_max_deg": slope_max,
        "slope_mean_deg": slope_mean,
        "data_gap": data_gap,
    }


def themis_to_surface_proxy(
    themis_nir_60: np.ndarray,
    target_shape: tuple[int, int] = (600, 600),
) -> tuple[np.ndarray, np.ndarray]:
    """Map 100 m/px THEMIS Nighttime IR DN to proxy thermal inertia [140..380] and Pandolf eta [1.05..2.05].

    Strictly nearest-neighbor upsampled so the 100 m native blocks stay visually honest (Review V5).
    """
    dn = themis_nir_60.astype(np.float32)
    p5, p95 = float(np.percentile(dn, 5)), float(np.percentile(dn, 95))
    norm = np.clip((dn - p5) / max(1.0, p95 - p5), 0.0, 1.0)
    ti_60 = 140.0 + norm * 240.0  # J m^-2 K^-1 s^-1/2 proxy scale
    eta_60 = 2.05 - norm * 1.00   # Low TI -> ~2.05 loose sand; High TI -> ~1.05 bedrock

    rep_r = target_shape[0] // themis_nir_60.shape[0]
    rep_c = target_shape[1] // themis_nir_60.shape[1]
    ti_grid = np.repeat(np.repeat(ti_60, rep_r, axis=0), rep_c, axis=1).astype(np.float32)
    eta_grid = np.repeat(np.repeat(eta_60, rep_r, axis=0), rep_c, axis=1).astype(np.float32)
    return ti_grid, eta_grid


def compute_viewshed_los(
    elev: np.ndarray,
    hab_rc: tuple[int, int],
    dx_m: float,
    dy_m: float,
    mast_height_m: float = 3.0,
    rx_height_m: float = 1.6,
    n_samples: int = 120,
) -> np.ndarray:
    """Vectorized curved-Mars line-of-sight viewshed from habitat antenna (Review F8)."""
    rows, cols = elev.shape
    r0, c0 = hab_rc
    z0 = float(elev[r0, c0]) + mast_height_m

    rr, cc = np.meshgrid(np.arange(rows, dtype=np.float32), np.arange(cols, dtype=np.float32), indexing="ij")
    dr = rr - float(r0)
    dc = cc - float(c0)
    dist_m = np.hypot(dr * dy_m, dc * dx_m)
    z_target = elev + rx_height_m - (dist_m ** 2) / (2.0 * MARS_RADIUS_M)

    blocked = np.zeros((rows, cols), dtype=bool)
    for t in np.linspace(0.02, 0.98, n_samples, dtype=np.float32):
        ri = np.rint(r0 + t * dr).astype(np.int32)
        ci = np.rint(c0 + t * dc).astype(np.int32)
        d_ray = t * dist_m
        z_ray = z0 + t * (z_target - z0)
        z_terrain = elev[ri, ci] - (d_ray ** 2) / (2.0 * MARS_RADIUS_M)
        blocked |= (dist_m > 25.0) & (z_terrain > z_ray + 0.15)

    los = (~blocked).astype(np.uint8)
    los[r0, c0] = 1
    return los


def compute_sky_view_factor(elev: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    """Estimate normalized sky-view factor [0.65..1.0] for SCENARIO terrain shielding context."""
    rows, cols = elev.shape
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    radii_cells = [5, 15, 40]
    padded = np.pad(elev, 40, mode="edge")
    max_horizon_tan = np.zeros((rows, cols), dtype=np.float32)

    sin_sum = np.zeros((rows, cols), dtype=np.float32)
    for dr, dc in dirs:
        dir_max_tan = np.zeros((rows, cols), dtype=np.float32)
        for rad in radii_cells:
            sr = 40 + dr * rad
            sc = 40 + dc * rad
            d_m = math.hypot(dr * rad * dy_m, dc * rad * dx_m)
            dz = padded[sr : sr + rows, sc : sc + cols] - elev
            dir_max_tan = np.maximum(dir_max_tan, np.maximum(0.0, dz / d_m))
        max_horizon_tan = np.maximum(max_horizon_tan, dir_max_tan)
        sin_h = dir_max_tan / np.sqrt(1.0 + dir_max_tan ** 2)
        sin_sum += (1.0 - sin_h)

    svf = sin_sum / float(len(dirs))
    return np.clip(svf, 0.65, 1.0).astype(np.float32)
