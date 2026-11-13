# RedSight — System & Software Architecture Specification

**Status:** Phase A1 Architecture Contract (2026-11-13). Companion to [`technical-approaches.md`](technical-approaches.md), [`24-48-hour-plan.md`](24-48-hour-plan.md), and [`research/independent-architecture-review.md`](research/independent-architecture-review.md).

> **Honesty & Compliance:** RedSight is a **decision-support prototype** using real NASA/USGS/PDS data. All routes, consumables, and turn-back markers are **modeled scenario estimates within stated assumptions** — never certified life-support or flight-safety numbers. Every layer, card, and constant carries an explicit **Observed / Derived / Scenario / Unavailable** badge.

---

## 1. Three-Tier Static-First Architecture

To eliminate live API failure risks (Mars Trek rate limits, TLS resets, or S3 timeouts) during judging, RedSight separates **build-time acquisition**, **offline deterministic computation**, and **static browser presentation**:

1. **Tier 1 — Build-Time Data Acquisition (`data/raw/` + `data/PROVENANCE.md`):**
   - Pulls and caches real NASA/USGS/PDS data over the Gale Crater / lower Mount Sharp operations box (`137.36°E–137.46°E, -4.75°N–-4.65°N`, ≈ `5.91 km × 5.93 km`).
   - Implements the **Review F3** retry-hardened download playbook and records exact URLs, access timestamps, SHA-256 hashes, resolutions, licenses, and credits in [`../data/PROVENANCE.md`](../data/PROVENANCE.md).
2. **Tier 2 — Offline Python Geospatial & Routing Engine (`engine/`):**
   - Conditions the `1200×1200` float32 DEM (`Gale_DEM_SMG_1m`) and `60×60` THEMIS Nighttime IR proxy (`mc23_aeolis_nir`, 100 m/px) onto a unified `600×600` (`~9.88 m/px`) planning grid.
   - Computes Horn 3×3 slopes with **dual aggregation (Review F4)**: `slope_max_deg` (block max) enforces the hard `15.0°` traversability constraint, while `slope_mean_deg` (block mean) drives Pandolf metabolic grade $G$.
   - Builds an 8-connected directed CSR graph (`360,000` nodes, `~2.87M` directed edges at 10 m demo scale; scales to `1.44M` nodes at 5 m) with corner-cutting prevention.
   - Solves forward shortest-path trees (`Fastest`, `Balanced`, `Safest`) and backward return-cost fields (`Back_time`, `Back_o2`) via `scipy.sparse.csgraph.dijkstra` (**Review F2**).
   - Exports static rasters, GeoJSON overlays, `terrain_mesh.json`, and route JSON bundles into `app/public/`.
3. **Tier 3 — Static Web Application (`app/`):**
   - Vite + TypeScript + MapLibre GL JS (`BSD-3-Clause`) for the 2D layered map planner + Three.js (`MIT`) for the 3D terrain orbit view and 1.6 m eye-height first-person helmet HUD walkthrough.
   - Zero backend required; works completely offline after page load.
   - Client-side `pnrCalculator.ts` rescales `used_o2_l_base` / `back_o2_l_base` and recomputes the Turn-Back / Point-of-No-Return (`PNR`) marker in `< 1 ms` as the user adjusts load, suit overhead $\kappa$, reserve %, or consumables budget.

---

## 2. Coordinate Reference System & Review F1–F8 Integration

- **CRS (Review §2 / AD-1):** Planetocentric east-positive degrees on the IAU Mars 2000 sphere (`+proj=longlat +R=3396190 +no_defs` / `IAU_2015:49900`), $1^\circ\text{ lat} = 59,274.7\text{ m}$, $\cos(-4.70^\circ) = 0.996637$ ($1^\circ\text{ lon} = 59,075.4\text{ m}$). All layers are ingested in planetocentric degrees to avoid the ~3.2–3.3 km planetographic latitude offset at Gale.
- **Dual Slope Aggregation (Review F4):** 1 m / sub-grid Horn slope is computed before resampling, yielding both `slope_max_deg` (hard block $> 15^\circ$) and `slope_mean_deg` (Pandolf metabolic cost).
- **Scipy Dijkstra Core (Review F2):** `scipy.sparse.csgraph.dijkstra` computes full forward and backward cost fields in fractions of a second; custom A\* (`astar_oracle.py`) is retained as the **T7** verification oracle with mode-scaled heuristics (**Review F5**).
- **Piecewise Speed $V(\theta)$ (Review F5):** Single shared definition in degrees across engine and tests:
  - $\theta \ge 0^\circ$: $V = V_{\max} \cdot \max(0.30, \cos(2\theta))$
  - $-12^\circ \le \theta < 0^\circ$: $V = 1.10 \cdot V_{\max}$
  - $\theta < -12^\circ$: $V = V_{\max} \cdot \max(0.30, 1.10 - 0.05(|\theta| - 12^\circ))$
- **THEMIS 100 m Resolution Transparency (Review V5):** THEMIS Nighttime IR (`100 m/px`, `60×60` cells) is upsampled strictly with nearest-neighbor (`np.repeat`) and displayed pixelated (`image-rendering: pixelated`) so 100 m blocks are never disguised as boot-scale precision.
- **Viewshed LOS Curvature (Review F8):** Habitat comms LOS raycast explicitly includes Mars planetary curvature drop $\Delta z_{\text{curv}} = \frac{d^2}{2 R_{\text{Mars}}}$ (~5.3 m at 6 km) plus antenna mast (`+3.0 m`) and astronaut height (`+1.6 m`).

---

## 3. JSON Integration Contracts (`app/public/data/`)

All UI components read directly from engine-generated static JSON artifacts:

1. **`constants.json`**: Stores every planetary, physiological, and scenario constant with `{ value, range, units, badge, source_title, source_url, note }`.
2. **`layers_manifest.json`**: Declares `ops_bbox_lonlat`, `grid_shape`, `grid_resolution_m`, scenario `habitat` coordinates, and full provenance cards for every map layer (`L1`–`L10`).
3. **`targets.json`**: Curated Gale science targets (`site_boxwork_2025`, `site_gediz_sulfate`, `site_marker_band`, `site_clay_butte`) with coordinates, geologic/CRISM evidence, and `OBSERVED`/`DERIVED` badges.
4. **`routes/{goal_id}_{mode}.json`**: Per-route summary metrics (modeled round-trip time, O₂ liters, hazard breakdown across slope/sand/gap/LOS), GeoJSON `LineString` in `[lon, lat, elev_m]`, and `waypoints_profile[]` storing `{ idx, row, col, lon, lat, elev_m, cum_dist_m, seg_slope_mean_deg, seg_slope_max_deg, surf_eta, los, used_time_s, back_time_s, used_o2_l_base, back_o2_l_base, dominant_cost_reason }`.
5. **`environment_context.json`**: Curiosity RAD GCR point baseline (`0.64 ± 0.12 mSv/day`) + Sept 2017 SEP scenario parameters + REMS annual pressure/temperature range + local solar elevation window + approximate Curiosity surface photo pins.
6. **`terrain_mesh.json`**: Decimated `150×150` elevation matrix + bounds for Three.js 3D terrain orbit and 1.6 m first-person HUD rendering.
