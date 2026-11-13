import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type {
  CuriosityPhotoPin,
  HabitatSite,
  LayerMeta,
  RouteBundle,
  RouteMode,
  TargetSite,
} from '../types/contracts';
import type { EvaluatedRoute } from '../utils/pnrCalculator';

export class MapView2D {
  private map: maplibregl.Map;
  private ready = false;
  private pendingUpdate: (() => void) | null = null;
  private pnrMarker: maplibregl.Marker | null = null;
  private hudCursorMarker: maplibregl.Marker | null = null;

  constructor(
    container: HTMLElement,
    bbox: [number, number, number, number],
    layers: LayerMeta[],
    habitat: HabitatSite,
    targets: TargetSite[],
    photos: CuriosityPhotoPin[],
    onSelectGoal: (goalId: string) => void
  ) {
    const [lonMin, latMin, lonMax, latMax] = bbox;
    const centerLon = 0.5 * (lonMin + lonMax);
    const centerLat = 0.5 * (latMin + latMax);

    const imgCoords: [[number, number], [number, number], [number, number], [number, number]] = [
      [lonMin, latMax],
      [lonMax, latMax],
      [lonMax, latMin],
      [lonMin, latMin],
    ];

    const sources: Record<string, maplibregl.SourceSpecification> = {};
    const styleLayers: maplibregl.LayerSpecification[] = [
      {
        id: 'bg-mars',
        type: 'background',
        paint: { 'background-color': '#0b0f17' },
      },
    ];

    for (const lyr of layers) {
      sources[`src-${lyr.id}`] = {
        type: 'image',
        url: lyr.image_url,
        coordinates: imgCoords,
      };
      styleLayers.push({
        id: `lyr-${lyr.id}`,
        type: 'raster',
        source: `src-${lyr.id}`,
        layout: {
          visibility: lyr.default_visible ? 'visible' : 'none',
        },
        paint: {
          'raster-opacity': lyr.default_opacity,
          'raster-resampling': lyr.pixelated ? 'nearest' : 'linear',
        },
      });
    }

    this.map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        sources,
        layers: styleLayers,
      },
      center: [centerLon, centerLat],
      zoom: 12.6,
      minZoom: 11.2,
      maxZoom: 16.5,
      attributionControl: false,
    });

    this.map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-left');

    this.map.on('load', () => {
      this.ready = true;
      this.initVectorSources(habitat, targets, photos, onSelectGoal);
      if (this.pendingUpdate) {
        this.pendingUpdate();
        this.pendingUpdate = null;
      }
    });
  }

  private initVectorSources(
    habitat: HabitatSite,
    targets: TargetSite[],
    photos: CuriosityPhotoPin[],
    onSelectGoal: (goalId: string) => void
  ): void {
    const emptyFc: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

    this.map.addSource('routes-alt', { type: 'geojson', data: emptyFc });
    this.map.addSource('route-active-safe', { type: 'geojson', data: emptyFc });
    this.map.addSource('route-active-beyond', { type: 'geojson', data: emptyFc });

    this.map.addLayer({
      id: 'routes-alt-line',
      type: 'line',
      source: 'routes-alt',
      paint: {
        'line-color': ['get', 'color'],
        'line-width': 2.2,
        'line-opacity': 0.55,
        'line-dasharray': [2, 2],
      },
    });

    this.map.addLayer({
      id: 'route-active-beyond-line',
      type: 'line',
      source: 'route-active-beyond',
      paint: {
        'line-color': '#f59e0b',
        'line-width': 4.5,
        'line-opacity': 0.92,
        'line-dasharray': [1.5, 1.2],
      },
    });

    this.map.addLayer({
      id: 'route-active-safe-line',
      type: 'line',
      source: 'route-active-safe',
      paint: {
        'line-color': '#22d3ee',
        'line-width': 4.8,
        'line-opacity': 0.96,
      },
    });

    // Habitat Marker
    const habEl = document.createElement('div');
    habEl.style.cssText =
      'width:18px;height:18px;border-radius:50%;background:#10b981;border:2px solid #fff;box-shadow:0 0 10px #10b981;cursor:pointer;';
    new maplibregl.Marker({ element: habEl })
      .setLngLat([habitat.lon, habitat.lat])
      .setPopup(
        new maplibregl.Popup({ offset: 14 }).setHTML(
          `<strong>${habitat.name}</strong><br><span class="badge badge-SCENARIO">SCENARIO</span><br>${habitat.lat.toFixed(4)}°N, ${habitat.lon.toFixed(4)}°E · ${habitat.elev_m} m`
        )
      )
      .addTo(this.map);

    // Target Markers
    for (const t of targets) {
      const el = document.createElement('div');
      el.style.cssText =
        'padding:3px 7px;border-radius:12px;background:#e06d3b;color:#fff;font-size:10px;font-weight:700;border:1.5px solid #fff;cursor:pointer;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.6);';
      el.textContent = t.name.split(' ').slice(0, 2).join(' ');
      el.addEventListener('click', () => onSelectGoal(t.id));
      new maplibregl.Marker({ element: el })
        .setLngLat([t.lon, t.lat])
        .setPopup(
          new maplibregl.Popup({ offset: 14 }).setHTML(
            `<strong>${t.name}</strong><br><span class="badge badge-${t.badge}">${t.badge}</span> · ${t.elev_m} m<br><div style="margin-top:4px">${t.evidence}</div>`
          )
        )
        .addTo(this.map);
    }

    // Curiosity Raw Photo Pins (approximate location)
    for (const ph of photos) {
      const pel = document.createElement('div');
      pel.style.cssText =
        'width:14px;height:14px;border-radius:3px;background:#a855f7;border:1.5px solid #fff;cursor:pointer;box-shadow:0 0 6px rgba(168,85,247,0.8);';
      pel.title = `Curiosity Sol ${ph.sol} (${ph.instrument}) — Approx location`;
      new maplibregl.Marker({ element: pel })
        .setLngLat([ph.lon, ph.lat])
        .setPopup(
          new maplibregl.Popup({ offset: 12 }).setHTML(
            `<div><strong>Sol ${ph.sol} · ${ph.instrument}</strong> <span class="badge badge-OBSERVED">OBSERVED</span></div>
             <img src="${ph.local_image}" alt="Curiosity raw" style="width:100%;border-radius:4px;margin:6px 0;max-height:140px;object-fit:cover;"/>
             <div style="font-size:10px;color:#fbbf24;">${ph.location_accuracy}</div>
             <div style="font-size:10px;color:#93a4bf;margin-top:3px;">Credit: ${ph.credit}</div>`
          )
        )
        .addTo(this.map);
    }
  }

  public setLayerVisibility(layerId: string, visible: boolean): void {
    if (!this.ready) return;
    this.map.setLayoutProperty(`lyr-${layerId}`, 'visibility', visible ? 'visible' : 'none');
  }

  public setLayerOpacity(layerId: string, opacity: number): void {
    if (!this.ready) return;
    this.map.setPaintProperty(`lyr-${layerId}`, 'raster-opacity', opacity);
  }

  public updateRoutes(
    allModes: Record<RouteMode, RouteBundle>,
    activeMode: RouteMode,
    evalResult: EvaluatedRoute
  ): void {
    const apply = () => {
      const modeColors: Record<RouteMode, string> = {
        fastest: '#f43f5e',
        balanced: '#38bdf8',
        safest: '#10b981',
      };

      const altFeatures: GeoJSON.Feature[] = [];
      (['fastest', 'balanced', 'safest'] as RouteMode[]).forEach((m) => {
        if (m === activeMode) return;
        const b = allModes[m];
        if (!b) return;
        altFeatures.push({
          type: 'Feature',
          properties: { mode: m, color: modeColors[m] },
          geometry: {
            type: 'LineString',
            coordinates: b.geometry.coordinates.map((c) => [c[0], c[1]]),
          },
        });
      });

      const active = allModes[activeMode];
      const coords = active.geometry.coordinates.map((c) => [c[0], c[1]]);
      const pnr = evalResult.pnrIdx;

      const safeCoords = coords.slice(0, pnr + 1);
      const beyondCoords = coords.slice(pnr);

      (this.map.getSource('routes-alt') as maplibregl.GeoJSONSource).setData({
        type: 'FeatureCollection',
        features: altFeatures,
      });
      (this.map.getSource('route-active-safe') as maplibregl.GeoJSONSource).setData({
        type: 'FeatureCollection',
        features:
          safeCoords.length >= 2
            ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: safeCoords } }]
            : [],
      });
      (this.map.getSource('route-active-beyond') as maplibregl.GeoJSONSource).setData({
        type: 'FeatureCollection',
        features:
          beyondCoords.length >= 2
            ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: beyondCoords } }]
            : [],
      });

      // Live Turn-Back (PNR) marker
      if (this.pnrMarker) this.pnrMarker.remove();
      const wp = evalResult.pnrWaypoint;
      const pnrEl = document.createElement('div');
      pnrEl.style.cssText =
        'padding:2px 7px;border-radius:4px;background:#f59e0b;color:#080c14;font-size:10px;font-weight:800;border:1.5px solid #fff;box-shadow:0 0 10px rgba(245,158,11,0.9);white-space:nowrap;';
      pnrEl.textContent = evalResult.goalReachableWithinReserve ? 'PNR ≥ GOAL' : 'TURN-BACK (PNR)';

      this.pnrMarker = new maplibregl.Marker({ element: pnrEl })
        .setLngLat([wp.lon, wp.lat])
        .setPopup(
          new maplibregl.Popup({ offset: 12 }).setHTML(
            `<strong>Modeled Turn-Back Point (PNR)</strong> <span class="badge badge-SCENARIO">SCENARIO</span>
             <div style="margin-top:4px;">At ${(wp.cum_dist_m / 1000).toFixed(2)} km outbound (${(wp.used_time_s / 60).toFixed(1)} min)</div>
             <div style="font-size:10px;color:#93a4bf;margin-top:3px;">Scenario estimate assuming Pandolf metabolism + ${(evalResult.usableBudget).toFixed(0)} ${evalResult.budgetUnit} usable budget. Not a flight rule.</div>`
          )
        )
        .addTo(this.map);
    };

    if (!this.ready) {
      this.pendingUpdate = apply;
    } else {
      apply();
    }
  }

  public setCursorLocation(lon: number, lat: number): void {
    if (!this.ready) return;
    if (!this.hudCursorMarker) {
      const el = document.createElement('div');
      el.style.cssText =
        'width:12px;height:12px;border-radius:50%;background:#fff;border:2px solid #22d3ee;box-shadow:0 0 8px #22d3ee;';
      this.hudCursorMarker = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(this.map);
    } else {
      this.hudCursorMarker.setLngLat([lon, lat]);
    }
  }

  public resize(): void {
    this.map.resize();
  }
}
