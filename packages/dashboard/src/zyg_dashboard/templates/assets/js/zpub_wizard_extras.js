// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// ── Facial Hair Modal ──────────────────────────────────────────────────────────
(function() {
  const _FH_FACE = `<ellipse cx="22" cy="27" rx="10" ry="11" fill="#d4a574"/>`;
  function _fhs(inner) {
    return `<svg width="32" height="40" viewBox="0 0 44 50" style="display:block;margin:0 auto 2px">${_FH_FACE}${inner}</svg>`;
  }

  window._stFacialHairData = [
    { v:'none',              l:'None',              s:_fhs('') },
    { v:'stubble',           l:'Stubble',           s:_fhs(`<ellipse cx="22" cy="33" rx="8" ry="5" fill="#8b6040" opacity="0.55"/>`) },
    { v:'goatee',            l:'Goatee',            s:_fhs(`<ellipse cx="22" cy="34" rx="4.5" ry="5" fill="#6a4020" opacity="0.8"/>`) },
    { v:'mustache',          l:'Mustache',          s:_fhs(`<ellipse cx="22" cy="28.5" rx="7" ry="2.5" fill="#6a4020" opacity="0.85"/>`) },
    { v:'handlebar mustache',l:'Handlebar',         s:_fhs(`<ellipse cx="22" cy="28.5" rx="7" ry="2.2" fill="#6a4020" opacity="0.85"/><path d="M14,29 Q10,28 9,31" stroke="#6a4020" stroke-width="1.8" fill="none" stroke-linecap="round"/><path d="M30,29 Q34,28 35,31" stroke="#6a4020" stroke-width="1.8" fill="none" stroke-linecap="round"/>`) },
    { v:'short beard',       l:'Short Beard',       s:_fhs(`<ellipse cx="22" cy="33" rx="8.5" ry="7" fill="#6a4020" opacity="0.72"/>`) },
    { v:'full beard',        l:'Full Beard',        s:_fhs(`<ellipse cx="22" cy="34" rx="9" ry="7.5" fill="#6a4020" opacity="0.78"/>`) },
    { v:'long beard',        l:'Long Beard',        s:_fhs(`<ellipse cx="22" cy="34" rx="8.5" ry="7" fill="#6a4020" opacity="0.78"/><rect x="18" y="38" width="8" height="12" rx="4" fill="#6a4020" opacity="0.72"/>`) },
    { v:'van dyke',          l:'Van Dyke',          s:_fhs(`<ellipse cx="22" cy="28.5" rx="6" ry="2" fill="#6a4020" opacity="0.85"/><ellipse cx="22" cy="35" rx="3.5" ry="4.5" fill="#6a4020" opacity="0.8"/>`) },
    { v:'circle beard',      l:'Circle Beard',      s:_fhs(`<ellipse cx="22" cy="31.5" rx="6.5" ry="6" fill="#6a4020" opacity="0.75"/><ellipse cx="22" cy="31.5" rx="4" ry="4" fill="#d4a574"/>`) },
    { v:'anchor beard',      l:'Anchor Beard',      s:_fhs(`<ellipse cx="22" cy="28.5" rx="6" ry="2" fill="#6a4020" opacity="0.82"/><ellipse cx="22" cy="34.5" rx="3" ry="4" fill="#6a4020" opacity="0.8"/><rect x="20" y="33" width="4" height="7" rx="2" fill="#6a4020" opacity="0.65"/>`) },
    { v:'extended goatee',   l:'Extended Goatee',   s:_fhs(`<ellipse cx="22" cy="28.5" rx="6.5" ry="2" fill="#6a4020" opacity="0.82"/><ellipse cx="22" cy="35" rx="5.5" ry="5.5" fill="#6a4020" opacity="0.78"/>`) },
    { v:'chinstrap',         l:'Chinstrap',         s:_fhs(`<rect x="11.5" y="26" width="2.5" height="12" rx="1.2" fill="#6a4020" opacity="0.75"/><rect x="30" y="26" width="2.5" height="12" rx="1.2" fill="#6a4020" opacity="0.75"/><ellipse cx="22" cy="37.5" rx="3.5" ry="2.5" fill="#6a4020" opacity="0.75"/>`) },
    { v:'mutton chops',      l:'Mutton Chops',      s:_fhs(`<ellipse cx="13" cy="30" rx="5" ry="6.5" fill="#6a4020" opacity="0.72"/><ellipse cx="31" cy="30" rx="5" ry="6.5" fill="#6a4020" opacity="0.72"/>`) },
  ];

  window.stOpenFacialHairModal = function() {
    const body = document.getElementById('st-facial-modal-body');
    if (!body) return;
    const cur = (document.getElementById('st-facial-hair') || {}).value || 'none';
    let html = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">';
    window._stFacialHairData.forEach(item => {
      const sel = item.v === cur;
      html += `<button type="button" onclick="stSelectFacialHair('${item.v}','${item.l}')"
        style="background:${sel ? 'rgba(167,139,250,0.18)' : 'var(--surface2)'};border:${sel ? '2px solid var(--accent)' : '1px solid var(--border)'};border-radius:10px;padding:8px 4px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:4px;color:var(--text)">
        ${item.s}
        <span style="font-size:0.7rem;text-align:center;line-height:1.2">${item.l}</span>
      </button>`;
    });
    html += '</div>';
    body.innerHTML = html;
    document.getElementById('st-facial-modal').style.display = 'block';
  };

  window.stCloseFacialHairModal = function() {
    const m = document.getElementById('st-facial-modal');
    if (m) m.style.display = 'none';
  };

  window.stFacialHairModalBg = function(e) {
    if (e.target && e.target.id === 'st-facial-modal') stCloseFacialHairModal();
  };

  window.stSelectFacialHair = function(val, label) {
    const inp = document.getElementById('st-facial-hair');
    const lbl = document.getElementById('st-facial-label');
    const ico = document.getElementById('st-facial-icon');
    if (inp) inp.value = val;
    if (lbl) lbl.textContent = label;
    const iconMap = { none:'🪒', stubble:'🟫', goatee:'🧔', mustache:'👨', 'handlebar mustache':'🎩',
      'short beard':'🧔', 'full beard':'🧔‍♂️', 'long beard':'🧙', 'van dyke':'🎭', 'circle beard':'⭕',
      'anchor beard':'⚓', 'extended goatee':'🧔', chinstrap:'📐', 'mutton chops':'🦁' };
    if (ico) ico.textContent = iconMap[val] || '🪒';
    if (!window._stApplyingPhotoAnalysis) window._stMarkPhotoFieldEdited('facial_hair');
    stCloseFacialHairModal();
  };

  // muscle_mass is now 1-100 (continuous). Map to label zones.
  function _mmLabel(v) {
    if (v <= 20) return 'Slim';
    if (v <= 40) return 'Average';
    if (v <= 60) return 'Athletic';
    if (v <= 80) return 'Muscular';
    return 'Very Muscular';
  }

  function _mmSvg(v) {
    // Interpolate all measurements linearly across 1-100
    const t  = (v - 1) / 99;                // 0.0 → 1.0
    const sw = Math.round(18 + t * (42 - 18));  // shoulder width 18→42
    const cw = Math.round(12 + t * (28 - 12));  // chest width 12→28
    const aw = Math.round( 3 + t * ( 9 -  3));  // arm radius 3→9
    const cx = 26;
    return `<svg width="52" height="68" viewBox="0 0 52 68" style="display:block">
      <ellipse cx="${cx}" cy="14" rx="8" ry="9" fill="#d4a574"/>
      <rect x="${cx - cw/2}" y="22" width="${cw}" height="26" rx="4" fill="#7c9fc7"/>
      <rect x="${cx - sw/2 - aw}" y="22" width="${aw*2}" height="22" rx="${aw}" fill="#7c9fc7"/>
      <rect x="${cx + sw/2 - aw}" y="22" width="${aw*2}" height="22" rx="${aw}" fill="#7c9fc7"/>
      <rect x="${cx - 6}" y="48" width="12" height="20" rx="4" fill="#5a7faf"/>
    </svg>`;
  }

  window.stMuscleMassChange = function() {
    // Any change (user drag or photo-analysis apply) makes the slider value
    // deliberate — payload builders send 'auto' until this flag is set.
    window._stMuscleDirty = true;
    const sl = document.getElementById('st-muscle-mass');
    const lbl = document.getElementById('st-muscle-label');
    const prev = document.getElementById('st-muscle-preview');
    const v = parseInt((sl || {}).value || 20);
    if (lbl) lbl.textContent = _mmLabel(v);
    if (prev) prev.innerHTML = _mmSvg(v);
  };

  document.addEventListener('DOMContentLoaded', function() {
    const prev = document.getElementById('st-muscle-preview');
    if (prev) prev.innerHTML = _mmSvg(20);
    if (typeof window._stInitPhotoFieldTracking === 'function') window._stInitPhotoFieldTracking();
    if (typeof window.stOnPipelineModeChange === 'function') window.stOnPipelineModeChange();
  });
})();
