# RedSight Data Provenance Ledger

**Generated (UTC):** 2026-11-13T14:24:51Z  
**Operations Box (Planetocentric East-Positive):** `[137.36, -4.75, 137.46, -4.65]` (`137.36°E–137.46°E, -4.75°N–-4.65°N`)

| Local Artifact | Badge | Resolution / Scale | CRS | License / Terms | Credit | SHA-256 (prefix) | Bytes |
|---|---|---|---|---|---|---|---|
| `data/raw/gale_dem_1200.tif` | **OBSERVED** | 1 m native mosaic resampled to ~4.94 m/px (1200x1200) | WKID 104905 / Mars 2000 Planetocentric East-Positive | NASA/JPL-Caltech public domain (PDS HiRISE DTM mosaic) | NASA/JPL-Caltech/University of Arizona (Mars Trek Gale_DEM_SMG_1m) | `40f4bf685670...` | 6555244 |
| `data/raw/hirise_ortho_1200.jpg` | **OBSERVED** | 0.25 m native mosaic exported at ~4.94 m/px (1200x1200) | WKID 104905 / Mars 2000 Planetocentric East-Positive | NASA/JPL-Caltech/University of Arizona public domain | NASA/JPL-Caltech/University of Arizona (Mars Trek curiosity_hirise_mosaic) | `b6be2dd8c253...` | 253750 |
| `data/raw/themis_nir_60x60.npy` | **OBSERVED** | 100 m/px (60x60 window) | Mars 2000 Planetocentric East-Positive | CC0-1.0 (USGS ARD STAC) | NASA/JPL-Caltech/Arizona State University; USGS Astrogeology ARD | `60a5d12a7ff3...` | 3728 |
| `data/raw/crism_hydrated.png` | **DERIVED** | 36 m/px targeted CRISM MTRDR browse (HRL0000BABA) | Mars 2000 Equirectangular Planetocentric | NASA/JPL/JHU-APL PDS Public Domain | NASA/JPL-Caltech/JHU-APL/PDS (CRISM MTRDR HRL0000BABA Hydrated Mineral Browse (brhydj)) | `e8a0927676d1...` | 81423 |
| `data/raw/crism_phyllosilicate.png` | **DERIVED** | 36 m/px targeted CRISM MTRDR browse (HRL0000BABA) | Mars 2000 Equirectangular Planetocentric | NASA/JPL/JHU-APL PDS Public Domain | NASA/JPL-Caltech/JHU-APL/PDS (CRISM MTRDR HRL0000BABA Phyllosilicate/Clay Browse (brphyj)) | `ed5f82515a45...` | 65960 |
| `data/raw/sim3292_geology.json` | **DERIVED** | 1:20M Global Geologic Map (SIM 3292, Tanaka et al. 2014) | Planetocentric Lon/Lat | USGS Public Domain | USGS/NASA Planetary Geologic Mapping Program (SIM 3292) | `43bf78b8d2bc...` | 22072388 |
| `data/raw/sim3292_overlay.png` | **DERIVED** | 1:20M Global Geologic Map rasterized over ops box | WKID 104905 | USGS Public Domain | USGS/NASA Planetary Geologic Mapping Program / Mars Trek | `e224c10c0028...` | 8687 |
| `data/raw/curiosity_photos.json` | **OBSERVED** | Per-sol surface camera telemetry (approximate location only) | Rover site/sol metadata (no exact lat/lon) | NASA/JPL-Caltech/MSSS Public Domain | NASA/JPL-Caltech/MSSS | `b76568395faa...` | 52856 |

## Source URLs

- `data/raw/gale_dem_1200.tif`: https://trek.nasa.gov/mars/trekarcgis/rest/services/Gale_DEM_SMG_1m/ImageServer/exportImage?bbox=137.36%2C-4.75%2C137.46%2C-4.65&size=1200%2C1200&format=tiff&compression=NONE&f=image
- `data/raw/hirise_ortho_1200.jpg`: https://trek.nasa.gov/mars/trekarcgis/rest/services/curiosity_hirise_mosaic/ImageServer/exportImage?bbox=137.36%2C-4.75%2C137.46%2C-4.65&size=1200%2C1200&format=jpg&f=image
- `data/raw/themis_nir_60x60.npy`: https://astrogeo-ard.s3.us-west-2.amazonaws.com/mars/mo/themis/controlled_mosaics/mc23_aeolis_nir/mc23_aeolis_nir.tif
- `data/raw/crism_hydrated.png`: https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/browse/2008/2008_202/hrl0000baba/hrl0000baba_07_brhydj_mtr3.png
- `data/raw/crism_phyllosilicate.png`: https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/browse/2008/2008_202/hrl0000baba/hrl0000baba_07_brphyj_mtr3.png
- `data/raw/sim3292_geology.json`: https://astrogeology.usgs.gov/pygeoapi/collections/mars/sim3292_global_geologic_map/units/items?bbox=137.36%2C-4.75%2C137.46%2C-4.65&f=json
- `data/raw/sim3292_overlay.png`: https://trek.nasa.gov/mars/trekarcgis/rest/services/SIM3292_Global_Geology/MapServer/export?bbox=137.36%2C-4.75%2C137.46%2C-4.65&bboxSR=104905&imageSR=104905&size=600%2C600&format=png32&transparent=true&f=image
- `data/raw/curiosity_photos.json`: https://mars.nasa.gov/api/v1/raw_image_items/?condition=msl&per_page=30&order=sol+desc
