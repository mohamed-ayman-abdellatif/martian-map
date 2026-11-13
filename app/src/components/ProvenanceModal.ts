import type { ConstantsFile, LayersManifest } from '../types/contracts';

export function renderProvenanceModal(
  root: HTMLElement,
  manifest: LayersManifest,
  constants: ConstantsFile,
  focusLayerId?: string
): void {
  root.classList.remove('hidden');
  root.innerHTML = `
    <div class="modal-backdrop" id="prov-backdrop">
      <div class="modal-box">
        <div class="modal-head">
          <div>
            <h2>Provenance & Honesty Inspector</h2>
            <div style="font-size:11px;color:var(--muted);">Every layer and model constant carries its primary NASA/USGS/PDS source, resolution, license, and Observed/Derived/Scenario/Unavailable badge.</div>
          </div>
          <button class="btn-outline" id="prov-close">Close</button>
        </div>
        <div class="modal-body">
          <div style="margin-bottom:10px;padding:8px 10px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.4);border-radius:6px;">
            <strong>Prototype Scope & Limitations:</strong> RedSight is a decision-support prototype. No rock-by-rock boot-scale walkability dataset exists; THEMIS thermal inertia is 100 m/px; CRISM maps mineral units (18-200 m/px) while 2025 boxwork veins were identified by Curiosity surface imaging; RAD and REMS are single roving point measurements (no spatial radiation or spatial weather map exists).
          </div>
          <h3 style="margin:10px 0 6px;font-size:13px;">Map Layers (${manifest.layers.length})</h3>
          <table class="audit-table">
            <thead>
              <tr>
                <th>Layer</th>
                <th>Badge</th>
                <th>Resolution / CRS</th>
                <th>Source & Limitations</th>
                <th>License / Credit</th>
              </tr>
            </thead>
            <tbody>
              ${manifest.layers
                .map(
                  (l) => `
                <tr style="${l.id === focusLayerId ? 'background:rgba(34,211,238,0.12);' : ''}">
                  <td><strong>${l.title}</strong><br><span style="color:var(--muted)">Type: ${l.data_kind}</span></td>
                  <td><span class="badge badge-${l.badge}">${l.badge}</span></td>
                  <td>${l.native_resolution}</td>
                  <td>
                    <a href="${l.source_url}" target="_blank" rel="noreferrer" style="color:var(--cyan);">${l.source_product}</a>
                    <div style="color:var(--muted);margin-top:2px;">${l.limitations}</div>
                  </td>
                  <td>${l.license}<br><span style="color:var(--muted)">${l.credit}</span></td>
                </tr>`
                )
                .join('')}
            </tbody>
          </table>

          <h3 style="margin:14px 0 6px;font-size:13px;">Model & Scenario Constants (${Object.keys(constants.constants).length})</h3>
          <table class="audit-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Value</th>
                <th>Badge</th>
                <th>Primary Source & Assumption Note</th>
              </tr>
            </thead>
            <tbody>
              ${Object.entries(constants.constants)
                .map(
                  ([k, c]) => `
                <tr>
                  <td><code>${k}</code></td>
                  <td style="font-family:var(--mono);">${c.formula ? 'Pandolf Eq.' : c.value} ${c.units}</td>
                  <td><span class="badge badge-${c.badge}">${c.badge}</span></td>
                  <td>
                    <a href="${c.source_url}" target="_blank" rel="noreferrer" style="color:var(--cyan);">${c.source_title}</a>
                    <div style="color:var(--muted);margin-top:2px;">${c.note}</div>
                  </td>
                </tr>`
                )
                .join('')}
            </tbody>
          </table>

          <div style="font-size:11px;color:var(--muted);">
            <strong>Open-Source Software Credits:</strong> MapLibre GL JS (BSD-3-Clause) · Three.js (MIT) · SciPy & NumPy (BSD-3-Clause) · CRS: ${constants.crs.name} (<code>${constants.crs.proj4}</code>).
          </div>
        </div>
      </div>
    </div>
  `;

  root.querySelector('#prov-close')?.addEventListener('click', () => root.classList.add('hidden'));
  root.querySelector('#prov-backdrop')?.addEventListener('click', (e) => {
    if (e.target === root.querySelector('#prov-backdrop')) root.classList.add('hidden');
  });
}
