import type { RouteBundle } from '../types/contracts';
import type { EvaluatedRoute } from '../utils/pnrCalculator';

export function renderProfileChart(
  container: HTMLElement,
  route: RouteBundle,
  evalResult: EvaluatedRoute,
  cursorIdx: number,
  onSelectCursor: (idx: number) => void
): void {
  const wps = route.waypoints_profile;
  const n = wps.length;
  if (n < 2) return;

  const totalDistKm = Math.max(0.1, route.summary.distance_m / 1000);
  const elevs = wps.map((w) => w.elev_m);
  const minE = Math.min(...elevs) - 10;
  const maxE = Math.max(...elevs) + 10;

  const W = 900;
  const H = 132;
  const padL = 48;
  const padR = 54;
  const padT = 12;
  const padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const xOf = (i: number) => padL + (i / (n - 1)) * plotW;
  const yElev = (e: number) => padT + plotH - ((e - minE) / Math.max(1, maxE - minE)) * plotH;
  const maxCost = Math.max(evalResult.totalBudget * 1.15, ...evalResult.scaledUsed.map((u, i) => u + evalResult.scaledBack[i]), 1);
  const yCost = (v: number) => padT + plotH - (Math.min(v, maxCost) / maxCost) * plotH;

  const elevPts = wps.map((w, i) => `${xOf(i).toFixed(1)},${yElev(w.elev_m).toFixed(1)}`).join(' ');
  const areaPts = `${padL},${padT + plotH} ${elevPts} ${padL + plotW},${padT + plotH}`;
  const costPts = wps
    .map((_, i) => `${xOf(i).toFixed(1)},${yCost(evalResult.scaledUsed[i] + evalResult.scaledBack[i]).toFixed(1)}`)
    .join(' ');

  const usableY = yCost(evalResult.usableBudget);
  const pnrX = xOf(evalResult.pnrIdx);
  const curX = xOf(Math.min(n - 1, Math.max(0, cursorIdx)));

  container.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:100%;cursor:crosshair;" id="profile-svg">
      <defs>
        <linearGradient id="elevFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#e06d3b" stop-opacity="0.45"/>
          <stop offset="100%" stop-color="#e06d3b" stop-opacity="0.05"/>
        </linearGradient>
      </defs>
      <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="#080c14" stroke="#25334d" stroke-width="1"/>
      <polygon points="${areaPts}" fill="url(#elevFill)"/>
      <polyline points="${elevPts}" fill="none" stroke="#e06d3b" stroke-width="2"/>
      <line x1="${padL}" y1="${usableY.toFixed(1)}" x2="${padL + plotW}" y2="${usableY.toFixed(1)}" stroke="#10b981" stroke-width="1.2" stroke-dasharray="4,3"/>
      <polyline points="${costPts}" fill="none" stroke="#38bdf8" stroke-width="1.8"/>
      <line x1="${pnrX.toFixed(1)}" y1="${padT}" x2="${pnrX.toFixed(1)}" y2="${padT + plotH}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="3,2"/>
      <circle cx="${curX.toFixed(1)}" cy="${yElev(wps[Math.min(n - 1, cursorIdx)].elev_m).toFixed(1)}" r="4.5" fill="#22d3ee" stroke="#fff" stroke-width="1.5"/>

      <text x="${padL - 4}" y="${padT + 9}" fill="#93a4bf" font-size="9" text-anchor="end">${maxE.toFixed(0)}m</text>
      <text x="${padL - 4}" y="${padT + plotH}" fill="#93a4bf" font-size="9" text-anchor="end">${minE.toFixed(0)}m</text>
      <text x="${padL + plotW + 4}" y="${usableY.toFixed(1)}" fill="#10b981" font-size="9" dominant-baseline="middle">Usable</text>
      <text x="${pnrX.toFixed(1)}" y="${padT + 9}" fill="#f59e0b" font-size="9" text-anchor="middle">PNR</text>
      <text x="${padL}" y="${H - 5}" fill="#93a4bf" font-size="9">0 km (Habitat)</text>
      <text x="${padL + plotW * 0.5}" y="${H - 5}" fill="#93a4bf" font-size="9" text-anchor="middle">
        Orange: Elevation (m above areoid) · Blue: Outbound+Return (${evalResult.budgetUnit}) · Dashed Green: Usable Budget
      </text>
      <text x="${padL + plotW}" y="${H - 5}" fill="#93a4bf" font-size="9" text-anchor="end">${totalDistKm.toFixed(2)} km (Goal)</text>
    </svg>
  `;

  const svg = container.querySelector('#profile-svg') as SVGSVGElement | null;
  if (svg) {
    svg.addEventListener('click', (ev) => {
      const rect = svg.getBoundingClientRect();
      const frac = ((ev.clientX - rect.left) / rect.width) * W;
      const t = Math.max(0, Math.min(1, (frac - padL) / plotW));
      onSelectCursor(Math.round(t * (n - 1)));
    });
  }
}
