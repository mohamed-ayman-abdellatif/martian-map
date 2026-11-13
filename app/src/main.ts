import './style.css';
import type {
  ConstantsFile,
  EnvironmentContext,
  LayersManifest,
  MissionParams,
  RouteBundle,
  RouteMode,
  TargetsFile,
  TerrainMesh,
  ViewMode,
} from './types/contracts';
import { evaluateMissionRoute } from './utils/pnrCalculator';
import { MapView2D } from './components/MapView2D';
import { TerrainHUD3D } from './components/TerrainHUD3D';
import { renderProfileChart } from './components/ProfileChart';
import { renderProvenanceModal } from './components/ProvenanceModal';
import { renderEnvironmentModal } from './components/EnvironmentModal';

async function loadJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  return res.json() as Promise<T>;
}

async function bootstrap(): Promise<void> {
  const root = document.getElementById('app')!;
  root.innerHTML = '<div style="padding:24px;color:#93a4bf;">Loading Gale Crater / Mount Sharp datasets...</div>';

  const [constants, manifest, targetsFile, envContext, terrainMesh] = await Promise.all([
    loadJson<ConstantsFile>('/data/constants.json'),
    loadJson<LayersManifest>('/data/layers_manifest.json'),
    loadJson<TargetsFile>('/data/targets.json'),
    loadJson<EnvironmentContext>('/data/environment_context.json'),
    loadJson<TerrainMesh>('/data/terrain_mesh.json'),
  ]);

  // Preload all 12 route bundles so switching goals/modes works 100% offline with zero latency
  const routesCache: Record<string, Record<RouteMode, RouteBundle>> = {};
  await Promise.all(
    targetsFile.targets.map(async (t) => {
      const [fastest, balanced, safest] = await Promise.all([
        loadJson<RouteBundle>(`/data/routes/${t.id}_fastest.json`),
        loadJson<RouteBundle>(`/data/routes/${t.id}_balanced.json`),
        loadJson<RouteBundle>(`/data/routes/${t.id}_safest.json`),
      ]);
      routesCache[t.id] = { fastest, balanced, safest };
    })
  );

  const state: {
    viewMode: ViewMode;
    params: MissionParams;
    cursorIdx: number;
    sepScenarioId: string;
    layerVis: Record<string, boolean>;
    layerOp: Record<string, number>;
  } = {
    viewMode: 'map2d',
    params: {
      goalId: targetsFile.targets[0].id,
      mode: 'balanced',
      crewMode: 'buddy',
      loadKg: 30,
      kappa: 1.3,
      budgetType: 'o2',
      o2BudgetLiters: 420,
      timeBudgetHours: 5.5,
      reserveFraction: 0.25,
    },
    cursorIdx: 0,
    sepScenarioId: envContext.radiation.sep_scenarios[0].id,
    layerVis: Object.fromEntries(manifest.layers.map((l) => [l.id, l.default_visible])),
    layerOp: Object.fromEntries(manifest.layers.map((l) => [l.id, l.default_opacity])),
  };

  root.innerHTML = `
    <div class="layout-root">
      <header class="topbar">
        <div class="brand">
          <div class="brand-dot"></div>
          <div>
            <h1>RedSight — Hyperlocal Marswalk Decision-Support Planner</h1>
            <div class="brand-sub">Gale Crater / Lower Mount Sharp (137.36°E–137.46°E, -4.75°N–-4.65°N) · NASA Space Apps 2026</div>
          </div>
        </div>
        <div class="view-tabs">
          <button class="tab-btn active" data-view="map2d">2D Layered Map</button>
          <button class="tab-btn" data-view="terrain3d">3D Terrain View</button>
          <button class="tab-btn" data-view="hud">1st-Person HUD</button>
        </div>
        <div class="topbar-actions">
          <button class="btn-outline" id="btn-env">RAD & REMS Cards</button>
          <button class="btn-outline" id="btn-prov">Provenance & Honesty Inspector</button>
        </div>
      </header>

      <div class="honesty-strip">
        <span><strong>Decision-Support Prototype:</strong> Uses real NASA/USGS/PDS data. All routes, O₂/time figures, and turn-back markers are modeled scenario estimates within stated assumptions — never a safety guarantee.</span>
        <span style="font-family:var(--mono);">15° hard slope limit (Scenario) · THEMIS 100m · RAD point</span>
      </div>

      <div class="workspace">
        <aside class="sidebar">
          <div class="card">
            <div class="card-header">
              <span class="card-title">1. Science Goal Picker</span>
              <span class="badge badge-OBSERVED">GALE TARGETS</span>
            </div>
            <div class="goal-list" id="goal-list"></div>
          </div>

          <div class="card">
            <div class="card-header">
              <span class="card-title">2. Excursion & Suit Setup</span>
              <span class="badge badge-SCENARIO">SCENARIO</span>
            </div>
            <div class="seg-group" id="crew-group">
              <button class="seg-btn active" data-crew="buddy">Buddy Pair (DRA 5.0)</button>
              <button class="seg-btn" data-crew="solo">Solo Contingency</button>
            </div>
            <div class="ctrl-row">
              <div class="ctrl-label"><span>Carried Load (L)</span><span class="ctrl-val" id="val-load">30 kg</span></div>
              <input type="range" id="inp-load" min="10" max="50" step="2" value="30" />
            </div>
            <div class="ctrl-row">
              <div class="ctrl-label"><span>Suit Overhead (κ, Norcross)</span><span class="ctrl-val" id="val-kappa">1.30×</span></div>
              <input type="range" id="inp-kappa" min="1.20" max="1.50" step="0.05" value="1.30" />
            </div>
            <div class="seg-group" id="budget-type-group">
              <button class="seg-btn active" data-btype="o2">O₂ Tank Budget</button>
              <button class="seg-btn" data-btype="time">Time Budget</button>
            </div>
            <div class="ctrl-row" id="row-o2-budget">
              <div class="ctrl-label"><span>Suit O₂ Supply</span><span class="ctrl-val" id="val-o2">420 L</span></div>
              <input type="range" id="inp-o2" min="200" max="800" step="10" value="420" />
            </div>
            <div class="ctrl-row hidden" id="row-time-budget">
              <div class="ctrl-label"><span>Excursion Window</span><span class="ctrl-val" id="val-time">5.5 h</span></div>
              <input type="range" id="inp-time" min="2.0" max="8.0" step="0.25" value="5.5" />
            </div>
            <div class="ctrl-row" style="margin-bottom:0;">
              <div class="ctrl-label"><span>Return Reserve Policy</span><span class="ctrl-val" id="val-reserve">25%</span></div>
              <input type="range" id="inp-reserve" min="15" max="40" step="1" value="25" />
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <span class="card-title">3. Route Modes & Turn-Back</span>
              <span class="badge badge-DERIVED">DIJKSTRA FIELD</span>
            </div>
            <div class="seg-group-3" id="mode-group">
              <button class="seg-btn" data-mode="fastest">Fastest</button>
              <button class="seg-btn active" data-mode="balanced">Balanced</button>
              <button class="seg-btn" data-mode="safest">Safest</button>
            </div>
            <div class="mode-caption" id="mode-caption"></div>
            <div id="route-comparison"></div>
          </div>
        </aside>

        <main class="viewport-wrap">
          <div id="map2d-container"></div>
          <div id="view3d-container" class="hidden"></div>

          <div class="layer-panel" id="layer-panel">
            <div class="card-header" style="margin-bottom:6px;">
              <span class="card-title">NASA & Derived Layers</span>
              <span style="font-size:10px;color:var(--muted);">Opacity + Info</span>
            </div>
            <div id="layer-list"></div>
          </div>

          <div class="map-legend" id="map-legend">
            <span><i class="leg-dot" style="background:#10b981"></i>Scenario Habitat</span>
            <span><i class="leg-dot" style="background:#e06d3b"></i>Science Target</span>
            <span><i class="leg-dot" style="background:#22d3ee"></i>Within Turn-Back Reserve</span>
            <span><i class="leg-dot" style="background:#f59e0b"></i>Beyond PNR Reserve</span>
            <span><i class="leg-dot" style="background:#a855f7"></i>Curiosity Photo (approx)</span>
          </div>
        </main>
      </div>

      <footer class="profile-dock">
        <div class="profile-summary" id="profile-summary"></div>
        <div class="profile-svg-wrap" id="profile-chart"></div>
      </footer>
    </div>
    <div id="modal-root" class="hidden"></div>
  `;

  const mapContainer = document.getElementById('map2d-container')!;
  const view3dContainer = document.getElementById('view3d-container')!;
  const modalRoot = document.getElementById('modal-root')!;

  const mapView = new MapView2D(
    mapContainer,
    manifest.ops_bbox_lonlat,
    manifest.layers,
    targetsFile.habitat,
    targetsFile.targets,
    envContext.curiosity_photos,
    (goalId) => {
      state.params.goalId = goalId;
      state.cursorIdx = 0;
      refresh();
    }
  );

  let view3d: TerrainHUD3D | null = null;
  const ensureView3D = () => {
    if (!view3d) {
      view3d = new TerrainHUD3D(
        view3dContainer,
        terrainMesh,
        targetsFile.habitat,
        targetsFile.targets,
        (idx) => {
          state.cursorIdx = idx;
          const r = routesCache[state.params.goalId][state.params.mode];
          const ev = evaluateMissionRoute(r, state.params);
          const wp = r.waypoints_profile[idx];
          mapView.setCursorLocation(wp.lon, wp.lat);
          renderProfileChart(
            document.getElementById('profile-chart')!,
            r,
            ev,
            state.cursorIdx,
            handleSelectCursor
          );
        }
      );
    }
    return view3d;
  };

  function handleSelectCursor(idx: number): void {
    state.cursorIdx = idx;
    const r = routesCache[state.params.goalId][state.params.mode];
    const wp = r.waypoints_profile[idx];
    mapView.setCursorLocation(wp.lon, wp.lat);
    if (view3d) view3d.setCursorIdx(idx);
    refreshProfileOnly();
  }

  function renderGoals(): void {
    const el = document.getElementById('goal-list')!;
    el.innerHTML = targetsFile.targets
      .map(
        (t) => `
      <button class="goal-btn ${t.id === state.params.goalId ? 'active' : ''}" data-goal="${t.id}">
        <div class="goal-top">
          <span>${t.name}</span>
          <span class="badge badge-${t.badge}">${t.badge}</span>
        </div>
        <div class="goal-meta">${t.category} · ${t.elev_m} m · ${t.geologic_unit}</div>
        <div class="goal-meta" style="color:#cbd5e1;">${t.evidence}</div>
      </button>`
      )
      .join('');

    el.querySelectorAll('.goal-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.params.goalId = (btn as HTMLElement).dataset.goal!;
        state.cursorIdx = 0;
        refresh();
      });
    });
  }

  function renderLayersPanel(): void {
    const el = document.getElementById('layer-list')!;
    el.innerHTML = manifest.layers
      .map(
        (l) => `
      <div class="layer-item">
        <div class="layer-top">
          <label>
            <input type="checkbox" data-vis="${l.id}" ${state.layerVis[l.id] ? 'checked' : ''} />
            <span>${l.title}</span>
          </label>
          <span class="badge badge-${l.badge}">${l.badge}</span>
        </div>
        <div class="layer-sub">
          <span>${l.native_resolution.split('(')[0].trim()}</span>
          <div style="display:flex;align-items:center;gap:4px;">
            <input type="range" data-op="${l.id}" min="0" max="1" step="0.05" value="${state.layerOp[l.id]}" style="width:65px;" />
            <button class="info-btn" data-info="${l.id}" title="View Provenance">i</button>
          </div>
        </div>
      </div>`
      )
      .join('');

    el.querySelectorAll('input[data-vis]').forEach((inp) => {
      inp.addEventListener('change', (e) => {
        const id = (e.target as HTMLInputElement).dataset.vis!;
        const vis = (e.target as HTMLInputElement).checked;
        state.layerVis[id] = vis;
        mapView.setLayerVisibility(id, vis);
      });
    });

    el.querySelectorAll('input[data-op]').forEach((inp) => {
      inp.addEventListener('input', (e) => {
        const id = (e.target as HTMLInputElement).dataset.op!;
        const op = parseFloat((e.target as HTMLInputElement).value);
        state.layerOp[id] = op;
        mapView.setLayerOpacity(id, op);
      });
    });

    el.querySelectorAll('button[data-info]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = (btn as HTMLElement).dataset.info!;
        renderProvenanceModal(modalRoot, manifest, constants, id);
      });
    });
  }

  function refreshProfileOnly(): void {
    const r = routesCache[state.params.goalId][state.params.mode];
    const ev = evaluateMissionRoute(r, state.params);
    const cur = r.waypoints_profile[Math.min(state.cursorIdx, r.waypoints_profile.length - 1)];

    document.getElementById('profile-summary')!.innerHTML = `
      <div><strong>Active Mode:</strong> ${r.mode.toUpperCase()} · <strong>Goal:</strong> ${r.goal_name}</div>
      <div>Cursor: <strong>${(cur.cum_dist_m / 1000).toFixed(2)} km</strong> · Elev ${cur.elev_m.toFixed(1)} m · Slope ${cur.seg_slope_mean_deg.toFixed(1)}°</div>
      <div>PNR Turn-Back: <strong>${(ev.pnrWaypoint.cum_dist_m / 1000).toFixed(2)} km</strong> (${ev.goalReachableWithinReserve ? 'Goal within reserve' : 'Turn back before goal'})</div>
      <div style="color:var(--muted);font-size:10px;">Click profile chart to inspect route or move 3D HUD cursor.</div>
    `;

    renderProfileChart(
      document.getElementById('profile-chart')!,
      r,
      ev,
      state.cursorIdx,
      handleSelectCursor
    );
  }

  function refresh(): void {
    renderGoals();
    const goalRoutes = routesCache[state.params.goalId];
    const activeRoute = goalRoutes[state.params.mode];
    const evalMap: Record<RouteMode, ReturnType<typeof evaluateMissionRoute>> = {
      fastest: evaluateMissionRoute(goalRoutes.fastest, state.params),
      balanced: evaluateMissionRoute(goalRoutes.balanced, state.params),
      safest: evaluateMissionRoute(goalRoutes.safest, state.params),
    };
    const activeEval = evalMap[state.params.mode];

    // Caption right on the mode selector (Review §2)
    document.getElementById('mode-caption')!.textContent =
      state.params.mode === 'safest'
        ? 'Safest = lowest modeled hazard-score within available data (5-10 m slope, 100 m thermal proxy, LOS).'
        : activeRoute.mode_caption;

    // Side-by-side raw axes + hazard breakdown
    const hb = activeRoute.summary.hazard_breakdown;
    const hTot = Math.max(1, hb.total_hazard_score);
    const sPct = (100 * hb.slope_penalty) / hTot;
    const saPct = (100 * hb.sand_ti_penalty) / hTot;
    const lPct = (100 * hb.los_penalty) / hTot;

    const pnrWp = activeEval.pnrWaypoint;
    const crewNote =
      state.params.crewMode === 'buddy'
        ? `2-astronaut buddy total: ${activeEval.totalCrewO2.toFixed(0)} L O₂`
        : `Solo contingency: ${activeEval.totalCrewO2.toFixed(0)} L O₂`;

    document.getElementById('route-comparison')!.innerHTML = `
      <table class="cmp-table">
        <thead>
          <tr>
            <th>Mode</th>
            <th>Dist</th>
            <th>RT Time</th>
            <th>RT O₂/suit</th>
            <th>Hazard</th>
          </tr>
        </thead>
        <tbody>
          ${(['fastest', 'balanced', 'safest'] as RouteMode[])
            .map((m) => {
              const r = goalRoutes[m];
              const ev = evalMap[m];
              return `
              <tr class="${m === state.params.mode ? 'cmp-row-active' : ''}">
                <td>${m.charAt(0).toUpperCase() + m.slice(1)}</td>
                <td>${(r.summary.distance_m / 1000).toFixed(2)} km</td>
                <td>${ev.totalRoundTripTimeMin.toFixed(0)} m</td>
                <td>${ev.totalRoundTripO2PerSuit.toFixed(0)} L</td>
                <td>${r.summary.hazard_breakdown.total_hazard_score.toFixed(0)}</td>
              </tr>`;
            })
            .join('')}
        </tbody>
      </table>

      <div style="font-size:11px;margin-bottom:4px;">
        <strong>Max / Mean Slope:</strong> ${activeRoute.summary.max_slope_crossed_deg}° / ${activeRoute.summary.mean_slope_deg}° (hard limit ${activeRoute.summary.hard_limit_deg}°) · <strong>LOS:</strong> ${activeRoute.summary.los_coverage_pct}%
      </div>

      <div class="hazard-bar" title="Modeled hazard score breakdown">
        <div style="width:${sPct.toFixed(1)}%;background:#ef4444;" title="Slope penalty"></div>
        <div style="width:${saPct.toFixed(1)}%;background:#f59e0b;" title="100m Sand proxy"></div>
        <div style="width:${lPct.toFixed(1)}%;background:#a855f7;" title="Off-LOS"></div>
      </div>
      <div class="hazard-legend">
        <span><i class="leg-dot" style="background:#ef4444"></i>Slope (${hb.slope_penalty.toFixed(0)})</span>
        <span><i class="leg-dot" style="background:#f59e0b"></i>100m Sand (${hb.sand_ti_penalty.toFixed(0)})</span>
        <span><i class="leg-dot" style="background:#a855f7"></i>Off-LOS (${hb.los_penalty.toFixed(0)})</span>
      </div>

      <div class="pnr-box ${activeEval.goalReachableWithinReserve ? 'pnr-ok' : 'pnr-warn'}" style="margin-top:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
          <strong>Turn-Back Estimate (PNR)</strong>
          <span class="badge badge-SCENARIO">SCENARIO</span>
        </div>
        ${
          activeEval.goalReachableWithinReserve
            ? `Goal reachable within ${Math.round(state.params.reserveFraction * 100)}% reserve (usable ${activeEval.usableBudget.toFixed(0)} ${activeEval.budgetUnit}).`
            : `Last turnaround at <strong>${(pnrWp.cum_dist_m / 1000).toFixed(2)} km</strong> (${(pnrWp.used_time_s / 60).toFixed(0)} min outbound) to preserve ${Math.round(state.params.reserveFraction * 100)}% reserve.`
        }
        <div style="color:var(--muted);font-size:10px;margin-top:3px;">
          ${crewNote}. ${activeEval.loadRescaled ? 'O₂ rescaled from 30 kg baseline; path unchanged.' : ''}
        </div>
      </div>
    `;

    mapView.updateRoutes(goalRoutes, state.params.mode, activeEval);
    if (view3d) {
      view3d.updateRoute(activeRoute, activeEval);
    }
    refreshProfileOnly();
  }

  // Bind UI controls
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const vm = (btn as HTMLElement).dataset.view as ViewMode;
      state.viewMode = vm;

      const layerPanel = document.getElementById('layer-panel')!;
      const legend = document.getElementById('map-legend')!;
      if (vm === 'map2d') {
        mapContainer.classList.remove('hidden');
        view3dContainer.classList.add('hidden');
        layerPanel.classList.remove('hidden');
        legend.classList.remove('hidden');
        mapView.resize();
      } else {
        mapContainer.classList.add('hidden');
        view3dContainer.classList.remove('hidden');
        layerPanel.classList.add('hidden');
        legend.classList.add('hidden');
        const v3 = ensureView3D();
        v3.resize();
        v3.updateRoute(
          routesCache[state.params.goalId][state.params.mode],
          evaluateMissionRoute(routesCache[state.params.goalId][state.params.mode], state.params)
        );
        v3.setMode(vm);
        v3.setCursorIdx(state.cursorIdx);
      }
    });
  });

  document.querySelectorAll('#crew-group .seg-btn').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#crew-group .seg-btn').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.params.crewMode = (b as HTMLElement).dataset.crew as 'buddy' | 'solo';
      refresh();
    });
  });

  document.querySelectorAll('#budget-type-group .seg-btn').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#budget-type-group .seg-btn').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      const bt = (b as HTMLElement).dataset.btype as 'o2' | 'time';
      state.params.budgetType = bt;
      document.getElementById('row-o2-budget')!.classList.toggle('hidden', bt !== 'o2');
      document.getElementById('row-time-budget')!.classList.toggle('hidden', bt !== 'time');
      refresh();
    });
  });

  document.querySelectorAll('#mode-group .seg-btn').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#mode-group .seg-btn').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.params.mode = (b as HTMLElement).dataset.mode as RouteMode;
      state.cursorIdx = 0;
      refresh();
    });
  });

  document.getElementById('inp-load')!.addEventListener('input', (e) => {
    state.params.loadKg = parseFloat((e.target as HTMLInputElement).value);
    document.getElementById('val-load')!.textContent = `${state.params.loadKg} kg`;
    refresh();
  });

  document.getElementById('inp-kappa')!.addEventListener('input', (e) => {
    state.params.kappa = parseFloat((e.target as HTMLInputElement).value);
    document.getElementById('val-kappa')!.textContent = `${state.params.kappa.toFixed(2)}×`;
    refresh();
  });

  document.getElementById('inp-o2')!.addEventListener('input', (e) => {
    state.params.o2BudgetLiters = parseFloat((e.target as HTMLInputElement).value);
    document.getElementById('val-o2')!.textContent = `${state.params.o2BudgetLiters} L`;
    refresh();
  });

  document.getElementById('inp-time')!.addEventListener('input', (e) => {
    state.params.timeBudgetHours = parseFloat((e.target as HTMLInputElement).value);
    document.getElementById('val-time')!.textContent = `${state.params.timeBudgetHours.toFixed(2)} h`;
    refresh();
  });

  document.getElementById('inp-reserve')!.addEventListener('input', (e) => {
    const pct = parseFloat((e.target as HTMLInputElement).value);
    state.params.reserveFraction = pct / 100;
    document.getElementById('val-reserve')!.textContent = `${pct}%`;
    refresh();
  });

  document.getElementById('btn-prov')!.addEventListener('click', () => {
    renderProvenanceModal(modalRoot, manifest, constants);
  });

  document.getElementById('btn-env')!.addEventListener('click', () => {
    renderEnvironmentModal(modalRoot, envContext, state.sepScenarioId, (id) => {
      state.sepScenarioId = id;
    });
  });

  window.addEventListener('resize', () => {
    mapView.resize();
    if (view3d) view3d.resize();
  });

  renderLayersPanel();
  refresh();
}

bootstrap().catch((err) => {
  console.error(err);
  document.getElementById('app')!.innerHTML = `<pre style="color:#fca5a5;padding:20px;">${String(err)}</pre>`;
});
