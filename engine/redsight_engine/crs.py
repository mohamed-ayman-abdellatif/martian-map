"""Mars 2000 sphere planetocentric coordinate helpers."""

from __future__ import annotations

import math

MARS_RADIUS_M = 3396190.0
DEG_TO_M_LAT = 59274.7
DEFAULT_BBOX = (137.36, -4.75, 137.46, -4.65)  # (lon_min, lat_min, lon_max, lat_max)


def cos_ref_lat(bbox: tuple[float, float, float, float] = DEFAULT_BBOX) -> float:
    mid_lat = 0.5 * (bbox[1] + bbox[3])
    return math.cos(math.radians(mid_lat))


def cell_spacing_m(
    bbox: tuple[float, float, float, float],
    shape: tuple[int, int],
) -> tuple[float, float]:
    """Return (dx_m, dy_m) ground cell size on the Mars 2000 sphere."""
    rows, cols = shape
    lon_span = bbox[2] - bbox[0]
    lat_span = bbox[3] - bbox[1]
    c_lat = cos_ref_lat(bbox)
    dx_m = (lon_span * DEG_TO_M_LAT * c_lat) / cols
    dy_m = (lat_span * DEG_TO_M_LAT) / rows
    return dx_m, dy_m


def lonlat_to_rowcol(
    lon: float,
    lat: float,
    bbox: tuple[float, float, float, float],
    shape: tuple[int, int],
) -> tuple[int, int]:
    """Convert planetocentric (lon, lat) to pixel (row, col), north-up."""
    rows, cols = shape
    lon_min, lat_min, lon_max, lat_max = bbox
    col = int(((lon - lon_min) / (lon_max - lon_min)) * cols)
    row = int(((lat_max - lat) / (lat_max - lat_min)) * rows)
    row = max(0, min(rows - 1, row))
    col = max(0, min(cols - 1, col))
    return row, col


def rowcol_to_lonlat(
    row: int,
    col: int,
    bbox: tuple[float, float, float, float],
    shape: tuple[int, int],
) -> tuple[float, float]:
    """Convert pixel center (row, col) to planetocentric (lon, lat)."""
    rows, cols = shape
    lon_min, lat_min, lon_max, lat_max = bbox
    lon = lon_min + ((col + 0.5) / cols) * (lon_max - lon_min)
    lat = lat_max - ((row + 0.5) / rows) * (lat_max - lat_min)
    return round(lon, 7), round(lat, 7)
