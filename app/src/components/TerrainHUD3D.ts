import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { HabitatSite, RouteBundle, TargetSite, TerrainMesh, ViewMode } from '../types/contracts';
import type { EvaluatedRoute } from '../utils/pnrCalculator';

export class TerrainHUD3D {
  private container: HTMLElement;
  private meshData: TerrainMesh;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private controls: OrbitControls;

  private widthM: number;
  private depthM: number;
  private terrainGeo: THREE.PlaneGeometry;
  private terrainMesh: THREE.Mesh;
  private routeGroup = new THREE.Group();
  private markersGroup = new THREE.Group();

  private exaggeration = 1.5;
  private viewMode: ViewMode = 'terrain3d';
  private activeRoute: RouteBundle | null = null;
  private activeEval: EvaluatedRoute | null = null;
  private cursorIdx = 0;
  private playing = false;
  private playSpeed = 5;
  private lastTick = performance.now();
  private animId = 0;
  private onCursorChange: (idx: number) => void;

  // HUD DOM elements
  private hudOverlayEl: HTMLElement;
  private hudControlsEl: HTMLElement;

  constructor(
    container: HTMLElement,
    meshData: TerrainMesh,
    habitat: HabitatSite,
    targets: TargetSite[],
    onCursorChange: (idx: number) => void
  ) {
    this.container = container;
    this.meshData = meshData;
    this.onCursorChange = onCursorChange;

    const [lonMin, latMin, lonMax, latMax] = meshData.bbox;
    this.widthM = (lonMax - lonMin) * 59274.7 * Math.cos((-4.7 * Math.PI) / 180);
    this.depthM = (latMax - latMin) * 59274.7;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#130d0b');
    this.scene.fog = new THREE.FogExp2('#1c120e', 0.00009);

    const w = container.clientWidth || 900;
    const h = container.clientHeight || 600;
    this.camera = new THREE.PerspectiveCamera(58, w / h, 1.0, 30000);
    this.camera.position.set(-2800, 2600, 3200);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 300, 0);

    const hemi = new THREE.HemisphereLight('#ffd8b8', '#241a18', 1.25);
    this.scene.add(hemi);
    const sun = new THREE.DirectionalLight('#fff2e2', 1.1);
    sun.position.set(-3000, 5000, -2500);
    this.scene.add(sun);

    // Terrain PlaneGeometry
    this.terrainGeo = new THREE.PlaneGeometry(
      this.widthM,
      this.depthM,
      meshData.cols - 1,
      meshData.rows - 1
    );
    this.terrainGeo.rotateX(-Math.PI / 2);
    this.applyElevationToGeometry();

    const texLoader = new THREE.TextureLoader();
    const tex = texLoader.load('/layers/hirise_base.jpg');
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.MeshStandardMaterial({
      map: tex,
      roughness: 0.92,
      metalness: 0.04,
    });
    this.terrainMesh = new THREE.Mesh(this.terrainGeo, mat);
    this.scene.add(this.terrainMesh);
    this.scene.add(this.routeGroup);
    this.scene.add(this.markersGroup);

    // Build DOM overlays for 3D controls & 1st-person HUD visor
    this.hudControlsEl = document.createElement('div');
    this.hudControlsEl.className = 'hud-controls';
    this.container.appendChild(this.hudControlsEl);

    this.hudOverlayEl = document.createElement('div');
    this.hudOverlayEl.className = 'visor-hud hidden';
    this.container.appendChild(this.hudOverlayEl);

    this.rebuildStaticMarkers(habitat, targets);
    this.renderControlsPanel();
    this.animate();
  }

  private lonLatElevToXYZ(lon: number, lat: number, elevM: number): THREE.Vector3 {
    const [lonMin, latMin, lonMax, latMax] = this.meshData.bbox;
    const x = ((lon - lonMin) / (lonMax - lonMin) - 0.5) * this.widthM;
    const z = (0.5 - (lat - latMin) / (latMax - latMin)) * this.depthM;
    const y = (elevM - this.meshData.elev_min_m) * this.exaggeration;
    return new THREE.Vector3(x, y, z);
  }

  private applyElevationToGeometry(): void {
    const pos = this.terrainGeo.attributes.position as THREE.BufferAttribute;
    const { rows, cols, elev, elev_min_m } = this.meshData;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        pos.setY(idx, (elev[r][c] - elev_min_m) * this.exaggeration);
      }
    }
    pos.needsUpdate = true;
    this.terrainGeo.computeVertexNormals();
  }

  private rebuildStaticMarkers(habitat: HabitatSite, targets: TargetSite[]): void {
    this.markersGroup.clear();
    const habPos = this.lonLatElevToXYZ(habitat.lon, habitat.lat, habitat.elev_m);
    const habMesh = new THREE.Mesh(
      new THREE.CylinderGeometry(35, 45, 50, 16),
      new THREE.MeshBasicMaterial({ color: '#10b981' })
    );
    habMesh.position.copy(habPos).add(new THREE.Vector3(0, 25, 0));
    this.markersGroup.add(habMesh);

    for (const t of targets) {
      const tp = this.lonLatElevToXYZ(t.lon, t.lat, t.elev_m);
      const tMesh = new THREE.Mesh(
        new THREE.ConeGeometry(30, 80, 12),
        new THREE.MeshBasicMaterial({ color: '#e06d3b' })
      );
      tMesh.position.copy(tp).add(new THREE.Vector3(0, 40, 0));
      this.markersGroup.add(tMesh);
    }
  }

  public setExaggeration(exag: number, habitat: HabitatSite, targets: TargetSite[]): void {
    this.exaggeration = exag;
    this.applyElevationToGeometry();
    this.rebuildStaticMarkers(habitat, targets);
    if (this.activeRoute && this.activeEval) {
      this.updateRoute(this.activeRoute, this.activeEval);
    }
    this.renderControlsPanel();
  }

  public setMode(mode: ViewMode): void {
    this.viewMode = mode;
    if (mode === 'hud') {
      this.controls.enabled = false;
      this.hudOverlayEl.classList.remove('hidden');
      this.positionHudCamera();
    } else {
      this.playing = false;
      this.controls.enabled = true;
      this.hudOverlayEl.classList.add('hidden');
      this.camera.position.set(-2800, 2600, 3200);
      this.controls.target.set(0, 300, 0);
      this.controls.update();
    }
    this.renderControlsPanel();
  }

  public updateRoute(route: RouteBundle, evalResult: EvaluatedRoute): void {
    this.activeRoute = route;
    this.activeEval = evalResult;
    this.routeGroup.clear();

    const wps = route.waypoints_profile;
    const pnr = evalResult.pnrIdx;

    const safePts: THREE.Vector3[] = [];
    const beyondPts: THREE.Vector3[] = [];
    wps.forEach((w, i) => {
      const pt = this.lonLatElevToXYZ(w.lon, w.lat, w.elev_m).add(new THREE.Vector3(0, 8, 0));
      if (i <= pnr) safePts.push(pt);
      if (i >= pnr) beyondPts.push(pt);
    });

    if (safePts.length >= 2) {
      const geo = new THREE.BufferGeometry().setFromPoints(safePts);
      this.routeGroup.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#22d3ee' })));
    }
    if (beyondPts.length >= 2) {
      const geo = new THREE.BufferGeometry().setFromPoints(beyondPts);
      this.routeGroup.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#f59e0b' })));
    }

    // PNR pylon
    const pnrWp = evalResult.pnrWaypoint;
    const pnrPos = this.lonLatElevToXYZ(pnrWp.lon, pnrWp.lat, pnrWp.elev_m);
    const pnrBeacon = new THREE.Mesh(
      new THREE.CylinderGeometry(18, 18, 140, 12),
      new THREE.MeshBasicMaterial({ color: '#f59e0b' })
    );
    pnrBeacon.position.copy(pnrPos).add(new THREE.Vector3(0, 70, 0));
    this.routeGroup.add(pnrBeacon);

    this.cursorIdx = Math.min(this.cursorIdx, wps.length - 1);
    if (this.viewMode === 'hud') {
      this.positionHudCamera();
    }
    this.renderControlsPanel();
  }

  public setCursorIdx(idx: number): void {
    if (!this.activeRoute) return;
    this.cursorIdx = Math.max(0, Math.min(this.activeRoute.waypoints_profile.length - 1, idx));
    if (this.viewMode === 'hud') {
      this.positionHudCamera();
    }
    this.renderControlsPanel();
  }

  private positionHudCamera(): void {
    if (!this.activeRoute || !this.activeEval) return;
    const wps = this.activeRoute.waypoints_profile;
    const cur = wps[this.cursorIdx];
    const aheadIdx = Math.min(wps.length - 1, this.cursorIdx + 5);
    const ahead = wps[aheadIdx];

    const pCur = this.lonLatElevToXYZ(cur.lon, cur.lat, cur.elev_m);
    const pAhead = this.lonLatElevToXYZ(ahead.lon, ahead.lat, ahead.elev_m);
    const eyeOffset = Math.max(5.0, 1.6 * this.exaggeration);

    this.camera.position.set(pCur.x, pCur.y + eyeOffset, pCur.z);
    if (aheadIdx > this.cursorIdx) {
      this.camera.lookAt(pAhead.x, pAhead.y + eyeOffset * 0.9, pAhead.z);
    }

    const dx = pAhead.x - pCur.x;
    const dz = pAhead.z - pCur.z;
    const heading = ((Math.atan2(dx, -dz) * 180) / Math.PI + 360) % 360;

    const o2Rem = this.activeEval.scaledO2Remaining[this.cursorIdx];
    const backCost = this.activeEval.scaledBack[this.cursorIdx];
    const pastPnr = this.cursorIdx > this.activeEval.pnrIdx;

    this.hudOverlayEl.innerHTML = `
      <div class="visor-top">
        <div class="compass-bar">
          HDG ${heading.toFixed(0).padStart(3, '0')}° · ELEV ${cur.elev_m.toFixed(1)} m · DIST ${(cur.cum_dist_m / 1000).toFixed(2)} km
          ${pastPnr ? '<div class="hud-alert">SCENARIO TURN-BACK POINT (PNR) PASSED — RETURN RESERVE EXCEEDED</div>' : ''}
        </div>
      </div>
      <div class="visor-bottom">
        <div class="hud-telemetry-card">
          <div><strong>O₂ TANK REMAINING</strong> <span class="badge badge-SCENARIO">SCENARIO</span></div>
          <div style="font-size:18px;font-weight:800;color:${pastPnr ? '#ef4444' : '#34d399'};">${o2Rem.toFixed(1)} L O₂</div>
          <div>Return-to-Hab Back(x): ${backCost.toFixed(1)} ${this.activeEval.budgetUnit}</div>
          <div>Step Terrain: ${cur.dominant_cost_reason}</div>
        </div>
        <div class="hud-telemetry-card" style="text-align:right;">
          <div><strong>TERRAIN & COMMS</strong> <span class="badge badge-DERIVED">DERIVED</span></div>
          <div>Cell Slope (mean / max): ${cur.seg_slope_mean_deg.toFixed(1)}° / ${cur.seg_slope_max_deg.toFixed(1)}° (limit 15°)</div>
          <div>THEMIS 100m Sand Proxy η: ${cur.surf_eta.toFixed(2)}</div>
          <div>Habitat Geometric LOS: <strong style="color:${cur.los ? '#34d399' : '#f59e0b'}">${cur.los ? 'IN LINE-OF-SIGHT' : 'TERRAIN OCCLUDED'}</strong></div>
        </div>
      </div>
    `;
  }

  private renderControlsPanel(): void {
    const n = this.activeRoute ? this.activeRoute.waypoints_profile.length : 1;
    this.hudControlsEl.innerHTML = `
      <div style="font-weight:700;margin-bottom:4px;">${this.viewMode === 'hud' ? '1st-Person Helmet HUD (1.6 m eye)' : '3D Terrain Orbit View'}</div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:8px;">
        HiRISE DTM mesh + orbital ortho drape (not a photorealistic simulation).
      </div>
      <div class="ctrl-row">
        <div class="ctrl-label"><span>Vertical Exaggeration</span><span class="ctrl-val">${this.exaggeration.toFixed(1)}×</span></div>
        <input type="range" id="hud-exag" min="1.0" max="3.0" step="0.1" value="${this.exaggeration}" />
      </div>
      ${
        this.viewMode === 'hud'
          ? `
        <div style="display:flex;gap:6px;margin-bottom:6px;">
          <button class="btn-outline" id="hud-play" style="flex:1;">${this.playing ? 'Pause Walk' : 'Play Walk'}</button>
          <button class="btn-outline" id="hud-speed">${this.playSpeed}×</button>
        </div>
        <div class="ctrl-row" style="margin-bottom:0;">
          <div class="ctrl-label"><span>Route Progress</span><span class="ctrl-val">${Math.round((this.cursorIdx / Math.max(1, n - 1)) * 100)}%</span></div>
          <input type="range" id="hud-scrub" min="0" max="${Math.max(0, n - 1)}" value="${this.cursorIdx}" />
        </div>
      `
          : '<div style="font-size:10px;color:var(--muted);">Drag to orbit · Scroll to zoom · Right-drag to pan.</div>'
      }
    `;

    this.hudControlsEl.querySelector('#hud-exag')?.addEventListener('input', (e) => {
      const v = parseFloat((e.target as HTMLInputElement).value);
      this.exaggeration = v;
      this.applyElevationToGeometry();
      if (this.activeRoute && this.activeEval) this.updateRoute(this.activeRoute, this.activeEval);
      const valSpan = this.hudControlsEl.querySelector('.ctrl-val');
      if (valSpan) valSpan.textContent = `${v.toFixed(1)}×`;
    });

    this.hudControlsEl.querySelector('#hud-play')?.addEventListener('click', () => {
      this.playing = !this.playing;
      this.renderControlsPanel();
    });

    this.hudControlsEl.querySelector('#hud-speed')?.addEventListener('click', () => {
      this.playSpeed = this.playSpeed === 5 ? 15 : this.playSpeed === 15 ? 30 : 5;
      this.renderControlsPanel();
    });

    this.hudControlsEl.querySelector('#hud-scrub')?.addEventListener('input', (e) => {
      const idx = parseInt((e.target as HTMLInputElement).value, 10);
      this.cursorIdx = idx;
      this.positionHudCamera();
      this.onCursorChange(idx);
    });
  }

  private animate = (): void => {
    this.animId = requestAnimationFrame(this.animate);
    const now = performance.now();
    const dt = (now - this.lastTick) / 1000;
    this.lastTick = now;

    if (this.viewMode === 'hud' && this.playing && this.activeRoute) {
      const n = this.activeRoute.waypoints_profile.length;
      if (dt > 0.04) {
        const step = Math.max(1, Math.round(this.playSpeed * 0.4));
        if (this.cursorIdx + step < n) {
          this.cursorIdx += step;
          this.positionHudCamera();
          this.onCursorChange(this.cursorIdx);
          const scrub = this.hudControlsEl.querySelector('#hud-scrub') as HTMLInputElement | null;
          if (scrub) scrub.value = String(this.cursorIdx);
        } else {
          this.playing = false;
          this.renderControlsPanel();
        }
      }
    } else if (this.controls.enabled) {
      this.controls.update();
    }

    this.renderer.render(this.scene, this.camera);
  };

  public resize(): void {
    const w = this.container.clientWidth || 900;
    const h = this.container.clientHeight || 600;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  public dispose(): void {
    cancelAnimationFrame(this.animId);
    this.renderer.dispose();
  }
}
