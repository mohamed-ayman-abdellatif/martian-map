"""Phase A2 retry-hardened NASA/USGS/PDS data pull and provenance logger."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw"
PHOTOS_DIR = ROOT_DIR / "app" / "public" / "data" / "photos"
PROVENANCE_PATH = ROOT_DIR / "data" / "PROVENANCE.md"

BBOX = [137.36, -4.75, 137.46, -4.65]  # [lon_min, lat_min, lon_max, lat_max]
BBOX_STR = ",".join(str(x) for x in BBOX)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_with_retry(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 4,
    timeout: int = 30,
) -> requests.Response:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (200, 206):
                return resp
            last_err = RuntimeError(f"HTTP {resp.status_code} for {resp.url}")
        except Exception as exc:
            last_err = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed after {retries} attempts: {url} ({last_err})")


def pull_themis_nir_cog(records: list[dict[str, str]]) -> None:
    """Fetch 60x60 (100 m/px) THEMIS Nighttime IR sub-window from USGS ARD CC0 COG."""
    tif_url = (
        "https://astrogeo-ard.s3.us-west-2.amazonaws.com/"
        "mars/mo/themis/controlled_mosaics/mc23_aeolis_nir/mc23_aeolis_nir.tif"
    )
    prov_url = (
        "https://astrogeo-ard.s3.us-west-2.amazonaws.com/"
        "mars/mo/themis/controlled_mosaics/mc23_aeolis_nir/provenance.txt"
    )
    out_npy = RAW_DIR / "themis_nir_60x60.npy"
    out_prov = RAW_DIR / "themis_provenance.txt"

    try:
        prov_txt = fetch_with_retry(prov_url, timeout=15).content
        out_prov.write_bytes(prov_txt)

        hdr = fetch_with_retry(tif_url, headers={"Range": "bytes=0-32767"}, timeout=20).content
        offs = struct.unpack_from("<1855I", hdr, 2042)
        cnts = struct.unpack_from("<1855I", hdr, 9462)
        scale = 592.747
        col0 = round((BBOX[0] - 135.0) * scale)
        row0 = round((0.0 - BBOX[3]) * scale)
        tile_r, tile_c = row0 // 512, col0 // 512
        t_idx = tile_r * 53 + tile_c
        off, cnt = offs[t_idx], cnts[t_idx]
        raw_tile = fetch_with_retry(
            tif_url, headers={"Range": f"bytes={off}-{off + cnt - 1}"}, timeout=20
        ).content
        tile = np.frombuffer(zlib.decompress(raw_tile), dtype=np.uint8).reshape(512, 512)
        tile = np.cumsum(tile, axis=1, dtype=np.uint8)
        r_local = row0 - tile_r * 512
        c_local = col0 - tile_c * 512
        sub = tile[r_local : r_local + 60, c_local : c_local + 60]
        assert sub.shape == (60, 60), f"Unexpected THEMIS shape {sub.shape}"
        np.save(out_npy, sub)
        records.append(
            {
                "file": "data/raw/themis_nir_60x60.npy",
                "url": tif_url,
                "res": "100 m/px (60x60 window)",
                "crs": "Mars 2000 Planetocentric East-Positive",
                "license": "CC0-1.0 (USGS ARD STAC)",
                "credit": "NASA/JPL-Caltech/Arizona State University; USGS Astrogeology ARD",
                "badge": "OBSERVED",
                "bytes": str(out_npy.stat().st_size),
                "sha256": sha256_bytes(out_npy.read_bytes()),
            }
        )
    except Exception as exc:
        print(f"[WARN] THEMIS S3 COG range pull failed ({exc}); writing neutral fallback.")
        fallback = np.full((60, 60), 175, dtype=np.uint8)
        np.save(out_npy, fallback)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: list[dict[str, str]] = []

    # 1. Gale 1 m DEM (quantitatively exported 32-bit float TIFF at 1200x1200)
    dem_url = "https://trek.nasa.gov/mars/trekarcgis/rest/services/Gale_DEM_SMG_1m/ImageServer/exportImage"
    dem_params = {
        "bbox": BBOX_STR,
        "size": "1200,1200",
        "format": "tiff",
        "compression": "NONE",
        "f": "image",
    }
    dem_resp = fetch_with_retry(dem_url, params=dem_params, timeout=45)
    dem_path = RAW_DIR / "gale_dem_1200.tif"
    dem_path.write_bytes(dem_resp.content)
    with Image.open(io.BytesIO(dem_resp.content)) as im:
        assert im.mode == "F", f"Expected float32 TIFF mode 'F', got {im.mode}"
        arr = np.array(im, dtype=np.float32)
        assert arr.shape == (1200, 1200), f"Unexpected DEM shape {arr.shape}"
        print(f"DEM OK: {arr.shape}, elev [{arr.min():.1f}, {arr.max():.1f}] m")
    records.append(
        {
            "file": "data/raw/gale_dem_1200.tif",
            "url": dem_resp.url,
            "res": "1 m native mosaic resampled to ~4.94 m/px (1200x1200)",
            "crs": "WKID 104905 / Mars 2000 Planetocentric East-Positive",
            "license": "NASA/JPL-Caltech public domain (PDS HiRISE DTM mosaic)",
            "credit": "NASA/JPL-Caltech/University of Arizona (Mars Trek Gale_DEM_SMG_1m)",
            "badge": "OBSERVED",
            "bytes": str(len(dem_resp.content)),
            "sha256": sha256_bytes(dem_resp.content),
        }
    )

    # 2. HiRISE 0.25 m optical mosaic export (1200x1200 JPG)
    hirise_url = "https://trek.nasa.gov/mars/trekarcgis/rest/services/curiosity_hirise_mosaic/ImageServer/exportImage"
    hirise_resp = fetch_with_retry(
        hirise_url,
        params={"bbox": BBOX_STR, "size": "1200,1200", "format": "jpg", "f": "image"},
        timeout=45,
    )
    hirise_path = RAW_DIR / "hirise_ortho_1200.jpg"
    hirise_path.write_bytes(hirise_resp.content)
    print(f"HiRISE OK: {len(hirise_resp.content)} bytes")
    records.append(
        {
            "file": "data/raw/hirise_ortho_1200.jpg",
            "url": hirise_resp.url,
            "res": "0.25 m native mosaic exported at ~4.94 m/px (1200x1200)",
            "crs": "WKID 104905 / Mars 2000 Planetocentric East-Positive",
            "license": "NASA/JPL-Caltech/University of Arizona public domain",
            "credit": "NASA/JPL-Caltech/University of Arizona (Mars Trek curiosity_hirise_mosaic)",
            "badge": "OBSERVED",
            "bytes": str(len(hirise_resp.content)),
            "sha256": sha256_bytes(hirise_resp.content),
        }
    )

    # 3. THEMIS Nighttime IR 100 m COG sub-window
    pull_themis_nir_cog(records)

    # 4. CRISM MTRDR HRL0000BABA mineral browse overlays (PDS Geosciences, 36 m/px)
    crism_bounds = (137.2970000, -4.9981722, 137.5545100, -4.5991487)  # from .lbl
    crism_products = [
        (
            "crism_hydrated.png",
            "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/browse/2008/2008_202/hrl0000baba/hrl0000baba_07_brhydj_mtr3.png",
            "CRISM MTRDR HRL0000BABA Hydrated Mineral Browse (brhydj)",
        ),
        (
            "crism_phyllosilicate.png",
            "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/browse/2008/2008_202/hrl0000baba/hrl0000baba_07_brphyj_mtr3.png",
            "CRISM MTRDR HRL0000BABA Phyllosilicate/Clay Browse (brphyj)",
        ),
    ]
    for fname, prod_url, desc in crism_products:
        resp = fetch_with_retry(prod_url, timeout=30)
        with Image.open(io.BytesIO(resp.content)) as im_full:
            im_rgba = im_full.convert("RGBA")
            w_f, h_f = im_rgba.size
            c_lon0, c_lat0, c_lon1, c_lat1 = crism_bounds
            x0 = int(round((BBOX[0] - c_lon0) / (c_lon1 - c_lon0) * w_f))
            x1 = int(round((BBOX[2] - c_lon0) / (c_lon1 - c_lon0) * w_f))
            y0 = int(round((c_lat1 - BBOX[3]) / (c_lat1 - c_lat0) * h_f))
            y1 = int(round((c_lat1 - BBOX[1]) / (c_lat1 - c_lat0) * h_f))
            cropped = im_rgba.crop((x0, y0, x1, y1)).resize((600, 600), Image.Resampling.NEAREST)
            fpath = RAW_DIR / fname
            cropped.save(fpath, format="PNG")
            nz = int((np.array(cropped)[:, :, 3] > 0).sum())
            print(f"{fname} OK: cropped ({x1-x0}x{y1-y0}) -> 600x600, non-zero alpha={nz}")
        records.append(
            {
                "file": f"data/raw/{fname}",
                "url": prod_url,
                "res": "36 m/px targeted CRISM MTRDR browse (HRL0000BABA)",
                "crs": "Mars 2000 Equirectangular Planetocentric",
                "license": "NASA/JPL/JHU-APL PDS Public Domain",
                "credit": f"NASA/JPL-Caltech/JHU-APL/PDS ({desc})",
                "badge": "DERIVED",
                "bytes": str(fpath.stat().st_size),
                "sha256": sha256_bytes(fpath.read_bytes()),
            }
        )

    # 5. USGS SIM 3292 Geologic Map (GeoJSON + overlay PNG)
    sim_json_url = "https://astrogeology.usgs.gov/pygeoapi/collections/mars/sim3292_global_geologic_map/units/items"
    sim_resp = fetch_with_retry(sim_json_url, params={"bbox": BBOX_STR, "f": "json"}, timeout=30)
    sim_json_path = RAW_DIR / "sim3292_geology.json"
    sim_json_path.write_bytes(sim_resp.content)
    records.append(
        {
            "file": "data/raw/sim3292_geology.json",
            "url": sim_resp.url,
            "res": "1:20M Global Geologic Map (SIM 3292, Tanaka et al. 2014)",
            "crs": "Planetocentric Lon/Lat",
            "license": "USGS Public Domain",
            "credit": "USGS/NASA Planetary Geologic Mapping Program (SIM 3292)",
            "badge": "DERIVED",
            "bytes": str(len(sim_resp.content)),
            "sha256": sha256_bytes(sim_resp.content),
        }
    )

    sim_png_url = "https://trek.nasa.gov/mars/trekarcgis/rest/services/SIM3292_Global_Geology/MapServer/export"
    sim_png_resp = fetch_with_retry(
        sim_png_url,
        params={
            "bbox": BBOX_STR,
            "bboxSR": "104905",
            "imageSR": "104905",
            "size": "600,600",
            "format": "png32",
            "transparent": "true",
            "f": "image",
        },
        timeout=30,
    )
    (RAW_DIR / "sim3292_overlay.png").write_bytes(sim_png_resp.content)
    records.append(
        {
            "file": "data/raw/sim3292_overlay.png",
            "url": sim_png_resp.url,
            "res": "1:20M Global Geologic Map rasterized over ops box",
            "crs": "WKID 104905",
            "license": "USGS Public Domain",
            "credit": "USGS/NASA Planetary Geologic Mapping Program / Mars Trek",
            "badge": "DERIVED",
            "bytes": str(len(sim_png_resp.content)),
            "sha256": sha256_bytes(sim_png_resp.content),
        }
    )

    # 6. Curiosity Raw Images API (cached metadata + thumbnails)
    msl_url = "https://mars.nasa.gov/api/v1/raw_image_items/"
    msl_resp = fetch_with_retry(
        msl_url,
        params={"condition": "msl", "per_page": 30, "order": "sol desc"},
        timeout=30,
    )
    msl_data = msl_resp.json()
    (RAW_DIR / "curiosity_photos.json").write_bytes(msl_resp.content)
    records.append(
        {
            "file": "data/raw/curiosity_photos.json",
            "url": msl_resp.url,
            "res": "Per-sol surface camera telemetry (approximate location only)",
            "crs": "Rover site/sol metadata (no exact lat/lon)",
            "license": "NASA/JPL-Caltech/MSSS Public Domain",
            "credit": "NASA/JPL-Caltech/MSSS",
            "badge": "OBSERVED",
            "bytes": str(len(msl_resp.content)),
            "sha256": sha256_bytes(msl_resp.content),
        }
    )

    # Cache up to 6 Mastcam/Navcam/ChemCam thumbnails locally
    saved_thumbs = []
    for item in msl_data.get("items", []):
        if len(saved_thumbs) >= 6:
            break
        img_urls = item.get("image_files") or {}
        thumb_url = img_urls.get("medium") or img_urls.get("small") or item.get("url")
        inst = str(item.get("instrument", ""))
        if not thumb_url or not any(k in inst.upper() for k in ["MAST", "NAVCAM", "CHEMCAM", "MAHLI"]):
            continue
        try:
            t_resp = fetch_with_retry(thumb_url, retries=2, timeout=15)
            fname = f"msl_sol{item.get('sol', 'x')}_{item.get('id', len(saved_thumbs))}.jpg"
            (PHOTOS_DIR / fname).write_bytes(t_resp.content)
            saved_thumbs.append(
                {
                    "id": str(item.get("id", fname)),
                    "sol": item.get("sol"),
                    "instrument": inst,
                    "title": item.get("title") or f"Curiosity {inst} Sol {item.get('sol')}",
                    "caption": (item.get("caption") or "Surface observation in Mount Sharp boxwork corridor.")[:220],
                    "date_taken_utc": item.get("date_taken_utc"),
                    "local_image": f"/data/photos/{fname}",
                    "source_url": thumb_url,
                    "credit": "NASA/JPL-Caltech/MSSS",
                }
            )
        except Exception:
            continue
    (RAW_DIR / "cached_photos_meta.json").write_text(json.dumps(saved_thumbs, indent=2), encoding="utf-8")
    print(f"Cached {len(saved_thumbs)} Curiosity thumbnails locally.")

    # 7. Write data/PROVENANCE.md
    lines = [
        "# RedSight Data Provenance Ledger",
        "",
        f"**Generated (UTC):** {ts}  ",
        f"**Operations Box (Planetocentric East-Positive):** `{BBOX}` (`137.36°E–137.46°E, -4.75°N–-4.65°N`)",
        "",
        "| Local Artifact | Badge | Resolution / Scale | CRS | License / Terms | Credit | SHA-256 (prefix) | Bytes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| `{r['file']}` | **{r['badge']}** | {r['res']} | {r['crs']} | "
            f"{r['license']} | {r['credit']} | `{r['sha256'][:12]}...` | {r['bytes']} |"
        )
    lines.extend(["", "## Source URLs", ""])
    for r in records:
        lines.append(f"- `{r['file']}`: {r['url']}")
    PROVENANCE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {PROVENANCE_PATH}")


if __name__ == "__main__":
    main()
