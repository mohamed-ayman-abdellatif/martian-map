import type { EnvironmentContext } from '../types/contracts';

export function renderEnvironmentModal(
  root: HTMLElement,
  env: EnvironmentContext,
  selectedSepId: string,
  onChangeSep: (sepId: string) => void
): void {
  root.classList.remove('hidden');
  const sep = env.radiation.sep_scenarios.find((s) => s.id === selectedSepId) ?? env.radiation.sep_scenarios[0];
  const hourlyGcr = env.radiation.gcr_baseline_msv_day / 24;
  const total8hDose = hourlyGcr * 8 * sep.multiplier + sep.extra_dose_msv;
  const shieldedDose = total8hDose * env.radiation.svf_summary.mean;

  const solarSvgPts = env.weather_rems.solar_curve
    .map((p, idx) => {
      const x = 35 + (idx / (env.weather_rems.solar_curve.length - 1)) * 390;
      const y = 95 - (Math.max(0, p.sun_elevation_deg) / 75) * 75;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  root.innerHTML = `
    <div class="modal-backdrop" id="env-backdrop">
      <div class="modal-box">
        <div class="modal-head">
          <div>
            <h2>Radiation (RAD) & Weather/Daylight (REMS) Context</h2>
            <div style="font-size:11px;color:var(--muted);">Honest rover-point observations + labeled Scenario models (no spatial radiation or local weather maps exist).</div>
          </div>
          <button class="btn-outline" id="env-close">Close</button>
        </div>
        <div class="modal-body" style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
          <div class="card">
            <div class="card-header">
              <span class="card-title">Surface Radiation Context (RAD)</span>
              <span class="badge badge-OBSERVED">OBSERVED POINT</span>
            </div>
            <p style="margin:0 0 8px;">
              <strong>GCR Baseline:</strong> ${env.radiation.gcr_baseline_msv_day} ± ${env.radiation.gcr_uncertainty_msv_day} mSv/day
              <br><span style="color:var(--muted);">${env.radiation.source_citation}</span>
            </p>
            <div style="padding:6px 8px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:6px;margin-bottom:10px;">
              <span class="badge badge-UNAVAILABLE">UNAVAILABLE</span> <strong>Spatial Radiation Map:</strong> ${env.radiation.spatial_note}
            </div>
            <label style="display:block;font-weight:600;margin-bottom:4px;">Select SEP Event Scenario <span class="badge badge-SCENARIO">SCENARIO</span></label>
            <select id="sep-select" style="width:100%;padding:6px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;margin-bottom:8px;">
              ${env.radiation.sep_scenarios
                .map((s) => `<option value="${s.id}" ${s.id === sep.id ? 'selected' : ''}>${s.label}</option>`)
                .join('')}
            </select>
            <div style="font-family:var(--mono);font-size:11px;background:var(--bg);padding:8px;border-radius:6px;">
              8-hr Open-Sky Scenario Dose: <strong>${total8hDose.toFixed(3)} mSv</strong><br>
              DEM Sky-View Shielded (SVF=${env.radiation.svf_summary.mean}): <strong>${shieldedDose.toFixed(3)} mSv</strong>
            </div>
            <div style="color:var(--muted);font-size:10px;margin-top:6px;">${sep.source}</div>
          </div>

          <div class="card">
            <div class="card-header">
              <span class="card-title">Atmosphere & Daylight Window (REMS)</span>
              <span class="badge badge-OBSERVED">OBSERVED POINT</span>
            </div>
            <p style="margin:0 0 8px;">
              <strong>Annual Pressure:</strong> ${env.weather_rems.pressure_range_pa[0]}–${env.weather_rems.pressure_range_pa[1]} Pa<br>
              <strong>Air Temp:</strong> ${env.weather_rems.air_temp_c_range[0]}°C to ${env.weather_rems.air_temp_c_range[1]}°C ·
              <strong>Ground:</strong> ${env.weather_rems.ground_temp_c_range[0]}°C to +${env.weather_rems.ground_temp_c_range[1]}°C<br>
              <span style="color:var(--muted);">${env.weather_rems.source_citation}</span>
            </p>
            <div style="font-size:11px;color:var(--muted);margin-bottom:6px;">
              <span class="badge badge-SCENARIO">SCENARIO</span> ${env.weather_rems.mcd_note}
            </div>
            <div style="font-weight:600;margin-bottom:4px;">Gale Solar Elevation Window <span class="badge badge-DERIVED">DERIVED</span></div>
            <svg viewBox="0 0 440 115" style="width:100%;background:var(--bg);border-radius:6px;border:1px solid var(--border);">
              <polyline points="${solarSvgPts}" fill="none" stroke="#f59e0b" stroke-width="2.5"/>
              <line x1="35" y1="95" x2="425" y2="95" stroke="#25334d" stroke-width="1"/>
              <text x="35" y="109" fill="#93a4bf" font-size="9">05:30 LTST</text>
              <text x="230" y="109" fill="#93a4bf" font-size="9" text-anchor="middle">12:00 Noon (~61° el)</text>
              <text x="425" y="109" fill="#93a4bf" font-size="9" text-anchor="end">18:30 LTST</text>
            </svg>
          </div>
        </div>
      </div>
    </div>
  `;

  root.querySelector('#env-close')?.addEventListener('click', () => root.classList.add('hidden'));
  root.querySelector('#env-backdrop')?.addEventListener('click', (e) => {
    if (e.target === root.querySelector('#env-backdrop')) root.classList.add('hidden');
  });
  root.querySelector('#sep-select')?.addEventListener('change', (e) => {
    const val = (e.target as HTMLSelectElement).value;
    onChangeSep(val);
    renderEnvironmentModal(root, env, val, onChangeSep);
  });
}
