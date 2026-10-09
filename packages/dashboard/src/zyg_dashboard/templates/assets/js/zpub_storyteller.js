// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

(function(){
  var el = document.getElementById('ams-clock');
  function tick(){
    var now = new Date();
    var datePart = now.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Amsterdam'});
    var timePart = now.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Europe/Amsterdam'});
    el.textContent = datePart + '  ' + timePart + ' AMS';
  }
  tick();
  setInterval(tick, 1000);
})();

// ── Storyteller Wizard JavaScript ──────────────────────────────────────────────
(function() {
  'use strict';

  // Skin tone swatch picker
  window.stPickSkin = function(btn, value) {
    document.getElementById('st-skin').value = value;
    const label = value.charAt(0).toUpperCase() + value.slice(1);
    const labelEl = document.getElementById('st-skin-label');
    if (labelEl) labelEl.textContent = 'Selected: ' + label;
    document.querySelectorAll('#st-skin-swatches button').forEach(b => b.style.border = '2px solid transparent');
    btn.style.border = '2px solid #a78bfa';
    if (!window._stApplyingPhotoAnalysis) window._stMarkPhotoFieldEdited('skin_tone');
  };

  /* ── Advanced Identity toggle / reset (every advanced field defaults to "Auto") ── */
  window.stToggleAdvIdentity = function() {
    const body = document.getElementById('st-adv-identity-body');
    const icon = document.getElementById('st-adv-identity-icon');
    if (!body) return;
    const open = body.style.display === 'block';
    body.style.display = open ? 'none' : 'block';
    if (icon) icon.textContent = open ? '▶' : '▼';
  };
  window.stResetAdvIdentity = function() {
    document.querySelectorAll('.st-adv-input').forEach(el => {
      if (el.tagName === 'SELECT') {
        // Restore first <option> (which is always the "auto" choice for advanced fields)
        el.selectedIndex = 0;
      } else {
        el.value = '';
      }
    });
  };

  /* ── Hair Style Modal ─────────────────────────────────────────────────────── */
  (function(){
    const FA='<ellipse cx="19" cy="27" rx="10" ry="11" fill="#d4a574"/>';
    const HC='#5a4535';
    function _hs(h){return `<svg width="32" height="36" viewBox="0 0 38 44" style="display:block;margin:0 auto 2px">${h}${FA}</svg>`;}

    const CROWN=`<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/>`;
    const CROWN_W=`<ellipse cx="19" cy="14" rx="13" ry="8" fill="${HC}"/>`;
    const CROWN_S=`<ellipse cx="19" cy="18" rx="10" ry="5" fill="${HC}"/>`;
    const CROWN_T=`<ellipse cx="19" cy="17" rx="9" ry="3" fill="${HC}"/>`;
    const S_CHN=`<rect x="6" y="14" width="5" height="16" rx="2" fill="${HC}"/><rect x="27" y="14" width="5" height="16" rx="2" fill="${HC}"/>`;
    const S_SHR=`<rect x="5" y="13" width="5" height="22" rx="2" fill="${HC}"/><rect x="28" y="13" width="5" height="22" rx="2" fill="${HC}"/>`;
    const S_LNG=`<rect x="5" y="12" width="5" height="28" rx="2" fill="${HC}"/><rect x="28" y="12" width="5" height="28" rx="2" fill="${HC}"/>`;
    const W_MED=`<path d="M7,14 Q5,21 7,27 Q5,33 7,38" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M31,14 Q33,21 31,27 Q33,33 31,38" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/>`;
    const W_LNG=`<path d="M7,14 Q4,22 7,29 Q4,36 7,42" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M31,14 Q34,22 31,29 Q34,36 31,42" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/>`;
    const WC_MED=`<path d="M7,14 Q3,18 7,22 Q3,28 7,34" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,18 31,22 Q35,28 31,34" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/>`;
    const WC_LNG=`<path d="M7,14 Q3,18 7,23 Q3,29 7,35 Q3,41 7,44" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,18 31,23 Q35,29 31,35 Q35,41 31,44" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/>`;
    const AUTO_S=`<svg width="32" height="36" viewBox="0 0 38 44" style="display:block;margin:0 auto 2px"><path d="M19,2 L21,11 L30,8 L24,16 L33,19 L24,22 L30,30 L21,27 L19,36 L17,27 L8,30 L14,22 L5,19 L14,16 L8,8 L17,11 Z" fill="#a78bfa" opacity="0.85"/>${FA}</svg>`;

    window._stHairData = {
      female: [
        { sec:null, items:[{ v:'auto', l:'Auto', s:AUTO_S }]},
        { sec:'✂️ Short', items:[
          { v:'pixie cut',      l:'Pixie Cut',     s:_hs(`<ellipse cx="19" cy="18" rx="12" ry="8" fill="${HC}"/>`)},
          { v:'textured pixie', l:'Textured Pixie', s:_hs(`<ellipse cx="19" cy="18" rx="12" ry="8" fill="${HC}"/><path d="M17,10 Q19,5 21,10" stroke="${HC}" stroke-width="3" fill="none" stroke-linecap="round"/>`)},
          { v:'boy cut',        l:'Boy Cut',        s:_hs(CROWN_W)},
          { v:'buzz cut',       l:'Buzz Cut',       s:_hs(CROWN_S)},
          { v:'shaved head',    l:'Shaved',         s:_hs(CROWN_T)},
          { v:'1mm shave',      l:'1mm Shave',      s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="2" fill="${HC}" opacity="0.35"/>`)},
          { v:'bald',           l:'Bald',           s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="1.5" fill="#d4a574" opacity="0.15"/>`)},
          { v:'undercut short', l:'Undercut',       s:_hs(`<rect x="12" y="14" width="14" height="13" rx="2" fill="${HC}"/>`)},
          { v:'french crop',    l:'French Crop',    s:_hs(`${CROWN}<rect x="7" y="20" width="24" height="4" rx="0" fill="${HC}"/>`)},
          { v:'tapered nape',   l:'Tapered Nape',   s:_hs(`<ellipse cx="19" cy="17" rx="11" ry="6" fill="${HC}"/><path d="M9,27 Q9,23 19,23 Q29,23 29,27" fill="${HC}" opacity="0.5"/>`)},
          { v:'short afro',     l:'Short Afro',     s:_hs(`<ellipse cx="19" cy="17" rx="13" ry="9" fill="${HC}"/>`)},
        ]},
        { sec:'💁 Medium', items:[
          { v:'short bob',      l:'Short Bob',      s:_hs(`${S_CHN}${CROWN}`)},
          { v:'lob',            l:'Long Bob',       s:_hs(`${S_SHR}${CROWN}`)},
          { v:'blunt bob',      l:'Blunt Bob',      s:_hs(`<rect x="6" y="14" width="5" height="16" rx="0" fill="${HC}"/><rect x="27" y="14" width="5" height="16" rx="0" fill="${HC}"/>${CROWN}`)},
          { v:'wavy bob',       l:'Wavy Bob',       s:_hs(`${W_MED}${CROWN}`)},
          { v:'curly bob',      l:'Curly Bob',      s:_hs(`${WC_MED}${CROWN}`)},
          { v:'a-line bob',     l:'A-Line Bob',     s:_hs(`<rect x="6" y="14" width="5" height="22" rx="2" fill="${HC}"/><rect x="27" y="14" width="5" height="15" rx="2" fill="${HC}"/>${CROWN}`)},
          { v:'stacked bob',    l:'Stacked Bob',    s:_hs(`<rect x="7" y="14" width="5" height="16" rx="2" fill="${HC}"/><rect x="26" y="14" width="5" height="16" rx="2" fill="${HC}"/><ellipse cx="19" cy="14" rx="13" ry="9" fill="${HC}"/>`)},
          { v:'wolf cut',       l:'Wolf Cut',       s:_hs(`${W_MED}${CROWN_W}`)},
          { v:'butterfly cut',  l:'Butterfly',      s:_hs(`<path d="M6,14 Q3,22 6,30 Q2,38 6,42" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M32,14 Q35,22 32,30 Q36,38 32,42" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/>${CROWN}`)},
          { v:'shaggy',         l:'Shaggy',         s:_hs(`<path d="M7,14 Q5,20 7,26 Q5,32 7,38" stroke="${HC}" stroke-width="6" fill="none" stroke-linecap="round"/><path d="M31,14 Q33,20 31,26 Q33,32 31,38" stroke="${HC}" stroke-width="6" fill="none" stroke-linecap="round"/>${CROWN_W}`)},
          { v:'curtain bangs',  l:'Curtain Bangs',  s:_hs(`${S_SHR}${CROWN}<path d="M12,22 Q14,15 19,14" stroke="#d4a574" stroke-width="1.5" fill="none"/>`)},
          { v:'layered medium', l:'Layered',        s:_hs(`${S_SHR}${CROWN}<path d="M6,29 L11,30" stroke="#7a6040" stroke-width="1.5"/><path d="M32,29 L27,30" stroke="#7a6040" stroke-width="1.5"/>`)},
        ]},
        { sec:'🌊 Long', items:[
          { v:'long straight',   l:'Long Straight',   s:_hs(`${S_LNG}${CROWN}`)},
          { v:'long wavy',       l:'Long Wavy',        s:_hs(`${W_LNG}${CROWN}`)},
          { v:'long curly',      l:'Long Curly',       s:_hs(`${WC_LNG}${CROWN}`)},
          { v:'beach waves',     l:'Beach Waves',      s:_hs(`<path d="M7,14 Q3,23 7,31 Q3,38 6,43" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,23 31,31 Q35,38 32,43" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/>${CROWN_W}`)},
          { v:'cascading curls', l:'Cascading Curls',  s:_hs(`<path d="M7,14 Q3,18 7,23 Q3,29 7,35 Q3,41 7,44" stroke="${HC}" stroke-width="6" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,18 31,23 Q35,29 31,35 Q35,41 31,44" stroke="${HC}" stroke-width="6" fill="none" stroke-linecap="round"/>${CROWN_W}`)},
          { v:'sleek straight',  l:'Sleek Straight',   s:_hs(`${S_LNG}<ellipse cx="19" cy="14" rx="13" ry="7" fill="${HC}"/>`)},
          { v:'layered long',    l:'Layered Long',     s:_hs(`${S_LNG}${CROWN}<path d="M6,31 L11,32" stroke="#7a6040" stroke-width="1.5"/><path d="M32,31 L27,32" stroke="#7a6040" stroke-width="1.5"/>`)},
          { v:'mermaid waves',   l:'Mermaid',          s:_hs(`<path d="M7,14 Q3,23 7,31 Q3,38 6,44" stroke="${HC}" stroke-width="8" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,23 31,31 Q35,38 32,44" stroke="${HC}" stroke-width="8" fill="none" stroke-linecap="round"/>${CROWN_W}`)},
        ]},
        { sec:'🪢 Updo & Specialty', items:[
          { v:'high bun',         l:'High Bun',       s:_hs(`<ellipse cx="19" cy="7" rx="6" ry="5" fill="${HC}"/><ellipse cx="19" cy="17" rx="11" ry="6" fill="${HC}"/>`)},
          { v:'low bun',          l:'Low Bun',        s:_hs(`<ellipse cx="19" cy="36" rx="6" ry="5" fill="${HC}"/><rect x="5" y="14" width="5" height="20" rx="2" fill="${HC}"/><rect x="28" y="14" width="5" height="20" rx="2" fill="${HC}"/><ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/>`)},
          { v:'top knot',         l:'Top Knot',       s:_hs(`<ellipse cx="19" cy="5" rx="8" ry="7" fill="${HC}"/><ellipse cx="19" cy="17" rx="10" ry="6" fill="${HC}"/>`)},
          { v:'high ponytail',    l:'High Pony',      s:_hs(`<ellipse cx="19" cy="17" rx="11" ry="7" fill="${HC}"/><rect x="17" y="22" width="4" height="18" rx="2" fill="${HC}"/>`)},
          { v:'low ponytail',     l:'Low Pony',       s:_hs(`${CROWN}<rect x="17" y="34" width="4" height="12" rx="2" fill="${HC}"/>`)},
          { v:'side ponytail',    l:'Side Pony',      s:_hs(`${CROWN}<path d="M28,22 Q36,20 37,30" stroke="${HC}" stroke-width="5" fill="none" stroke-linecap="round"/>`)},
          { v:'braids',           l:'Braids',         s:_hs(`<ellipse cx="19" cy="15" rx="12" ry="7" fill="${HC}"/><rect x="7" y="14" width="5" height="14" rx="2" fill="${HC}"/><rect x="26" y="14" width="5" height="14" rx="2" fill="${HC}"/><rect x="12" y="35" width="5" height="9" rx="2" fill="${HC}"/><rect x="21" y="35" width="5" height="9" rx="2" fill="${HC}"/>`)},
          { v:'box braids',       l:'Box Braids',     s:_hs(`<ellipse cx="19" cy="14" rx="13" ry="8" fill="${HC}"/><rect x="9" y="23" width="4" height="20" rx="2" fill="${HC}"/><rect x="15" y="21" width="4" height="22" rx="2" fill="${HC}"/><rect x="23" y="21" width="4" height="22" rx="2" fill="${HC}"/><rect x="28" y="23" width="4" height="20" rx="2" fill="${HC}"/>`)},
          { v:'cornrows',         l:'Cornrows',       s:_hs(`${CROWN}<line x1="12" y1="9" x2="12" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="16" y1="8" x2="16" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="20" y1="8" x2="20" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="24" y1="8" x2="24" y2="22" stroke="#d4a574" stroke-width="1.5"/>`)},
          { v:'space buns',       l:'Space Buns',     s:_hs(`<ellipse cx="10" cy="13" rx="6" ry="5" fill="${HC}"/><ellipse cx="28" cy="13" rx="6" ry="5" fill="${HC}"/><ellipse cx="19" cy="18" rx="9" ry="5" fill="${HC}"/>`)},
          { v:'half up half down',l:'Half Up/Down',   s:_hs(`${S_SHR}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/><ellipse cx="19" cy="19" rx="7" ry="5" fill="${HC}"/>`)},
          { v:'afro',             l:'Afro',           s:_hs(`<ellipse cx="19" cy="16" rx="16" ry="13" fill="${HC}"/>`)},
          { v:'natural coils',    l:'Nat. Coils',     s:_hs(`<ellipse cx="19" cy="16" rx="14" ry="11" fill="${HC}"/><circle cx="12" cy="17" r="3" fill="#6a5040"/><circle cx="19" cy="11" r="3" fill="#6a5040"/><circle cx="26" cy="17" r="3" fill="#6a5040"/>`)},
          { v:'twist braids',     l:'Twist Braids',   s:_hs(`${CROWN}<rect x="12" y="22" width="4" height="20" rx="2" fill="${HC}"/><rect x="22" y="22" width="4" height="20" rx="2" fill="${HC}"/><path d="M12,25 Q16,28 12,32 Q16,36 12,40" stroke="#7a6040" stroke-width="1.2" fill="none"/><path d="M22,25 Q26,28 22,32 Q26,36 22,40" stroke="#7a6040" stroke-width="1.2" fill="none"/>`)},
          { v:'goddess braids',   l:'Goddess Braids', s:_hs(`${CROWN}<rect x="10" y="22" width="5" height="22" rx="2.5" fill="${HC}"/><rect x="17" y="21" width="5" height="23" rx="2.5" fill="${HC}"/><rect x="24" y="22" width="5" height="22" rx="2.5" fill="${HC}"/>`)},
          { v:'micro braids',     l:'Micro Braids',   s:_hs(`${CROWN}<rect x="9" y="23" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="13" y="22" width="3" height="20" rx="1.5" fill="${HC}"/><rect x="17" y="22" width="3" height="21" rx="1.5" fill="${HC}"/><rect x="21" y="22" width="3" height="21" rx="1.5" fill="${HC}"/><rect x="25" y="22" width="3" height="20" rx="1.5" fill="${HC}"/><rect x="29" y="23" width="3" height="19" rx="1.5" fill="${HC}"/>`)},
          { v:'dreadlocks',       l:'Locs',           s:_hs(`${CROWN}<rect x="9" y="25" width="3" height="17" rx="1.5" fill="${HC}"/><rect x="14" y="24" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="21" y="24" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="26" y="25" width="3" height="17" rx="1.5" fill="${HC}"/>`)},
          { v:'french twist',     l:'French Twist',   s:_hs(`${CROWN}<rect x="26" y="14" width="5" height="15" rx="2.5" fill="${HC}"/><ellipse cx="28" cy="12" rx="4" ry="3" fill="${HC}"/>`)},
          { v:'bantu knots',      l:'Bantu Knots',    s:_hs(`<ellipse cx="19" cy="18" rx="11" ry="7" fill="${HC}"/><circle cx="14" cy="15" r="3.5" fill="#6a4a30"/><circle cx="24" cy="15" r="3.5" fill="#6a4a30"/><circle cx="19" cy="11" r="3.5" fill="#6a4a30"/>`)},
          { v:'chignon',          l:'Chignon',        s:_hs(`<ellipse cx="19" cy="14" rx="11" ry="7" fill="${HC}"/><ellipse cx="19" cy="18" rx="9" ry="5" fill="#6a5040"/>`)},
          { v:'afro puff',        l:'Afro Puff',      s:_hs(`<ellipse cx="19" cy="5" rx="8" ry="7" fill="${HC}"/><ellipse cx="19" cy="19" rx="12" ry="8" fill="${HC}"/>`)},
        ]},
      ],
      male: [
        { sec:null, items:[{ v:'auto', l:'Auto', s:AUTO_S }]},
        { sec:'✂️ Short', items:[
          { v:'buzz cut',    l:'Buzz Cut',   s:_hs(`<path d="M9,27 Q9,16 19,16 Q29,16 29,27" fill="${HC}"/>`)},
          { v:'crew cut',    l:'Crew Cut',   s:_hs(`${CROWN}<rect x="9" y="16" width="20" height="7" fill="${HC}"/>`)},
          { v:'high fade',   l:'High Fade',  s:_hs(`<rect x="12" y="14" width="14" height="13" rx="2" fill="${HC}"/>`)},
          { v:'mid fade',    l:'Mid Fade',   s:_hs(`<rect x="10" y="15" width="18" height="12" rx="2" fill="${HC}"/><path d="M9,28 Q9,26 10,25" stroke="${HC}" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M29,28 Q29,26 28,25" stroke="${HC}" stroke-width="2" fill="none" stroke-linecap="round"/>`)},
          { v:'low fade',    l:'Low Fade',   s:_hs(`${CROWN}<path d="M9,27 Q9,24 10,23" stroke="${HC}" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M29,27 Q29,24 28,23" stroke="${HC}" stroke-width="3" fill="none" stroke-linecap="round"/>`)},
          { v:'caesar cut',  l:'Caesar Cut', s:_hs(`${CROWN}<rect x="7" y="20" width="24" height="4" fill="${HC}"/>`)},
          { v:'shaved head', l:'Shaved',     s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="3" fill="${HC}" opacity="0.7"/>`)},
          { v:'1mm shave',   l:'1mm Shave',  s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="2" fill="${HC}" opacity="0.35"/>`)},
          { v:'bald',        l:'Bald',       s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="1.5" fill="#d4a574" opacity="0.15"/>`)},
          { v:'flat top',    l:'Flat Top',   s:_hs(`<rect x="9" y="15" width="20" height="9" rx="1" fill="${HC}"/><rect x="7" y="15" width="3" height="9" fill="${HC}"/><rect x="28" y="15" width="3" height="9" fill="${HC}"/>`)},
          { v:'butch cut',   l:'Butch Cut',  s:_hs(`<ellipse cx="19" cy="19" rx="10" ry="5" fill="${HC}"/>`)},
          { v:'induction',   l:'Induction',  s:_hs(`<ellipse cx="19" cy="17" rx="9" ry="2" fill="${HC}" opacity="0.5"/>`)},
        ]},
        { sec:'💈 Medium', items:[
          { v:'short back and sides', l:'Short Sides',  s:_hs(`<rect x="9" y="16" width="20" height="11" rx="3" fill="${HC}"/>`)},
          { v:'undercut',             l:'Undercut',     s:_hs(`<path d="M9,24 L9,18 Q19,13 29,18 L29,24 L25,22 L19,26 L13,22 Z" fill="${HC}"/>`)},
          { v:'textured crop',        l:'Textured Crop',s:_hs(`${CROWN}<path d="M12,12 Q14,8 16,12" stroke="${HC}" stroke-width="2.5" fill="none" stroke-linecap="round"/><path d="M20,10 Q22,7 24,10" stroke="${HC}" stroke-width="2.5" fill="none" stroke-linecap="round"/>`)},
          { v:'side part',            l:'Side Part',    s:_hs(`<path d="M9,24 L9,17 Q12,13 29,16 L29,23 Z" fill="${HC}"/><line x1="12" y1="13" x2="12" y2="24" stroke="#d4a574" stroke-width="1.5"/>`)},
          { v:'french crop m',        l:'French Crop',  s:_hs(`${CROWN}<rect x="7" y="20" width="24" height="4" fill="${HC}"/>`)},
          { v:'quiff',                l:'Quiff',        s:_hs(`<ellipse cx="19" cy="22" rx="9" ry="6" fill="${HC}"/><path d="M16,16 C16,12 22,10 22,15" stroke="${HC}" stroke-width="3" fill="none" stroke-linecap="round"/>`)},
          { v:'pompadour',            l:'Pompadour',    s:_hs(`<path d="M12,24 C11,14 15,7 19,6 C23,7 27,14 26,24 Z" fill="${HC}"/>`)},
          { v:'slicked back',         l:'Slicked Back', s:_hs(`<path d="M9,24 C8,14 14,10 29,13 C22,15 16,18 13,24 Z" fill="${HC}"/>`)},
          { v:'faux hawk',            l:'Faux Hawk',    s:_hs(`<path d="M12,24 C11,16 16,11 19,10 C22,11 27,16 26,24 Z" fill="${HC}"/><rect x="9" y="20" width="4" height="8" rx="2" fill="${HC}" opacity="0.3"/><rect x="25" y="20" width="4" height="8" rx="2" fill="${HC}" opacity="0.3"/>`)},
          { v:'ivy league',           l:'Ivy League',   s:_hs(`${S_CHN}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/><line x1="12" y1="9" x2="12" y2="20" stroke="#d4a574" stroke-width="1.5"/>`)},
          { v:'mohawk',               l:'Mohawk',       s:_hs(`<path d="M15,24 C14,13 17,8 19,7 C21,8 24,13 23,24 Z" fill="${HC}"/>`)},
        ]},
        { sec:'🌊 Long', items:[
          { v:'shoulder length',  l:'Shoulder',      s:_hs(`${S_SHR}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/>`)},
          { v:'curtains',         l:'Curtains',      s:_hs(`${S_SHR}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/><line x1="19" y1="9" x2="19" y2="21" stroke="#d4a574" stroke-width="1.5"/>`)},
          { v:'flow',             l:'Flow',          s:_hs(`${W_LNG}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/>`)},
          { v:'surfer hair',      l:'Surfer',        s:_hs(`<path d="M7,14 Q3,23 6,31 Q2,38 5,43" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M31,14 Q35,23 32,31 Q36,38 33,43" stroke="${HC}" stroke-width="7" fill="none" stroke-linecap="round"/>${CROWN_W}`)},
          { v:'slicked back long',l:'Slicked Long',  s:_hs(`${S_SHR}<ellipse cx="19" cy="14" rx="12" ry="7" fill="${HC}"/><path d="M10,16 Q19,12 28,16" stroke="#7a6040" stroke-width="1.5" fill="none"/>`)},
          { v:'rocker hair',      l:'Rocker',        s:_hs(`${S_LNG}${CROWN}`)},
        ]},
        { sec:'🪢 Other', items:[
          { v:'man bun',     l:'Man Bun',      s:_hs(`<ellipse cx="19" cy="7" rx="5" ry="4" fill="${HC}"/><ellipse cx="19" cy="20" rx="10" ry="7" fill="${HC}"/>`)},
          { v:'dreadlocks',  l:'Locs',         s:_hs(`${CROWN}<rect x="9" y="25" width="3" height="17" rx="1.5" fill="${HC}"/><rect x="14" y="24" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="21" y="24" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="26" y="25" width="3" height="17" rx="1.5" fill="${HC}"/>`)},
          { v:'cornrows m',  l:'Cornrows',     s:_hs(`${CROWN}<line x1="12" y1="9" x2="12" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="16" y1="8" x2="16" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="20" y1="8" x2="20" y2="22" stroke="#d4a574" stroke-width="1.5"/><line x1="24" y1="8" x2="24" y2="22" stroke="#d4a574" stroke-width="1.5"/>`)},
          { v:'afro m',      l:'Afro',         s:_hs(`<ellipse cx="19" cy="16" rx="16" ry="13" fill="${HC}"/>`)},
          { v:'short afro m',l:'Short Afro',   s:_hs(`<ellipse cx="19" cy="17" rx="13" ry="9" fill="${HC}"/>`)},
          { v:'braids m',    l:'Braids',       s:_hs(`${CROWN}<rect x="13" y="23" width="5" height="18" rx="2.5" fill="${HC}"/><rect x="20" y="23" width="5" height="18" rx="2.5" fill="${HC}"/>`)},
          { v:'twist braids m', l:'Twist Braids', s:_hs(`${CROWN}<rect x="13" y="23" width="4" height="19" rx="2" fill="${HC}"/><rect x="21" y="23" width="4" height="19" rx="2" fill="${HC}"/><path d="M13,27 Q17,30 13,34 Q17,38 13,42" stroke="#7a6040" stroke-width="1.2" fill="none"/><path d="M21,27 Q25,30 21,34 Q25,38 21,42" stroke="#7a6040" stroke-width="1.2" fill="none"/>`)},
          { v:'micro braids m', l:'Micro Braids', s:_hs(`${CROWN}<rect x="10" y="23" width="3" height="19" rx="1.5" fill="${HC}"/><rect x="15" y="22" width="3" height="20" rx="1.5" fill="${HC}"/><rect x="20" y="22" width="3" height="21" rx="1.5" fill="${HC}"/><rect x="25" y="22" width="3" height="20" rx="1.5" fill="${HC}"/><rect x="30" y="23" width="3" height="19" rx="1.5" fill="${HC}"/>`)},
        ]},
      ]
    };

    function _stBuildHairModal(gender) {
      const current = (document.getElementById('st-hair-style') || {}).value || 'auto';
      const data = window._stHairData[gender === 'male' ? 'male' : 'female'];
      let html = '';
      data.forEach(sec => {
        const isAuto = !sec.sec;
        if (sec.sec) {
          html += `<div style="font-size:0.77rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:0.06em;margin:10px 0 6px;padding-bottom:4px;border-bottom:1px solid var(--border)">${sec.sec}</div>`;
        }
        if (isAuto) {
          const it = sec.items[0];
          const sel = current === it.v;
          html += `<button type="button" onclick="stSelectHairStyle('auto','Auto (AI chooses)',null)"
            style="display:flex;align-items:center;gap:12px;width:100%;background:${sel ? 'rgba(167,139,250,0.2)' : 'var(--surface2)'};border:${sel ? '2px solid var(--accent)' : '1px solid var(--border)'};border-radius:10px;padding:10px 14px;cursor:pointer;margin-bottom:10px;text-align:left">
            <span style="font-size:2rem;flex-shrink:0">✨</span>
            <div><div style="font-weight:600;font-size:0.9rem;color:var(--text)">Auto</div>
            <div style="font-size:0.74rem;color:var(--muted)">AI picks the perfect style for your character</div></div>
            ${sel ? '<span style="margin-left:auto;color:var(--accent);font-size:1.2rem">✓</span>' : ''}
          </button>`;
        } else {
          html += `<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:5px;margin-bottom:6px">`;
          sec.items.forEach(it => {
            const sel = current === it.v;
            const vesc = it.v.replace(/'/g,"\\'");
            const lesc = it.l.replace(/'/g,"\\'");
            html += `<button type="button" class="st-hair-card" data-val="${it.v}"
              onclick="stSelectHairStyle('${vesc}','${lesc}',this)"
              style="background:${sel ? 'rgba(167,139,250,0.15)' : 'var(--surface2)'};border:${sel ? '2px solid var(--accent)' : '1px solid var(--border)'};border-radius:7px;padding:5px 3px;cursor:pointer;text-align:center;font-size:0.63rem;color:var(--text);line-height:1.3">${it.s}${it.l}</button>`;
          });
          html += `</div>`;
        }
      });
      const body = document.getElementById('st-hair-modal-body');
      if (body) body.innerHTML = html;
    }

    window.stOpenHairModal = function() {
      const gender = (document.getElementById('st-gender') || {}).value || 'female';
      _stBuildHairModal(gender);
      const m = document.getElementById('st-hair-modal');
      if (m) m.style.display = 'block';
    };

    window.stCloseHairModal = function() {
      const m = document.getElementById('st-hair-modal');
      if (m) m.style.display = 'none';
    };

    window.stHairModalBg = function(e) {
      if (e.target && e.target.id === 'st-hair-modal') stCloseHairModal();
    };

    window.stSelectHairStyle = function(val, label, el) {
      document.getElementById('st-hair-style').value = val;
      const labelEl = document.getElementById('st-hair-label');
      if (val === 'auto') {
        if (labelEl) labelEl.textContent = 'Auto';
      } else if (labelEl) {
        labelEl.textContent = label;
      }
      if (!window._stApplyingPhotoAnalysis) window._stMarkPhotoFieldEdited('hair_style');
      stCloseHairModal();
    };

    window.stGenderChange = function() {
      const gender = document.getElementById('st-gender').value;
      document.getElementById('st-hair-style').value = 'auto';
      const labelEl = document.getElementById('st-hair-label');
      if (labelEl) labelEl.textContent = 'Auto';
      // Show facial hair only for male
      const fhWrap = document.getElementById('st-facial-hair-wrap');
      if (fhWrap) fhWrap.style.display = gender === 'male' ? 'block' : 'none';
      // Reset facial hair when switching to female
      if (gender !== 'male') {
        const fhInp = document.getElementById('st-facial-hair');
        const fhLbl = document.getElementById('st-facial-label');
        const fhIco = document.getElementById('st-facial-icon');
        if (fhInp) fhInp.value = 'none';
        if (fhLbl) fhLbl.textContent = 'None';
        if (fhIco) fhIco.textContent = '🪒';
      }
      if (typeof _filterVoicesByGenderAge === 'function') _filterVoicesByGenderAge();
    };

  })();

  // Wizard state
  window._stCharId        = null;
  window._stTriggerToken  = null;
  window._stLoraReady     = false;
  window._stCameraMode    = 'automatic';
  window._stLoraPoller    = null;
  window._stCurrentStep   = 1;

  // ── Camera angle selection ────────────────────────────────────────────────────
  window.stSelectCam = function(mode, el) {
    document.querySelectorAll('.st-cam-option').forEach(o => {
      o.style.border     = '1px solid var(--border)';
      o.style.background = 'var(--surface2)';
    });
    el.style.border     = '2px solid var(--accent)';
    el.style.background = 'rgba(124,111,247,0.12)';
    window._stCameraMode = mode;
  };

  // ── Voice radio change ────────────────────────────────────────────────────────
  window.stVoiceChange = function() {
    const charSel      = document.getElementById('st-voice-char');
    const wrap         = document.getElementById('st-voice-type-wrap');
    const narratorWrap = document.getElementById('st-narrator-voice-wrap');
    const isChar = charSel && charSel.checked;
    if (wrap)         wrap.style.display         = isChar ? 'block' : 'none';
    if (narratorWrap) narratorWrap.style.display  = isChar ? 'none'  : 'block';
    if (window._stCurrentStep === 2 || (wrap && wrap.offsetParent)) {
      _initStorytellerVoicePickers().then(() => {
        if (typeof _filterVoicesByGenderAge === 'function') _filterVoicesByGenderAge();
      });
    }
  };

  // ── Step navigation ───────────────────────────────────────────────────────────
  window.stNextStep = function(currentStep, _force) {
    // Block advancing from Step 1 → 2 while character is still generating
    if (currentStep === 1 && window._stCharGenerating && !_force) {
      // Show a fun message instead of a technical error
      const msgEl = document.getElementById('st-fun-msg');
      if (msgEl) {
        const _waiting = ['The monkeys are still painting…', 'Characters take time to sculpt.', 'Good things take a moment…'];
        msgEl.textContent = _waiting[Math.floor(Math.random() * _waiting.length)];
        setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 3000);
      }
      return;
    }
    // Character-only mode: open the preview modal directly.
    if (currentStep === 1 && window._stCharOnlyMode) {
      stOpenPreviewModal(window._stCharId);
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
      return;
    }
    // Hide the previous step when advancing
    const prev = document.getElementById(`st-step${currentStep}`);
    if (prev) prev.style.display = 'none';
    const next = document.getElementById(`st-step${currentStep + 1}`);
    if (next) {
      next.style.display = 'block';
      next.scrollIntoView({ behavior: 'smooth', block: 'start' });
      window._stCurrentStep = currentStep + 1;
      // When entering step 2, inject the character preview and filter voices by gender+age
      if (currentStep + 1 === 2) {
        _injectCharPreviewInStep2();
        _initStorytellerVoicePickers().then(() => {
          _filterVoicesByGenderAge();
          stVoiceChange();
        });
      }
    }
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  };

  // ── Generate Character (Step 1) ───────────────────────────────────────────────
  // Photo upload helpers + vision auto-fill
  window._stUploadedFiles = [];
  window._stPhotoAnalysis = null;
  window._stPhotoLockedFields = new Set();
  window._stPhotoDetectedKeys = new Set();
  window._stApplyingPhotoAnalysis = false;

  window._stFieldKeyForEl = function(el) {
    if (!el || !el.id) return '';
    const map = {
      'st-gender': 'gender', 'st-hair': 'hair_color', 'st-eyes': 'eye_color',
      'st-skin': 'skin_tone', 'st-age': 'age', 'st-height': 'height',
      'st-muscle-mass': 'muscle_mass', 'st-facial-hair': 'facial_hair',
      'st-hair-style': 'hair_style', 'st-char-style': 'style',
      'st-face-shape': 'face_shape', 'st-eye-shape': 'eye_shape',
      'st-eyebrow-style': 'eyebrow_style', 'st-nose-shape': 'nose_shape',
      'st-lip-shape': 'lip_shape', 'st-hair-length': 'hair_length',
      'st-hair-texture': 'hair_texture', 'st-distinctive-marks': 'distinctive_marks',
      'st-ethnic-heritage': 'ethnic_heritage', 'st-default-clothing': 'default_clothing',
      'st-accessories': 'accessories', 'st-default-expression': 'default_expression',
      'st-char-name': 'name',
    };
    return map[el.id] || el.id.replace(/^st-/, '').replace(/-/g, '_');
  };

  window._stMarkPhotoFieldEdited = function(elOrKey) {
    const key = typeof elOrKey === 'string' ? elOrKey : window._stFieldKeyForEl(elOrKey);
    if (!key) return;
    window._stPhotoLockedFields.add(key);
    window._stPhotoDetectedKeys.delete(key);
    const el = typeof elOrKey === 'string' ? null : elOrKey;
    if (el) el.classList.remove('st-photo-detected');
    document.querySelectorAll('[data-photo-badge="' + key + '"]').forEach(b => b.remove());
  };

  window._stMarkPhotoFieldDetected = function(key, el) {
    if (!key || window._stPhotoLockedFields.has(key)) return;
    window._stPhotoDetectedKeys.add(key);
    if (el) el.classList.add('st-photo-detected');
    const label = el && el.closest('label');
    if (label && !label.querySelector('[data-photo-badge="' + key + '"]')) {
      const badge = document.createElement('span');
      badge.className = 'st-photo-detected-badge';
      badge.dataset.photoBadge = key;
      badge.textContent = 'from photo';
      const anchor = label.querySelector('select,input,textarea,div[id="st-skin-swatches"]');
      if (anchor) label.insertBefore(badge, anchor);
      else label.appendChild(badge);
    }
  };

  window._stSetPhotoAnalysisStatus = function(text, kind) {
    const el = document.getElementById('st-photo-analysis-status');
    if (!el) return;
    el.textContent = text || '';
    el.className = kind || '';
  };

  window._stApplyPhotoAnalysisFields = function(fields) {
    if (!fields || typeof fields !== 'object') return;
    window._stApplyingPhotoAnalysis = true;
    try {
      const setSelect = (id, val, key) => {
        if (val == null || val === '') return;
        if (window._stPhotoLockedFields.has(key)) return;
        const el = document.getElementById(id);
        if (!el) return;
        const v = String(val);
        if (el.tagName === 'SELECT') {
          const opt = Array.from(el.options).find(o => o.value === v);
          if (opt) { el.value = v; window._stMarkPhotoFieldDetected(key, el); }
        } else {
          el.value = v;
          window._stMarkPhotoFieldDetected(key, el);
        }
      };
      setSelect('st-gender', fields.gender, 'gender');
      if (fields.gender && typeof stGenderChange === 'function') stGenderChange();
      setSelect('st-hair', fields.hair_color, 'hair_color');
      setSelect('st-eyes', fields.eye_color, 'eye_color');
      setSelect('st-height', fields.height, 'height');
      if (fields.age != null && !window._stPhotoLockedFields.has('age')) {
        const ageEl = document.getElementById('st-age');
        if (ageEl) { ageEl.value = fields.age; window._stMarkPhotoFieldDetected('age', ageEl); }
      }
      if (fields.skin_tone && !window._stPhotoLockedFields.has('skin_tone')) {
        const tone = String(fields.skin_tone);
        const btn = document.querySelector('#st-skin-swatches button[onclick*="' + tone + '"]');
        if (btn && typeof stPickSkin === 'function') {
          stPickSkin(btn, tone);
          window._stMarkPhotoFieldDetected('skin_tone', document.getElementById('st-skin-swatches'));
        }
      }
      if (fields.muscle_mass != null && !window._stPhotoLockedFields.has('muscle_mass')) {
        const sl = document.getElementById('st-muscle-mass');
        if (sl) {
          sl.value = fields.muscle_mass;
          if (typeof stMuscleMassChange === 'function') stMuscleMassChange();
          window._stMarkPhotoFieldDetected('muscle_mass', sl);
        }
      }
      if (fields.facial_hair && !window._stPhotoLockedFields.has('facial_hair')) {
        const fh = String(fields.facial_hair);
        if (typeof stSelectFacialHair === 'function') {
          stSelectFacialHair(fh, fh.replace(/\b\w/g, c => c.toUpperCase()));
          window._stMarkPhotoFieldDetected('facial_hair', document.getElementById('st-facial-trigger'));
        }
      }
      if (fields.hair_style && !window._stPhotoLockedFields.has('hair_style')) {
        const hs = String(fields.hair_style);
        if (typeof stSelectHairStyle === 'function') {
          const label = hs === 'auto' ? 'Auto' : hs.replace(/\b\w/g, c => c.toUpperCase());
          stSelectHairStyle(hs, label, null);
          window._stMarkPhotoFieldDetected('hair_style', document.getElementById('st-hair-trigger'));
        }
      }
      [
        ['st-face-shape', 'face_shape'], ['st-eye-shape', 'eye_shape'],
        ['st-eyebrow-style', 'eyebrow_style'], ['st-nose-shape', 'nose_shape'],
        ['st-lip-shape', 'lip_shape'], ['st-hair-length', 'hair_length'],
        ['st-hair-texture', 'hair_texture'], ['st-default-expression', 'default_expression'],
      ].forEach(([id, key]) => setSelect(id, fields[key], key));
      [
        ['st-distinctive-marks', 'distinctive_marks'],
        ['st-ethnic-heritage', 'ethnic_heritage'],
        ['st-default-clothing', 'default_clothing'],
        ['st-accessories', 'accessories'],
      ].forEach(([id, key]) => {
        if (!fields[key] || window._stPhotoLockedFields.has(key)) return;
        const el = document.getElementById(id);
        if (!el) return;
        el.value = fields[key];
        window._stMarkPhotoFieldDetected(key, el);
      });
    } finally {
      window._stApplyingPhotoAnalysis = false;
    }
  };

  // Photo vision runs only on Generate (server-side during generate-character).
  window._stClearPhotoAnalysisUi = function() {
    window._stPhotoAnalysis = null;
    window._stSetPhotoAnalysisStatus('', '');
  };

  window._stInitPhotoFieldTracking = function() {
    const form = document.getElementById('st-step1-form');
    if (!form || form.dataset.photoTrackInit) return;
    form.dataset.photoTrackInit = '1';
    form.querySelectorAll('select,input,textarea').forEach(el => {
      const mark = () => {
        if (window._stApplyingPhotoAnalysis) return;
        window._stMarkPhotoFieldEdited(el);
      };
      el.addEventListener('change', mark);
      el.addEventListener('input', mark);
    });
    document.querySelectorAll('#st-skin-swatches button').forEach(btn => {
      btn.addEventListener('click', () => {
        if (window._stApplyingPhotoAnalysis) return;
        window._stMarkPhotoFieldEdited('skin_tone');
      });
    });
  };

  window.stHandlePhotoFiles = function(files) {
    const MAX = 15;
    for (const f of files) {
      if (window._stUploadedFiles.length >= MAX) break;
      if (!f.type.startsWith('image/')) continue;
      window._stUploadedFiles.push(f);
      const thumb = document.createElement('div');
      thumb.style.cssText = 'width:56px;height:56px;border-radius:6px;overflow:hidden;position:relative;border:1px solid var(--border)';
      const img = document.createElement('img');
      img.style.cssText = 'width:100%;height:100%;object-fit:cover';
      img.src = URL.createObjectURL(f);
      const rm = document.createElement('button');
      rm.textContent = '×';
      rm.style.cssText = 'position:absolute;top:0;right:0;background:rgba(0,0,0,0.6);color:#fff;border:none;border-radius:0 6px 0 4px;cursor:pointer;font-size:0.75rem;padding:1px 4px;line-height:1';
      // 2026-07-31: resolve the file's position at CLICK time. The old code
      // captured the append-time index, so after any earlier removal every
      // later × spliced the wrong entry (or nothing), and the uploaded file
      // list silently stopped matching the thumbnails on screen.
      rm.onclick = () => {
        const i = window._stUploadedFiles.indexOf(f);
        if (i >= 0) window._stUploadedFiles.splice(i, 1);
        thumb.remove();
        stUpdatePhotoCount();
        if (!window._stUploadedFiles.length) {
          window._stClearPhotoAnalysisUi();
        }
      };
      thumb.appendChild(img); thumb.appendChild(rm);
      document.getElementById('st-photo-thumbs').appendChild(thumb);
    }
    stUpdatePhotoCount();
    if (window._stUploadedFiles.length) {
      window._stSetPhotoAnalysisStatus(
        'Photo ready — traits are analyzed when you click Generate Character.',
        ''
      );
    }
  };

  window.stHandlePhotoDrop = function(e) {
    e.preventDefault();
    document.getElementById('st-photo-dropzone').style.borderColor = 'var(--border)';
    stHandlePhotoFiles(e.dataTransfer.files);
  };

  window.stUpdatePhotoCount = function() {
    const n = window._stUploadedFiles.length;
    const el = document.getElementById('st-photo-count');
    if (el) el.textContent = n > 0 ? `${n} photo${n>1?'s':''} attached` : '';
    const dz = document.getElementById('st-photo-dropzone');
    if (dz) dz.style.borderColor = n > 0 ? 'var(--accent)' : 'var(--border)';
  };

  // Existing character library (storyteller + shared loader)
  window._stSelectedExistingChar = null;
  window._vidSelectedChar = null;
  window._crSelectedCreature = null;

  function _sortCreatureLibrary(creatures) {
    return creatures.slice().sort((a, b) => {
      const ta = (a.trained_at || '').localeCompare(b.trained_at || '');
      if (ta !== 0) return -ta;
      return (b.creature_id || '').localeCompare(a.creature_id || '');
    });
  }

  async function _fetchCreatureLibraryList() {
    const resp = await fetch('/api/creature/list-creatures?_=' + Date.now(), { cache: 'no-store' });
    const data = await resp.json();
    return _sortCreatureLibrary((data.creatures || []).filter(c => c.lora_ready));
  }

  function _renderCreatureLibraryCards(creatures, grid, onSelect, selectedCreatureId, options) {
    if (!grid) return;
    const opts = options || {};
    const silent = opts.silent === true;
    if (!silent) grid.innerHTML = '';
    const existing = new Set(
      silent ? Array.from(grid.querySelectorAll('[data-creature-id]')).map(el => el.dataset.creatureId) : []
    );
    creatures.forEach(cr => {
      if (silent && existing.has(cr.creature_id)) return;
      const card = document.createElement('div');
      card.style.cssText = 'cursor:pointer;border-radius:8px;overflow:hidden;border:2px solid '
        + (selectedCreatureId === cr.creature_id ? 'var(--accent)' : 'var(--border)')
        + ';background:var(--surface2);text-align:center;transition:border-color 0.15s';
      card.dataset.creatureId = cr.creature_id;
      card.onclick = () => onSelect(cr, card);
      const img = document.createElement('div');
      if (cr.preview_url) {
        img.style.cssText = 'width:100%;aspect-ratio:1;background-size:cover;background-position:center';
        img.style.backgroundImage = `url('${cr.preview_url}')`;
      } else {
        img.style.cssText = 'width:100%;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:1.3rem;color:var(--muted)';
        img.innerHTML = '<span style="font-size:1.1rem">🐉</span>';
      }
      const label = document.createElement('div');
      label.style.cssText = 'font-size:0.7rem;padding:3px 4px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;justify-content:space-between;gap:2px';
      const nameSpan = document.createElement('span');
      nameSpan.style.cssText = 'overflow:hidden;text-overflow:ellipsis;flex:1';
      nameSpan.textContent = cr.library_label || cr.name || cr.creature_id.slice(0, 8);
      nameSpan.title = (cr.name || cr.description || cr.creature_id) + ' · LoRA trained';
      label.appendChild(nameSpan);
      if (cr.preview_url) {
        const dlBtn = document.createElement('a');
        dlBtn.href     = _previewDownloadHref(cr.preview_url);
        dlBtn.download = _creatureDownloadFilename(cr);
        dlBtn.title    = 'Download preview';
        dlBtn.style.cssText = 'flex-shrink:0;color:var(--accent);text-decoration:none;font-size:0.85rem;line-height:1;padding:1px 2px;opacity:0.7';
        dlBtn.textContent = '⬇';
        dlBtn.onclick = e => e.stopPropagation();
        label.appendChild(dlBtn);
      }
      card.appendChild(img);
      card.appendChild(label);
      if (silent) grid.insertBefore(card, grid.firstChild);
      else grid.appendChild(card);
    });
  }

  let _crCreatureLibraryLoadSeq = 0;

  window.crOpenCreatureLibrary = async function() {
    const panel = document.getElementById('creature-library-panel');
    const btn = document.getElementById('creature-library-toggle');
    if (panel) panel.style.display = 'block';
    if (btn) btn.textContent = 'Hide library';
    await crLoadCreatureLibrary();
  };

  window.crToggleCreatureLibrary = async function() {
    const panel = document.getElementById('creature-library-panel');
    const btn = document.getElementById('creature-library-toggle');
    if (!panel) return;
    if (panel.style.display === 'none') {
      panel.style.display = 'block';
      if (btn) btn.textContent = 'Hide library';
      await crLoadCreatureLibrary();
    } else {
      panel.style.display = 'none';
      if (btn) btn.textContent = 'Show library';
    }
  };

  window.crLoadCreatureLibrary = async function(options) {
    const opts = options || {};
    const silent = opts.silent === true;
    const loading = document.getElementById('creature-library-loading');
    const grid = document.getElementById('creature-library-grid');
    const empty = document.getElementById('creature-library-empty');
    const seq = ++_crCreatureLibraryLoadSeq;
    if (!silent) {
      if (loading) loading.style.display = 'block';
      if (grid) grid.innerHTML = '';
      if (empty) empty.style.display = 'none';
    }
    try {
      const creatures = await _fetchCreatureLibraryList();
      if (seq !== _crCreatureLibraryLoadSeq) return;
      if (!silent && loading) loading.style.display = 'none';
      if (!creatures.length) {
        if (!silent && empty) empty.style.display = 'block';
        return;
      }
      if (empty) empty.style.display = 'none';
      _renderCreatureLibraryCards(creatures, grid, crSelectCreature,
        window._crSelectedCreature ? window._crSelectedCreature.creature_id : null,
        { silent });
    } catch (e) {
      if (!silent && loading) loading.textContent = 'Failed to load: ' + e.message;
    }
  };

  window.crSelectCreature = function(cr, card) {
    document.querySelectorAll('#creature-library-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    if (card) card.style.borderColor = 'var(--accent)';
    window._crSelectedCreature = cr;
    const info = document.getElementById('creature-selected-info');
    const name = document.getElementById('creature-selected-name');
    const trigger = document.getElementById('creature-selected-trigger');
    if (info) info.style.display = 'block';
    if (name) name.textContent = `${cr.library_label || cr.name || 'Creature'} · ${cr.creature_id}`;
    if (trigger) trigger.textContent = cr.trigger_token ? `Trigger: ${cr.trigger_token}` : '';
    const dlWrap = document.getElementById('creature-selected-download');
    if (dlWrap) {
      if (cr.preview_url) {
        dlWrap.style.display = 'block';
        dlWrap.innerHTML = '';
        const dlLink = document.createElement('a');
        dlLink.href = _previewDownloadHref(cr.preview_url);
        dlLink.download = _creatureDownloadFilename(cr);
        dlLink.textContent = '⬇ Download preview';
        dlLink.style.cssText = 'color:var(--accent);text-decoration:none;font-size:0.78rem';
        dlWrap.appendChild(dlLink);
      } else {
        dlWrap.style.display = 'none';
        dlWrap.innerHTML = '';
      }
    }
  };

  window.crClearSelectedCreature = function() {
    window._crSelectedCreature = null;
    document.querySelectorAll('#creature-library-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    const info = document.getElementById('creature-selected-info');
    if (info) info.style.display = 'none';
  };

  function _creatureDownloadFilename(cr) {
    const raw = (cr && (cr.name || cr.library_label)) || '';
    const slug = raw.trim().toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/[^a-z0-9_\-]+/g, '')
      .replace(/^_+|_+$/g, '');
    return (slug || (cr && cr.creature_id ? cr.creature_id.slice(0, 8) : 'creature')) + '.png';
  }

  function _previewDownloadHref(previewUrl) {
    if (!previewUrl) return '#';
    const u = new URL(previewUrl, window.location.origin);
    u.searchParams.set('download', '1');
    u.searchParams.delete('v');
    u.searchParams.delete('_');
    return u.toString();
  }

  function _charDownloadFilename(ch) {
    const raw = (ch && (ch.name || ch.library_label)) || '';
    const slug = raw.trim().toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/[^a-z0-9_\-]+/g, '')
      .replace(/^_+|_+$/g, '');
    return (slug || (ch && ch.char_id ? ch.char_id.slice(0, 8) : 'character')) + '.png';
  }

  function _charPreviewDownloadHref(previewUrl) {
    return _previewDownloadHref(previewUrl);
  }

  function _contactSheetDownloadFilename(sh) {
    const raw = (sh && (sh.name || sh.library_label))
      || (document.getElementById('st-char-name')?.value || '')
      || (window._stCharParams && window._stCharParams.name)
      || '';
    const slug = raw.trim().toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/[^a-z0-9_\-]+/g, '')
      .replace(/^_+|_+$/g, '');
    const cid = (sh && sh.char_id) || window._stCharId || '';
    return (slug ? slug + '_contact_sheet' : 'contact_sheet_' + (cid.slice(0, 8) || 'preview')) + '.png';
  }

  function _contactSheetPreviewDownloadHref(sh) {
    const purl = (sh && (sh.contact_sheet_url || sh.preview_url)) || '';
    if (!purl) return '#';
    return _previewDownloadHref(purl);
  }

  window.stDownloadContactSheetPreview = function(e) {
    if (e) e.preventDefault();
    const img = document.getElementById('st-cs-preview-img');
    const cid = window._stCharId;
    if (!img || !img.src || img.src === window.location.href) return;
    try {
      const u = new URL(img.src, window.location.origin);
      u.searchParams.set('download', '1');
      u.searchParams.delete('v');
      u.searchParams.delete('_');
      const a = document.createElement('a');
      a.href = u.toString();
      a.download = _contactSheetDownloadFilename({ char_id: cid, name: window._stCharParams?.name });
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { try { document.body.removeChild(a); } catch (_e) {} }, 500);
    } catch (err) {
      if (cid) {
        window.open('/api/storyteller/contact-sheet/image/' + cid + '?download=1', '_blank');
      }
    }
  };

  // 2026-07-31: a character HAS a portrait as soon as the library hands us any
  // image URL for it — the contact sheet first, since that IS the canonical
  // portrait for every modern (multi-angle) character. The old
  // /preview_(flux|sdxl)/ test rejected contact-sheet URLs, which is what made
  // the grid mark real characters "generating…" and fire the preview sweep.
  function _charTileImageUrl(ch) {
    if (!ch) return '';
    return ch.contact_sheet_url || ch.preview_url || '';
  }
  function _charIsContactSheet(ch) {
    if (!ch) return false;
    if (ch.contact_sheet_url) return true;
    if (ch.creation_pipeline === 'multi_angle_contact_sheet') return true;
    if (ch.source === 'contact_sheet') return true;
    return /contact-sheet|contactsheet/.test(ch.preview_url || '');
  }

  // Full library rows (bible-derived identity) keyed by char_id. The
  // contact-sheet grid hands out records with no identity keys at all; this
  // lets a selection made there be resolved back to the real character.
  window._stCharLibraryById = window._stCharLibraryById || {};
  // Per-slot preview provenance from /api/storyteller/character-status/<id>,
  // when the server supplies it. Optional by design — older servers omit it.
  window._stPreviewProvenance = window._stPreviewProvenance || {};

  function _stCharRecordFor(charId) {
    if (!charId) return null;
    const sel = window._stSelectedCharRecord;
    if (sel && sel.char_id === charId) return sel;
    return (window._stCharLibraryById || {})[charId] || null;
  }

  function _stSlotLabel(slot) {
    if (slot.includes('sdxl_front')) return 'Body (SDXL)';
    if (slot.includes('flux_face'))  return 'Face (FLUX)';
    if (slot.includes('sdxl_face'))  return 'Face (SDXL)';
    if (slot.includes('flux_front')) return 'Preview (FLUX)';
    return slot;
  }

  // Ordered image candidates for a character:
  //   1. contact sheet (canonical portrait when one exists)
  //   2. preview slots, provenance-verified ones first
  //   3. any other library preview URL, then the Blender reference renders
  // 2026-07-31: replaces "guess the filename from the run's backend toggle",
  // which rendered whatever the preview sweep last wrote into that slot.
  function _stPreviewCandidates(charId, opts) {
    const o = opts || {};
    const rec = _stCharRecordFor(charId) || {};
    const prov = (o.prov && typeof o.prov === 'object')
      ? o.prov
      : ((window._stPreviewProvenance || {})[charId] || null);
    const out = [];
    const sheet = rec.contact_sheet_url
      || (/contact-sheet|contactsheet/.test(rec.preview_url || '') ? rec.preview_url : '');
    if (sheet) out.push({ url: sheet, kind: 'sheet', slot: '', loraUsed: null, label: 'Contact sheet' });

    const _lu = (slot) => {
      const e = prov && prov[slot];
      if (!e || typeof e !== 'object') return null;
      if (e.lora_used === true) return true;
      if (e.lora_used === false) return false;
      return null;
    };
    const slots = (typeof _charPreviewSlotNames === 'function')
      ? (_charPreviewSlotNames() || []) : ['preview_flux_front'];
    const verified = slots.filter(s => _lu(s) === true);
    const rest     = slots.filter(s => _lu(s) !== true);
    verified.concat(rest).forEach(s => out.push({
      url: `/api/storyteller/char-image/${charId}/${s}.png`,
      kind: 'slot', slot: s, loraUsed: _lu(s), label: _stSlotLabel(s),
    }));

    if (rec.preview_url && !sheet && !/preview_(flux|sdxl)/.test(rec.preview_url)) {
      out.push({ url: rec.preview_url, kind: 'other', slot: '', loraUsed: null, label: 'Preview' });
    }
    ['full_00_000deg', 'full_04_090deg', 'full_08_180deg', 'face_00_000deg'].forEach(b => out.push({
      url: `/api/storyteller/char-image/${charId}/${b}.png`,
      kind: 'blender', slot: b, loraUsed: false, label: b,
    }));
    return out;
  }

  function _renderCharLibraryCards(chars, grid, onSelect, selectedCharId, options) {
    if (!grid) return;
    chars = _filterCharsForModelFamily(chars);
    const opts = options || {};
    const silent = opts.silent === true;
    if (!silent) grid.innerHTML = '';
    const existing = new Set(
      silent ? Array.from(grid.querySelectorAll('[data-char-id]')).map(el => el.dataset.charId) : []
    );
    chars.forEach(ch => {
      if (silent && existing.has(ch.char_id)) return;
      const card = document.createElement('div');
      card.style.cssText = 'cursor:pointer;border-radius:8px;overflow:hidden;border:2px solid '
        + (selectedCharId === ch.char_id ? 'var(--accent)' : 'var(--border)')
        + ';background:var(--surface2);text-align:center;transition:border-color 0.15s';
      card.dataset.charId = ch.char_id;
      card.onclick = () => onSelect(ch, card);
      const img = document.createElement('div');
      const _purl = ch.preview_url || ch.contact_sheet_url;
      const _isCs = ch.creation_pipeline === 'multi_angle_contact_sheet' || ch.source === 'contact_sheet';
      if (_purl && (_isCs || /preview_(flux|sdxl)|contact-sheet|contactsheet/.test(_purl))) {
        img.style.cssText = 'width:100%;aspect-ratio:' + (_isCs ? '4/3' : '1')
          + ';background-size:cover;background-position:center top';
        img.style.backgroundImage = `url('${_purl}')`;
      } else {
        img.style.cssText = 'width:100%;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:1.3rem;color:var(--muted)';
        img.innerHTML = '<span style="font-size:1.1rem">🧑</span>';
      }
      const label = document.createElement('div');
      label.style.cssText = 'font-size:0.7rem;padding:3px 4px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
      const _cmfVid = (ch.model_family || (ch.lora_families && ch.lora_families[0]) || '').toUpperCase();
      const _csTag = _isCs ? ' · sheet' : '';
      label.textContent = (ch.library_label || _stLibraryLabel(ch.name) || ch.char_id.slice(0, 8))
        + (_cmfVid ? ' · ' + _cmfVid : '') + _csTag;
      label.title = (ch.name || ch.char_id) + ' · LoRA ' + (_cmfVid || 'trained') + (_isCs ? ' · contact sheet' : '');
      card.appendChild(img);
      card.appendChild(label);
      if (silent) grid.insertBefore(card, grid.firstChild);
      else grid.appendChild(card);
    });
  }

  let _charLibraryPollTimer = null;
  let _stCharLibraryLoadSeq = 0;
  let _vidCharLibraryLoadSeq = 0;
  let _charLibraryIds = new Set();

  function _stopPreviewPollTimer() {
    if (window._stPreviewPollTimer) {
      clearInterval(window._stPreviewPollTimer);
      window._stPreviewPollTimer = null;
    }
  }

  // 2026-07-31: hard-bounded. The old timer only cleared itself once EVERY
  // pending tile had been swapped, and its swap test (/preview_(sdxl|flux)_/)
  // can never match a contact-sheet character's preview_url — so one such
  // character in the grid meant this tab hammered the expensive list-chars
  // endpoint every 12s forever, panel open or not.
  const _PREVIEW_POLL_MAX_TICKS = 25;   // ~5 minutes
  function _startPreviewPollTimer() {
    if (window._stPreviewPollTimer) return;
    let _ticks = 0;
    window._stPreviewPollTimer = setInterval(async () => {
      _ticks++;
      if (_ticks > _PREVIEW_POLL_MAX_TICKS || !_charLibraryPanelsOpen()) {
        _stopPreviewPollTimer();
        return;
      }
      try {
        const _mfPoll = _getModelFamily();
        const r2 = await fetch('/api/storyteller/list-chars?model_family=' + encodeURIComponent(_mfPoll) + '&_=' + Date.now(), { cache: 'no-store' });
        const d2 = await r2.json();
        const byId = {};
        (d2.chars || []).forEach(c => { byId[c.char_id] = c; });
        let stillPending = 0;
        document.querySelectorAll('[data-pending-preview="true"]').forEach(el => {
          const cid = el.dataset.pendingCharId;
          const ch2 = byId[cid];
          const _u2 = _charTileImageUrl(ch2);
          if (_u2) {
            el.style.cssText = 'width:100%;aspect-ratio:' + (_charIsContactSheet(ch2) ? '4/3' : '1')
              + ';background-size:cover;background-position:center top';
            el.style.backgroundImage = `url('${_u2}')`;
            el.innerHTML = '';
            delete el.dataset.pendingPreview;
          } else {
            stillPending++;
          }
        });
        if (stillPending === 0) _stopPreviewPollTimer();
      } catch (_) {}
    }, 12000);
  }

  function _sortCharLibrary(chars) {
    return chars.slice().sort((a, b) => {
      const ta = (a.trained_at || '').localeCompare(b.trained_at || '');
      if (ta !== 0) return -ta;
      return (b.char_id || '').localeCompare(a.char_id || '');
    });
  }

  async function _fetchCharLibraryList() {
    const mf = _getModelFamily();
    const resp = await fetch(
      '/api/storyteller/list-chars?model_family=' + encodeURIComponent(mf) + '&_=' + Date.now(),
      { cache: 'no-store', credentials: 'same-origin' }
    );
    const ct = (resp.headers.get('content-type') || '').toLowerCase();
    const raw = await resp.text();
    if (!resp.ok) {
      const hint = raw.trimStart().startsWith('<')
        ? ' Server returned HTML instead of JSON — restart zero_public_server.py.'
        : '';
      throw new Error('Character library HTTP ' + resp.status + hint);
    }
    if (!ct.includes('json')) {
      throw new Error(
        'Character library returned non-JSON (' + (ct || 'unknown type') + '). Hard-refresh the page.'
      );
    }
    let data;
    try {
      data = JSON.parse(raw);
    } catch (parseErr) {
      throw new Error('Character library JSON parse failed: ' + parseErr.message);
    }
    // 2026-07-31: keep every row (pre-family-filter) so a selection made from a
    // library that carries no identity — the contact-sheet grid — can be
    // resolved back to the real, bible-derived character record.
    try {
      (data.chars || []).forEach(c => {
        if (c && c.char_id) window._stCharLibraryById[c.char_id] = c;
      });
    } catch (_e) {}
    return _sortCharLibrary(_filterCharsForModelFamily(data.chars || []));
  }

  function _charMatchesPipelineFamily(ch) {
    return _filterCharsForModelFamily([ch]).length > 0;
  }

  function _charLibraryPanelsOpen() {
    const st = document.getElementById('st-existing-chars-panel');
    const vid = document.getElementById('vid-char-library-panel');
    return (st && st.style.display !== 'none') || (vid && vid.style.display !== 'none');
  }

  async function _refreshCharLibraryPanels(silent) {
    const stOpen = document.getElementById('st-existing-chars-panel')?.style.display !== 'none';
    const vidOpen = document.getElementById('vid-char-library-panel')?.style.display !== 'none';
    if (stOpen) await stLoadExistingChars({ silent: !!silent });
    if (vidOpen) await vidLoadCharLibrary({ silent: !!silent });
  }

  function _startCharLibraryPolling() {
    if (_charLibraryPollTimer) return;
    // Silent merge only — never wipe the grid. Poll while panel is open and
    // char gen may still be running (picks up newly trained LoRAs).
    _charLibraryPollTimer = setInterval(() => {
      if (!_charLibraryPanelsOpen()) {
        _stopCharLibraryPolling();
        return;
      }
      if (window._stCharGenerating) {
        _refreshCharLibraryPanels(true);
      }
    }, 30000);
  }

  function _stopCharLibraryPolling() {
    if (_charLibraryPollTimer) {
      clearInterval(_charLibraryPollTimer);
      _charLibraryPollTimer = null;
    }
  }

  window.vidToggleCharLibrary = async function() {
    const panel = document.getElementById('vid-char-library-panel');
    const btn = document.getElementById('vid-char-library-toggle');
    if (!panel) return;
    if (panel.style.display === 'none') {
      panel.style.display = 'block';
      if (btn) btn.textContent = 'Hide library';
      _startCharLibraryPolling();
      await vidLoadCharLibrary();
    } else {
      panel.style.display = 'none';
      if (btn) btn.textContent = 'Show library';
      if (!_charLibraryPanelsOpen()) _stopCharLibraryPolling();
    }
  };

  window.vidLoadCharLibrary = async function(options) {
    const opts = options || {};
    const silent = opts.silent === true;
    const loading = document.getElementById('vid-char-library-loading');
    const grid = document.getElementById('vid-char-library-grid');
    const empty = document.getElementById('vid-char-library-empty');
    const seq = ++_vidCharLibraryLoadSeq;
    if (!silent) {
      if (loading) loading.style.display = 'block';
      if (grid) grid.innerHTML = '';
      if (empty) empty.style.display = 'none';
    }
    try {
      const chars = await _fetchCharLibraryList();
      if (seq !== _vidCharLibraryLoadSeq) return;
      if (!silent && loading) loading.style.display = 'none';
      if (!chars.length) {
        if (!silent && empty) {
          const mf = _getModelFamily().toUpperCase();
          empty.textContent = 'No ' + mf + ' LoRA characters found. Train with ' + mf + ' or switch image backend.';
          empty.style.display = 'block';
        }
        return;
      }
      if (empty) empty.style.display = 'none';
      _updateCharLibraryFilterLabels(_getModelFamily());
      _renderCharLibraryCards(chars, grid, vidSelectChar,
        window._vidSelectedChar ? window._vidSelectedChar.char_id : null,
        { silent });
    } catch (e) {
      if (!silent && loading) loading.textContent = 'Failed to load: ' + e.message;
    }
  };

  window.vidSelectChar = function(ch, card) {
    if (!_charMatchesPipelineFamily(ch)) {
      return;
    }
    document.querySelectorAll('#vid-char-library-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    if (card) card.style.borderColor = 'var(--accent)';
    window._vidSelectedChar = ch;
    const info = document.getElementById('vid-char-selected-info');
    const name = document.getElementById('vid-char-selected-name');
    const runMf = _getModelFamily().toUpperCase();
    if (info) info.style.display = 'block';
    if (name) {
      name.textContent = `${ch.library_label || _stLibraryLabel(ch.name) || ch.name || 'Character'} · ${ch.char_id} · ${runMf}`;
    }
  };

  window.vidClearSelectedChar = function() {
    window._vidSelectedChar = null;
    document.querySelectorAll('#vid-char-library-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    const info = document.getElementById('vid-char-selected-info');
    if (info) info.style.display = 'none';
  };

  window.stToggleExistingChars = async function() {
    const panel = document.getElementById('st-existing-chars-panel');
    const btn   = document.getElementById('st-existing-toggle-btn');
    if (!panel) return;
    if (panel.style.display === 'none') {
      panel.style.display = 'block';
      if (btn) btn.textContent = 'Hide library';
      _startCharLibraryPolling();
      await stLoadExistingChars();
    } else {
      panel.style.display = 'none';
      if (btn) btn.textContent = 'Show library';
      if (!_charLibraryPanelsOpen()) _stopCharLibraryPolling();
    }
  };

  window.stLoadExistingChars = async function(options) {
    const opts = options || {};
    const silent = opts.silent === true;
    const loading = document.getElementById('st-existing-chars-loading');
    const grid    = document.getElementById('st-existing-chars-grid');
    const empty   = document.getElementById('st-existing-chars-empty');
    const seq = ++_stCharLibraryLoadSeq;
    if (!silent) {
      if (loading) loading.style.display = 'block';
      if (grid) grid.innerHTML = '';
      if (empty) empty.style.display = 'none';
      _charLibraryIds = new Set();
    }
    try {
      const chars = await _fetchCharLibraryList();
      if (seq !== _stCharLibraryLoadSeq) return;
      if (!silent && loading) loading.style.display = 'none';
      if (!chars.length) {
        if (!silent && empty) {
          const mf = _getModelFamily().toUpperCase();
          empty.textContent = 'No ' + mf + ' LoRA characters found. Train with ' + mf + ' selected, or switch image backend.';
          empty.style.display = 'block';
        }
        return;
      }
      if (empty) empty.style.display = 'none';
      _updateCharLibraryFilterLabels(_getModelFamily());
      let needsPreview = 0;
      const existingIds = silent && grid
        ? new Set(Array.from(grid.querySelectorAll('[data-char-id]')).map(el => el.dataset.charId))
        : _charLibraryIds;
      chars.forEach(ch => {
        if (silent && existingIds.has(ch.char_id)) return;
        existingIds.add(ch.char_id);
        const card = document.createElement('div');
        const isNew = ch.char_id === window._stCharId;
        card.style.cssText = 'cursor:pointer;border-radius:8px;overflow:hidden;border:2px solid '
          + (isNew ? 'var(--accent)' : 'var(--border)')
          + ';background:var(--surface2);text-align:center;transition:border-color 0.15s';
        card.dataset.charId = ch.char_id;
        card.dataset.triggerToken = ch.trigger_token;
        card.onclick = () => stSelectExistingChar(ch, card);
        const img = document.createElement('div');
        // 2026-07-31: accept the contact sheet (preferred) or any preview URL
        // the library gave us, whatever its shape. A character WITH a contact
        // sheet must never count as needing a preview.
        const _tileUrl = _charTileImageUrl(ch);
        if (_tileUrl) {
          img.style.cssText = 'width:100%;aspect-ratio:' + (_charIsContactSheet(ch) ? '4/3' : '1')
            + ';background-size:cover;background-position:center top';
          img.style.backgroundImage = `url('${_tileUrl}')`;
        } else {
          img.style.cssText = 'width:100%;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:1.3rem;color:var(--muted)';
          img.innerHTML = '<span style="animation:spin 1s linear infinite;display:inline-block">⟳</span><span style="font-size:0.55rem;margin-top:3px">generating…</span>';
          img.dataset.pendingPreview = 'true';
          img.dataset.pendingCharId  = ch.char_id;
          needsPreview++;
        }
        const label = document.createElement('div');
        label.style.cssText = 'font-size:0.7rem;padding:3px 4px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;justify-content:space-between;gap:2px';
        const nameSpan = document.createElement('span');
        nameSpan.style.cssText = 'overflow:hidden;text-overflow:ellipsis;flex:1';
        nameSpan.textContent = ch.library_label || _stLibraryLabel(ch.name) || 'Name';
        const _cmf = (ch.model_family || (ch.lora_families && ch.lora_families[0]) || '').toUpperCase();
        nameSpan.title = (ch.name || ch.char_id) + ' · LoRA ' + (_cmf || 'trained');
        label.appendChild(nameSpan);
        if (_cmf) {
          const mfTag = document.createElement('span');
          mfTag.textContent = _cmf;
          mfTag.style.cssText = 'flex-shrink:0;font-size:0.55rem;padding:1px 4px;border-radius:4px;background:var(--surface);color:var(--accent);font-weight:600';
          mfTag.title = (ch.lora_families || []).join(', ') || _cmf;
          label.appendChild(mfTag);
        }
        if (_tileUrl) {
          const dlBtn = document.createElement('a');
          dlBtn.href     = _charPreviewDownloadHref(_tileUrl);
          dlBtn.download = _charDownloadFilename(ch);
          dlBtn.title    = 'Download preview';
          dlBtn.style.cssText = 'flex-shrink:0;color:var(--accent);text-decoration:none;font-size:0.85rem;line-height:1;padding:1px 2px;opacity:0.7';
          dlBtn.textContent = '⬇';
          dlBtn.onclick = e => e.stopPropagation();
          label.appendChild(dlBtn);
        }
        card.appendChild(img); card.appendChild(label);
        if (grid) {
          if (silent) grid.insertBefore(card, grid.firstChild);
          else grid.appendChild(card);
        }
      });
      _charLibraryIds = existingIds;
      if (needsPreview > 0) {
        // 2026-07-31: DELETED the auto-POST to /api/storyteller/gen-char-previews.
        // Rendering a library page must never launch a fleet-wide GPU job: that
        // sweep rendered a hardcoded female / brown hair / medium skin prompt on
        // base FLUX with NO LoRA and wrote it over the canonical portrait of
        // every character it considered "missing" one. Preview backfill is an
        // operator action only — no replacement button here by design.
        _startPreviewPollTimer();
      }
    } catch (e) {
      if (!silent && loading) { loading.textContent = 'Failed to load: ' + e.message; }
    }
  };

  window.stSelectExistingChar = function(ch, card) {
    if (!ch) return;
    const runMf = _getModelFamily().toUpperCase();
    // 2026-07-31: the contact-sheet grid passes a record with NO identity keys.
    // Merge in the full (bible-derived) list-chars row when we have it, so the
    // selection carries the real identity instead of nothing.
    const known = (window._stCharLibraryById || {})[ch.char_id];
    const rec = known ? Object.assign({}, ch, known) : ch;
    // 2026-07-31: family guard runs BEFORE anything is recorded or repainted.
    // It used to leave _stSelectedExistingChar set on a card the UI never
    // acknowledged selecting, and only complained at the Generate button.
    if (!_charMatchesPipelineFamily(rec)) {
      const gs = document.getElementById('st-gen-status');
      if (gs) {
        gs.style.display = 'block';
        gs.textContent = 'Pick a ' + runMf + ' character — library is filtered to ' + runMf + ' only.';
      }
      return;
    }
    // Highlight selected card
    document.querySelectorAll('#st-existing-chars-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    if (card) card.style.borderColor = 'var(--accent)';
    window._stSelectedExistingChar = rec;
    window._stSelectedCharRecord   = rec;   // preview resolution (step 2 + modal)
    const info = document.getElementById('st-existing-selected-info');
    const name = document.getElementById('st-existing-selected-name');
    if (info) info.style.display = 'block';
    if (name) name.textContent = `${rec.name || 'Name'} · ${rec.char_id} · ${runMf} · trigger: ${rec.trigger_token}`;
    // Disable the Generate button and show a shortcut instead
    const btn = document.getElementById('st-gen-char-btn');
    if (btn) { btn.textContent = '✓ Use This Character →'; btn.style.background = '#22c55e'; }
  };

  window.stClearExistingChar = function() {
    window._stSelectedExistingChar = null;
    window._stSelectedCharRecord = null;
    window._stCharIdentityFromLibrary = false;
    document.querySelectorAll('#st-existing-chars-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
    const info = document.getElementById('st-existing-selected-info');
    if (info) info.style.display = 'none';
    const btn = document.getElementById('st-gen-char-btn');
    if (btn) { btn.textContent = 'Generate Character →'; btn.style.background = 'var(--accent)'; }
  };

  // Reset Step 1 state and let user try again after a LoRA failure
  window.stRetryCharacter = function() {
    // Hide failure card
    const failCard = document.getElementById('st-lora-failed-card');
    if (failCard) failCard.style.display = 'none';
    // Reset generation state
    window._stCharId        = null;
    window._stTriggerToken  = null;
    window._stCharGenerating = false;
    window._stLoraReady     = false;
    if (window._stLoraPoller) { clearInterval(window._stLoraPoller); window._stLoraPoller = null; }
    _stopCharFunMessages();
    // Reset progress ring
    const pw = document.getElementById('st-char-progress-wrap');
    if (pw) pw.style.display = 'none';
    // Re-show the form fields
    const _ff = document.getElementById('st-step1-form');
    if (_ff) _ff.style.display = '';
    const btn = document.getElementById('st-gen-char-btn');
    if (btn) { btn.disabled = false; btn.textContent = 'Generate Character →'; btn.style.background = 'var(--accent)'; btn.style.display = ''; }
    const status = document.getElementById('st-gen-status');
    if (status) { status.style.display = 'none'; status.textContent = ''; }
  };

  // ── Character preview modal ─────────────────────────────────────────────────
  // 2026-07-31: resolve the image from the character record the client already
  // holds — contact sheet first, then a provenance-verified preview slot, then
  // the Blender reference renders. It used to hardcode preview_flux_front.png,
  // which is exactly the slot the preview sweep overwrote with a generic,
  // non-LoRA portrait, so the modal vouched for the wrong picture.
  window.stOpenPreviewModal = function(charId) {
    if (!charId) return;
    const modal = document.getElementById('st-char-preview-modal');
    const img   = document.getElementById('st-char-preview-modal-img');
    if (!modal || !img) return;

    const _stamp = Date.now();
    const cands = _stPreviewCandidates(charId).map(
      c => c.url + (c.url.indexOf('?') >= 0 ? '&v=' : '?v=') + _stamp
    );
    let _ci = 0;
    const _tryNext = () => {
      if (_ci >= cands.length) { img.onerror = null; return; }
      img.src = cands[_ci++];
    };
    img.onload  = null;
    img.onerror = _tryNext;
    _tryNext();

    modal.style.display = 'flex';
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  };

  window.stClosePreviewModal = function() {
    const modal = document.getElementById('st-char-preview-modal');
    if (!modal) return;
    modal.style.display = 'none';
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  };

  // Download the currently-shown preview image. The server returns
  // Content-Disposition with the character name (e.g. nolan_sullivan.png).
  window.stDownloadPreviewImage = function() {
    const img = document.getElementById('st-char-preview-modal-img');
    if (!img || !img.src) return;
    try {
      const u = new URL(img.src, window.location.origin);
      u.searchParams.set('download', '1');
      u.searchParams.delete('v');
      u.searchParams.delete('_');
      const ch = window._stSelectedExistingChar || {};
      const a = document.createElement('a');
      a.href = u.toString();
      a.download = _charDownloadFilename(ch);
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { try { document.body.removeChild(a); } catch (_e) {} }, 500);
    } catch (e) {
      // Last-resort fallback: open the image in a new tab so the user can
      // still save it via the browser's context menu.
      window.open(img.src, '_blank');
    }
  };

  // ESC closes the modal too
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modal = document.getElementById('st-char-preview-modal');
      if (modal && modal.style.display === 'flex') window.stClosePreviewModal();
    }
  });


  // Random first + last names when the user leaves the name blank.
  // Keep in sync with character_bible_service.py (no eye-colour words as first names).
  const _ST_LAST_NAMES = [
    'Reed', 'Hayes', 'Brooks', 'Coleman', 'Foster', 'Bennett', 'Parker',
    'Mitchell', 'Sullivan', 'Ramirez', 'Nguyen', 'Patel', 'Kim', 'Chen',
    'Jackson', 'Turner', 'Phillips', 'Campbell', 'Rivera', 'Cooper',
    'Morgan', 'Bailey', 'Reyes', 'Howard', 'Ward', 'Torres', 'Peterson',
    'Gray', 'Russell', 'Griffin', 'Dunn', 'Walsh', 'Bryant', 'Lawson',
    'Ashford', 'Byrne', 'Castellanos', 'Duarte', 'Eriksen', 'Fontaine',
    'Grover', 'Hansen', 'Ibrahim', 'Jensen', 'Kowalski', 'Lindqvist',
    'Moreau', 'Novak', 'Okafor', 'Pereira', 'Quintero', 'Rossi', 'Sato',
    'Tanaka', 'Ueda', 'Vasquez', 'Weber', 'Yamada', 'Zhang', 'Okonkwo',
  ];
  const _ST_FIRST_NAMES_FEMALE = [
    'Elena', 'Maya', 'Aria', 'Nora', 'Luna', 'Ivy', 'Sofia', 'Mia', 'Zara',
    'Lila', 'Isla', 'Naya', 'Vera', 'Cleo', 'Iris', 'Juno', 'Mira',
    'Sage', 'Wren', 'Anya', 'Liv', 'Eva', 'Kira', 'Rhea', 'Nia', 'Clara',
    'Naomi', 'Tessa', 'Violet', 'Camila',
    'Freya', 'Amara', 'Leila', 'Priya', 'Sana', 'Mei', 'Yuki', 'Ines',
    'Bianca', 'Greta', 'Dahlia', 'Esme', 'Noor', 'Zoya', 'Alba', 'Runa',
    'Selin', 'Adaeze', 'Imani', 'Rosa', 'Petra', 'Sylvie', 'Maren', 'Odessa',
  ];
  const _ST_FIRST_NAMES_MALE = [
    'Marcus', 'Leo', 'Adrian', 'Kai', 'Theo', 'Milo', 'Felix', 'Ezra',
    'Atlas', 'Jonas', 'Aiden', 'Nolan', 'Ronan', 'Soren', 'Caleb', 'Owen',
    'Hugo', 'Silas', 'Cyrus', 'Dorian', 'Jasper', 'Eli', 'Arlo', 'Nico',
    'Ethan', 'Luca', 'Miles', 'Declan', 'Victor',
    'Anders', 'Bruno', 'Casper', 'Dmitri', 'Emeka', 'Farid', 'Gustav',
    'Hiro', 'Idris', 'Joaquin', 'Kenji', 'Lior', 'Mateo', 'Nadir', 'Oscar',
    'Pavel', 'Quinn', 'Ravi', 'Stellan', 'Tariq', 'Umberto', 'Wesley', 'Yusuf',
  ];
  const _ST_EYE_COLOR_WORDS = new Set(['brown', 'blue', 'green', 'hazel', 'grey', 'gray', 'amber', 'black']);
  function _stTitleWord(w) {
    w = (w || '').trim();
    if (!w) return '';
    return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
  }
  function _stRandomLast() {
    return _ST_LAST_NAMES[Math.floor(Math.random() * _ST_LAST_NAMES.length)] || 'Reed';
  }
  function _stRandomFullName(gender) {
    const pool = (String(gender || 'female').toLowerCase() === 'male')
      ? _ST_FIRST_NAMES_MALE : _ST_FIRST_NAMES_FEMALE;
    const first = pool[Math.floor(Math.random() * pool.length)] || 'Character';
    return first + ' ' + _stRandomLast();
  }
  function _stResolveName(raw, gender, eyeColor) {
    let t = (raw || '').trim();
    const eye = (eyeColor || '').trim().toLowerCase();
    if (!t || t.toLowerCase() === 'auto') return _stRandomFullName(gender);
    if (_ST_EYE_COLOR_WORDS.has(t.toLowerCase()) || (eye && t.toLowerCase() === eye)) {
      return _stRandomFullName(gender);
    }
    const parts = t.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return _stTitleWord(parts[0]) + ' ' + _stRandomLast();
    return _stTitleWord(parts[0]) + ' ' + parts.slice(1).map(_stTitleWord).join(' ');
  }
  function _stLibraryLabel(name) {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'Character';
    if (parts.length === 1) return parts[0];
    const initial = parts[parts.length - 1].charAt(0).toUpperCase();
    return parts[0] + ' ' + initial;
  }

  // Blank age input = Auto (server randomises per character). The input has no
  // baked-in value since 2026-07-18, so an untouched form no longer pins 25.
  function _stAgeValue() {
    const raw = ((document.getElementById('st-age') || {}).value || '').trim();
    const n = parseInt(raw, 10);
    return raw && !isNaN(n) ? n : 'auto';
  }
  // The muscle slider has no natural 'unset' position — treat it as Auto until
  // the user (or photo analysis) moves it; stMuscleMassChange sets the flag.
  function _stMuscleValue() {
    if (!window._stMuscleDirty) return 'auto';
    return parseInt((document.getElementById('st-muscle-mass') || {}).value || '20', 10);
  }

  window.stGetPipelineMode = function() {
    const el = document.querySelector('input[name="st-pipeline-mode"]:checked');
    return (el && el.value) || 'standard';
  };

  window.stOnPipelineModeChange = function() {
    const mode = stGetPipelineMode();
    const photoWrap = document.getElementById('st-photo-upload-wrap');
    const csLib = document.getElementById('st-cs-library-wrap');
    const btn = document.getElementById('st-gen-char-btn');
    if (photoWrap) photoWrap.style.display = mode === 'contact_sheet' ? 'none' : '';
    if (csLib) {
      csLib.style.display = mode === 'contact_sheet' ? 'block' : 'none';
      if (mode === 'contact_sheet') stLoadContactSheetLibrary();
    }
    if (btn) {
      btn.textContent = mode === 'contact_sheet'
        ? 'Build contact sheet →'
        : 'Generate Character →';
    }
  };

  window._stContactSheetPollTimer = null;

  window.stToggleCsLibrary = function(force) {
    const body = document.getElementById('st-cs-library-body');
    const btn = document.getElementById('st-cs-library-toggle');
    if (!body || !btn) return;
    const collapse = (typeof force === 'boolean') ? force : body.style.display !== 'none';
    body.style.display = collapse ? 'none' : '';
    btn.textContent = collapse ? '▸' : '▾';
    btn.title = collapse ? 'Expand library' : 'Collapse library';
    btn.setAttribute('aria-expanded', String(!collapse));
    try { localStorage.setItem('zpub_cs_lib_collapsed', collapse ? '1' : '0'); } catch (e) { /* private mode */ }
  };
  (function() {
    try {
      if (localStorage.getItem('zpub_cs_lib_collapsed') === '1') window.stToggleCsLibrary(true);
    } catch (e) { /* private mode */ }
  })();

  // ── Pipeline pause / resume controls ──────────────────────────────────────
  window.stRefreshPipelineCtrl = async function() {
    const panel = document.getElementById('st-pipe-ctrl');
    const runsEl = document.getElementById('st-pipe-runs');
    if (!panel) return;
    let d;
    try {
      const r = await fetch('/api/storyteller/pipeline/pause-state?_=' + Date.now(), { cache: 'no-store' });
      if (r.status === 403) { panel.style.display = 'none'; if (runsEl) runsEl.textContent = ''; return; }
      d = await r.json();
    } catch (e) { return; }
    panel.style.display = 'flex';
    const prodPaused = !!d.production_paused, schedPaused = !!d.scheduled_paused;
    const setBtn = (id, show) => { const b = document.getElementById(id); if (b) b.style.display = show ? '' : 'none'; };
    setBtn('st-btn-pause-prod', !prodPaused);  setBtn('st-btn-resume-prod', prodPaused);
    setBtn('st-btn-pause-sched', !schedPaused); setBtn('st-btn-resume-sched', schedPaused);
    const runs = d.runs || [];
    const nRun = runs.filter(x => x.status === 'running').length;
    const nPaused = runs.filter(x => x.status === 'paused').length;
    const statusEl = document.getElementById('st-pipe-ctrl-status');
    if (statusEl) {
      const bits = [];
      if (prodPaused) bits.push('⏸ PRODUCTION PAUSED');
      if (schedPaused) bits.push('⏸ queue paused');
      bits.push(`${nRun} running`, `${nPaused} parked`);
      statusEl.textContent = 'Pipeline: ' + bits.join(' · ');
    }
    if (runsEl) {
      runsEl.innerHTML = '';
      runs.forEach(x => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:2px 0';
        const paused = x.status === 'paused';
        const label = document.createElement('span');
        label.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        label.textContent = `${paused ? '⏸' : '▶'} ${x.name || x.char_id.slice(0,8)} — ${x.stage || '?'}`;
        row.appendChild(label);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText = 'font-size:0.68rem;background:none;border:1px solid var(--border);border-radius:5px;padding:2px 6px;cursor:pointer;color:' + (paused ? '#86efac' : '#fca5a5');
        btn.textContent = paused ? '▶ Resume' : '⏸ Pause';
        btn.onclick = () => paused ? stRunResume(x.char_id) : stRunPause(x.char_id);
        row.appendChild(btn);
        runsEl.appendChild(row);
      });
    }
  };
  async function _stPipePost(url, body) {
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.ok === false) alert(d.error || d.message || ('Request failed (' + r.status + ')'));
    } catch (e) { alert('Request failed: ' + e); }
    setTimeout(() => window.stRefreshPipelineCtrl(), 400);
  }
  window.stPipelinePause  = (scope) => _stPipePost('/api/storyteller/pipeline/pause',  { scope });
  window.stPipelineResume = (scope) => _stPipePost('/api/storyteller/pipeline/resume', { scope });
  window.stRunPause  = (cid) => _stPipePost('/api/storyteller/contact-sheet/pause/'  + cid, { reason: 'Paused by operator' });
  window.stRunResume = (cid) => _stPipePost('/api/storyteller/contact-sheet/resume/' + cid, {});

  window.stLoadContactSheetLibrary = async function() {
    try { window.stRefreshPipelineCtrl(); } catch (e) { /* control panel optional */ }
    const grid = document.getElementById('st-cs-library-grid');
    const loading = document.getElementById('st-cs-library-loading');
    const empty = document.getElementById('st-cs-library-empty');
    if (!grid) return;
    if (loading) loading.style.display = 'block';
    if (empty) empty.style.display = 'none';
    try {
      // Contact sheets are ALWAYS the FLUX per-cell photoreal composite — SDXL
      // only trains a LoRA, it never produces a sheet. So this library is pinned
      // to the photoreal (flux) view regardless of the global model-family
      // toggle, otherwise the identical FLUX images appear under an "SDXL" label
      // and read as an "SDXL version" that doesn't actually exist.
      const mf = 'flux';
      const resp = await fetch('/api/storyteller/list-contact-sheets?model_family=' + encodeURIComponent(mf) + '&_=' + Date.now(), { cache: 'no-store' });
      const data = await resp.json();
      const sheets = data.sheets || [];
      if (loading) loading.style.display = 'none';
      grid.innerHTML = '';
      if (!sheets.length) {
        if (empty) empty.style.display = 'block';
        return;
      }
      sheets.forEach(sh => {
        const card = document.createElement('div');
        const pending = sh.status === 'running';
        card.style.cssText = 'cursor:pointer;border-radius:8px;overflow:hidden;border:2px solid var(--border);background:var(--surface2);text-align:center';
        // 2026-07-31: open the character library through its own opener instead
        // of hand-setting display:block — the panel used to open empty (never
        // loaded, never polled) with its toggle still reading "Show library".
        // Loading it first also populates _stCharLibraryById, so the selection
        // below resolves this identity-free sheet record to the real character.
        card.onclick = async () => {
          if (!sh.lora_ready) {
            if (loading) {
              loading.style.display = 'block';
              loading.textContent = pending
                ? 'That contact sheet is still building — it becomes selectable once its LoRA is trained.'
                : 'No trained LoRA for that contact sheet yet — it cannot be used in a story.';
            }
            return;
          }
          const panel = document.getElementById('st-existing-chars-panel');
          if (panel && panel.style.display === 'none' && typeof stToggleExistingChars === 'function') {
            try { await stToggleExistingChars(); } catch (_e) { panel.style.display = 'block'; }
          }
          stSelectExistingChar(sh, card);
        };
        const thumb = document.createElement('div');
        thumb.className = 'st-cs-library-thumb';
        const img = document.createElement('div');
        const purl = sh.contact_sheet_url || sh.preview_url;
        if (purl) {
          img.style.cssText = 'width:100%;aspect-ratio:4/3;background-size:cover;background-position:center top';
          img.style.backgroundImage = `url('${purl}?_=${Date.now()}')`;
          const dlBtn = document.createElement('a');
          dlBtn.href = _contactSheetPreviewDownloadHref(sh);
          dlBtn.download = _contactSheetDownloadFilename(sh);
          dlBtn.className = 'st-cs-library-dl';
          dlBtn.title = 'Download contact sheet';
          dlBtn.setAttribute('aria-label', 'Download contact sheet');
          dlBtn.textContent = '⬇';
          dlBtn.onclick = e => e.stopPropagation();
          thumb.appendChild(img);
          thumb.appendChild(dlBtn);
        } else {
          img.style.cssText = 'width:100%;aspect-ratio:4/3;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:1.2rem';
          img.textContent = '📋';
          thumb.appendChild(img);
        }
        const label = document.createElement('div');
        label.style.cssText = 'font-size:0.68rem;padding:4px;color:var(--muted);line-height:1.2;display:flex;align-items:center;justify-content:space-between;gap:4px';
        const badge = pending ? (sh.awaiting_approval ? ' · review' : ' · running') : (sh.lora_ready ? ' · LoRA ✓' : '');
        const nameSpan = document.createElement('span');
        nameSpan.style.cssText = 'overflow:hidden;text-overflow:ellipsis;flex:1;text-align:left';
        nameSpan.textContent = (sh.library_label || sh.name || sh.char_id.slice(0, 8)) + badge;
        label.appendChild(nameSpan);
        card.appendChild(thumb);
        card.appendChild(label);
        grid.appendChild(card);
      });
    } catch (e) {
      if (loading) loading.textContent = 'Failed: ' + e.message;
    }
  };

  const _RING_STAGES_CS = {
    sheet_generate:     { pct: 15, label: 'Building multi-angle contact sheet…', pill: 'sheet' },
    awaiting_approval:  { pct: 40, label: 'QC safety valve — Zero sent you a review card…', pill: 'review' },
    tile_crop:          { pct: 52, label: 'Cropping tiles from approved sheets…', pill: 'tiles' },
    identity_qc:        { pct: 58, label: 'Identity QC — ArcFace drift gate on every tile…', pill: 'qc' },
    captions:           { pct: 66, label: 'Writing training captions…', pill: 'captions' },
    lora_training:      { pct: null, label: 'Training LoRA v1 from QC-passed tiles…', pill: 'lora' },
    angle_expansion:    { pct: null, label: 'LoRA v1 generating hard angles (backs, crown, low/high)…', pill: 'expand' },
    lora_refine:        { pct: null, label: 'Retraining LoRA v2 on expanded dataset…', pill: 'lora' },
    done:               { pct: 100, label: 'Contact sheet character ready!', pill: null },
  };

  // Sheet approval is Agent Zero-only — the wizard shows the preview and a
  // waiting note; the review card in Zero chat carries the Allow/Decline.

  // Progress-UI entry, callable from both the start flow and page-load
  // rehydration (2026-07-19): a refresh wiped window._stCharId — the run kept
  // going server-side but the page showed a fresh form with no way to watch
  // it. The active char_id now persists in localStorage and is revalidated
  // against the status endpoint on every page load.
  window._stEnterCsProgressUI = function (charId, modelFamily) {
    window._stCharId = charId;
    const status = document.getElementById('st-gen-status');
    if (status) status.style.display = 'none';
    const btn = document.getElementById('st-gen-char-btn');
    if (btn) btn.style.display = 'none';
    const formFields = document.getElementById('st-step1-form');
    if (formFields) formFields.style.display = 'none';
    const progressWrap = document.getElementById('st-char-progress-wrap');
    if (progressWrap) progressWrap.style.display = 'block';
    _setRingPct(5);
    window._stCharGenerating = true;
    try {
      localStorage.setItem('st_cs_active', JSON.stringify({ char_id: charId, t: Date.now() }));
      localStorage.setItem('kb_auto_template', 'contact_sheet_creation');
      if (modelFamily) {
        localStorage.setItem('kb_auto_family', modelFamily);
        localStorage.setItem('kb_model_family', modelFamily);
      }
    } catch (e) { /* private mode */ }
    _startContactSheetPoller(charId);
    stLoadContactSheetLibrary();
  };

  document.addEventListener('DOMContentLoaded', function () {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('st_cs_active') || 'null'); } catch (e) {}
    if (!saved || !saved.char_id) return;
    if (Date.now() - (saved.t || 0) > 48 * 3600 * 1000) {
      try { localStorage.removeItem('st_cs_active'); } catch (e) {}
      return;
    }
    fetch('/api/storyteller/contact-sheet/status/' + saved.char_id + '?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (st) {
        const s = (st && st.status) || 'unknown';
        if (s === 'running' || s === 'paused' || s === 'awaiting_approval' || s === 'queued') {
          const radio = document.querySelector('input[name="st-pipeline-mode"][value="contact_sheet"]');
          if (radio) {
            radio.checked = true;
            if (typeof window.stOnPipelineModeChange === 'function') window.stOnPipelineModeChange();
          }
          window._stEnterCsProgressUI(saved.char_id, st.model_family);
        } else {
          try { localStorage.removeItem('st_cs_active'); } catch (e) {}
        }
      })
      .catch(function () { /* server unreachable — keep key for next load */ });
  });

  function _startContactSheetPoller(charId) {
    if (window._stContactSheetPollTimer) clearInterval(window._stContactSheetPollTimer);
    window._stContactSheetPollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/api/storyteller/contact-sheet/status/' + charId + '?_=' + Date.now(), { cache: 'no-store' });
        const st = await resp.json();
        const stage = st.stage || 'sheet_generate';
        const ring = _RING_STAGES_CS[stage] || _RING_STAGES_CS.sheet_generate;
        let ringPct = ring.pct;
        let ringLabel = ring.label;
        if (stage === 'sheet_generate') {
          const gm = st.generation_mode || '';
          const sub = st.sheet_substage || '';
          const dual = st.dual_sheet || gm === 'dual_canvas_esrgan' || gm === 'multi_canvas_esrgan';
          if (dual || gm === 'single_canvas_esrgan' || gm === 'multi_canvas_esrgan' || sub.includes('flux_') || sub.includes('esrgan')) {
            const _sheetFromSub = sub.match(/^([a-h])_/);
            const _sp = _sheetFromSub ? _sheetFromSub[1].toUpperCase() : '';
            const _nSheets = st.sheet_count || 8;
            if (sub.endsWith('_flux_native_1920') && _sp) {
              ringPct = Math.min(36, 6 + Math.round('abcdefgh'.indexOf(_sp.toLowerCase()) * (30 / _nSheets)));
              ringLabel = `Sheet ${_sp}/${String.fromCharCode(64 + _nSheets)} — FLUX 2×3 @ 1920×1080…`;
            } else if (sub.endsWith('_esrgan_upscale') && _sp) {
              ringPct = Math.min(38, 8 + Math.round('abcdefgh'.indexOf(_sp.toLowerCase()) * (30 / _nSheets)));
              ringLabel = `Sheet ${_sp}/${String.fromCharCode(64 + _nSheets)} — ESRGAN upscale…`;
            } else if (sub === 'composite_preview') {
              ringPct = 38;
              ringLabel = `Building stacked preview (A–${String.fromCharCode(64 + _nSheets)})…`;
            } else if (sub === 'flux_native_1920') {
              ringPct = 12;
              ringLabel = 'Stage 1 — FLUX contact sheet 1920×1080…';
            } else if (sub === 'esrgan_upscale' || sub.endsWith('esrgan_upscale')) {
              ringPct = 28;
              ringLabel = 'ESRGAN upscale to 4K…';
            } else if (sub === 'sheet_complete') {
              ringPct = 38;
              const _nAngles = st.total_tiles || st.sheet_cells_total || 48;
              ringLabel = dual ? `${_nAngles}-angle multi-sheet ready for review…` : 'Contact sheet ready for review…';
            } else if (dual && st.sheet_cells_total > 0) {
              const done = st.sheet_cells_done || 0;
              const tot = st.sheet_cells_total || 48;
              ringPct = Math.min(37, Math.max(6, Math.round((done / tot) * 37)));
              ringLabel = `Multi-sheet ${done}/${tot} angles…`;
            } else {
              ringLabel = dual
                ? `${st.sheet_count || 8}×2×3 sheets (${st.sheet_cells_total || st.total_tiles || 48} angles)…`
                : 'Perfect Pixel — single canvas + upscale…';
            }
          } else if (st.sheet_cells_total > 0) {
            const done = st.sheet_cells_done || 0;
            const tot = st.sheet_cells_total;
            ringPct = Math.min(38, Math.max(5, Math.round((done / tot) * 38)));
            ringLabel = `Rendering angle ${done}/${tot} (Comfy)…`;
          }
        }
        if (stage === 'identity_qc') {
          const sub = st.sheet_substage || '';
          const m = sub.match(/^idqc_regen_(\d+)/);
          if (m) ringLabel = `Identity QC — regenerating drifted cell ${parseInt(m[1], 10) + 1} (IP-Adapter)…`;
        }
        if (stage === 'angle_expansion' && st.sheet_cells_total > 0) {
          const done = st.sheet_cells_done || 0;
          ringLabel = `LoRA v1 — hard angle ${Math.min(done + 1, st.sheet_cells_total)}/${st.sheet_cells_total} (backs, crown, low/high)…`;
        }
        const _qc = st.identity_qc;
        if (_qc && _qc.counts && ['captions', 'lora_training', 'angle_expansion', 'lora_refine'].includes(stage)) {
          const _p = _qc.counts.pass || 0, _f = _qc.counts.fail || 0, _r = _qc.regenerated || 0;
          ringLabel += ` · QC: ${_p} pass${_r ? ', ' + _r + ' repaired' : ''}${_f ? ', ' + _f + ' excluded' : ''}`;
        }
        if (ringPct != null) _setRingPct(ringPct);
        const rs = document.getElementById('st-ring-stage');
        if (rs) rs.textContent = ringLabel;
        const fm = document.getElementById('st-fun-msg');
        if (fm) fm.textContent = ringLabel;

        if (stage === 'awaiting_approval' && st.sheet_exists) {
          const wrap = document.getElementById('st-cs-approve-wrap');
          const previewWrap = document.getElementById('st-cs-preview-wrap');
          const img = document.getElementById('st-cs-preview-img');
          if (wrap) wrap.style.display = 'block';
          if (previewWrap) previewWrap.style.display = 'inline-block';
          if (img) img.src = (st.contact_sheet_url || '/api/storyteller/contact-sheet/image/' + charId) + '?_=' + Date.now();
          // Training-set-only sheet (2026-07-20): exactly the tiles an
          // approval trains on — the master sheet keeps excluded tiles.
          const tlink = document.getElementById('st-cs-training-link');
          if (tlink) tlink.href = '/api/storyteller/contact-sheet/training-image/' + charId + '?_=' + Date.now();
        }

        if (st.status === 'done') {
          clearInterval(window._stContactSheetPollTimer);
          window._stContactSheetPollTimer = null;
          window._stCharGenerating = false;
          try { localStorage.removeItem('st_cs_active'); } catch (e) {}
          document.getElementById('st-cs-approve-wrap').style.display = 'none';
          _setRingPct(100);
          stLoadContactSheetLibrary();
          stLoadExistingChars({ silent: true });
          stNextStep(1, true);
        }
        if (st.status === 'error') {
          clearInterval(window._stContactSheetPollTimer);
          window._stCharGenerating = false;
          try { localStorage.removeItem('st_cs_active'); } catch (e) {}
          const status = document.getElementById('st-gen-status');
          if (status) {
            status.style.display = 'block';
            status.textContent = '❌ ' + (st.error || 'Contact sheet pipeline failed');
          }
        }
      } catch (e) { /* retry next tick */ }
    }, 2500);
  }

  window.stStartContactSheetPipeline = async function() {
    const btn = document.getElementById('st-gen-char-btn');
    const status = document.getElementById('st-gen-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Building sheet…'; }
    if (status) { status.textContent = 'Starting contact sheet pipeline…'; status.style.display = 'block'; }

    const _stAdvVal = id => {
      const el = document.getElementById(id);
      const v = (el && el.value || '').trim();
      return v || 'auto';
    };
    const _nameInput = document.getElementById('st-char-name');
    const _gender = (document.getElementById('st-gender') || {}).value || 'female';
    const _eyeColor = (document.getElementById('st-eyes') || {}).value || 'brown';
    // Auto gender + blank name: don't pick a name client-side — the name pool
    // is gendered, and the server only rolls the gender during parsing. An
    // empty name lets the server assign one that matches the rolled gender.
    const _typedRaw = ((_nameInput && _nameInput.value) || '').trim();
    let _typedName = (_gender === 'auto' && !_typedRaw)
      ? '' : _stResolveName(_typedRaw, _gender, _eyeColor);
    if (_nameInput && _typedName) _nameInput.value = _typedName;

    // Full characteristics payload (2026-07-17): contact-sheet mode used to
    // send only the six colour/style basics — age, height, genre and the whole
    // Advanced Identity panel were silently dropped, so a user-selected age 25
    // never reached the pipeline. Mirror the standard-mode payload exactly;
    // 'auto' values resolve server-side via apply_auto_defaults().
    const params = {
      name: _typedName,
      gender: document.getElementById('st-gender').value,
      hair_color: document.getElementById('st-hair').value,
      hair_style: (document.getElementById('st-hair-style') || {}).value || 'auto',
      eye_color: document.getElementById('st-eyes').value,
      skin_tone: document.getElementById('st-skin').value,
      height: (document.getElementById('st-height') || {}).value || 'auto',
      age: _stAgeValue(),
      style: document.getElementById('st-char-style').value,
      genre: (document.getElementById('st-char-genre') || {}).value || 'general',
      facial_hair: (document.getElementById('st-facial-hair') || {}).value || 'none',
      muscle_mass: _stMuscleValue(),
      extra_prompt: (document.getElementById('st-char-extra-prompt') || {}).value || '',
      hair_length: _stAdvVal('st-hair-length'),
      hair_texture: _stAdvVal('st-hair-texture'),
      eye_shape: _stAdvVal('st-eye-shape'),
      eyebrow_style: _stAdvVal('st-eyebrow-style'),
      face_shape: _stAdvVal('st-face-shape'),
      nose_shape: _stAdvVal('st-nose-shape'),
      lip_shape: _stAdvVal('st-lip-shape'),
      distinctive_marks: (document.getElementById('st-distinctive-marks') || {}).value || 'auto',
      ethnic_heritage: (document.getElementById('st-ethnic-heritage') || {}).value || '',
      default_clothing: (document.getElementById('st-default-clothing') || {}).value || 'auto',
      accessories: (document.getElementById('st-accessories') || {}).value || 'auto',
      default_expression: _stAdvVal('st-default-expression'),
      posture: _stAdvVal('st-posture'),
      quality_suffix: (document.getElementById('st-quality-suffix') || {}).value || 'auto',
      negative_prompt: (document.getElementById('st-negative-prompt') || {}).value || 'auto',
      instantid_enabled: (document.getElementById('st-instantid-enabled') || {}).value || 'auto',
      face_detail_pass: (document.getElementById('st-face-detail-pass') || {}).value || 'auto',
      kick_lora: true,
      model_family: _getModelFamily(),
      auto_approve: false,
      rows: 3,
      cols: 6,
      sheet_mode: 'auto',
      invite_token: _zpubInviteToken(),
    };
    window._stCharParams = params;
    // Brand-new character: this form IS the identity the user chose.
    window._stCharIdentityFromLibrary = false;
    window._stSelectedCharRecord = null;

    try {
      const resp = await fetch('/api/storyteller/contact-sheet/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      const data = await resp.json();

      // The server materialises Auto fields at parse time — adopt the
      // resolved identity so the name box shows the assigned name and the
      // voice filter uses the real gender/age instead of 'auto'/25.
      if (data && data.resolved) {
        window._stCharParams = Object.assign({}, window._stCharParams, data.resolved);
        if (_nameInput && data.resolved.name) _nameInput.value = data.resolved.name;
        if (typeof _filterVoicesByGenderAge === 'function') {
          try { _filterVoicesByGenderAge(); } catch (e) { /* cosmetic */ }
        }
      }

      const _enterCsProgressUI = (charId) => {
        window._stEnterCsProgressUI(charId, params.model_family || 'flux');
      };

      // Pre-activation gate: run is parked in the Agent Zero approval queue.
      if (resp.status === 202 && data.pending) {
        if (status) {
          status.style.display = 'block';
          status.textContent = '🕐 Queued — Agent Zero is holding this run for your approval. It starts automatically once you approve.';
        }
        if (btn) { btn.disabled = true; btn.textContent = '🕐 Awaiting Zero approval…'; }
        if (window._stCsPendingPoll) clearInterval(window._stCsPendingPoll);
        window._stCsPendingPoll = setInterval(async () => {
          try {
            const r = await fetch('/api/pending_status/' + encodeURIComponent(data.pending_id), { cache: 'no-store' });
            if (!r.ok) return;
            const s = await r.json();
            if (s.status === 'approved' && s.job_id) {
              clearInterval(window._stCsPendingPoll);
              window._stCsPendingPoll = null;
              _enterCsProgressUI(s.job_id);
            } else if (s.status === 'declined') {
              clearInterval(window._stCsPendingPoll);
              window._stCsPendingPoll = null;
              if (status) { status.textContent = '❌ Run declined via Agent Zero.'; status.style.display = 'block'; }
              if (btn) { btn.disabled = false; btn.textContent = 'Build contact sheet →'; }
            }
          } catch (e) { /* retry next tick */ }
        }, 5000);
        return;
      }

      if (!resp.ok) throw new Error(data.error || data.message || 'Start failed');
      window._stTriggerToken = data.trigger_token;
      _enterCsProgressUI(data.char_id);
    } catch (e) {
      if (status) { status.textContent = '❌ ' + e.message; status.style.display = 'block'; }
      if (btn) { btn.disabled = false; btn.textContent = 'Build contact sheet →'; }
    }
  };

  // 2026-07-31: window.inviteToken is never assigned anywhere — the boot value
  // lives in a module-scoped `let` inside the zpub_app.js IIFE — so every
  // storyteller request went out with no invite_token and fell back to the
  // session cookie, filing the job against whichever link the session last saw.
  // Read the boot value directly instead of inventing a new global.
  function _zpubInviteToken() {
    try {
      return (window.ZPUB_BOOT && window.ZPUB_BOOT.inviteToken) || window.inviteToken || '';
    } catch (_e) { return ''; }
  }

  // 2026-07-31: identity keys we are willing to forward for an EXISTING
  // character. They are copied from the library row (which the server builds
  // from the character bible) — never invented. Anything the row does not
  // carry is simply left out so the server resolves it from the bible.
  const _ST_LIBRARY_IDENTITY_KEYS = [
    'name', 'gender', 'age', 'age_range', 'height', 'skin_tone',
    'hair_color', 'hair_style', 'hair_length', 'hair_texture',
    'eye_color', 'eye_shape', 'eyebrow_style', 'face_shape', 'nose_shape', 'lip_shape',
    'facial_hair', 'muscle_mass', 'body_build', 'distinctive_marks', 'ethnic_heritage',
    'style', 'genre', 'default_clothing', 'accessories', 'default_expression', 'posture',
  ];
  function _stIdentityFromLibraryRecord(ch) {
    const out = { char_id: ch.char_id };
    if (ch.trigger_token) out.trigger_token = ch.trigger_token;
    if (ch.model_family)  out.model_family  = ch.model_family;
    _ST_LIBRARY_IDENTITY_KEYS.forEach(k => {
      const v = ch[k];
      if (v === undefined || v === null) return;
      if (typeof v === 'string') {
        const t = v.trim();
        if (!t) return;
        const lt = t.toLowerCase();
        if (lt === 'unknown' || lt === 'auto') return;   // let the bible decide
        out[k] = t;
        return;
      }
      if (typeof v === 'number' && isNaN(v)) return;
      out[k] = v;
    });
    // list-chars folds the bible's prose body_build into muscle_mass; the
    // storyteller pipeline only reads body_build. Recover it rather than
    // shipping a build descriptor nothing reads. (See cross-file request.)
    if (!out.body_build && typeof out.muscle_mass === 'string') {
      out.body_build = out.muscle_mass;
      delete out.muscle_mass;
    }
    return out;
  }

  // 2026-07-31: the pipeline reads character_params['body_build'] and ignores
  // muscle_mass entirely, so the build the user picked never reached the
  // screenwriter. Translate the slider — but only when the user actually moved
  // it, so we never invent a build for someone who never chose one.
  function _stBodyBuildFromForm() {
    if (!window._stMuscleDirty) return '';
    const v = parseInt((document.getElementById('st-muscle-mass') || {}).value || '', 10);
    if (isNaN(v)) return '';
    if (v <= 15) return 'slender build';
    if (v <= 35) return 'lean build';
    if (v <= 60) return 'athletic build';
    if (v <= 80) return 'muscular build';
    return 'heavily muscled build';
  }

  window.stGenerateCharacter = async function() {
    if (stGetPipelineMode() === 'contact_sheet') {
      return stStartContactSheetPipeline();
    }
    // If user selected an existing character, skip generation and advance directly
    if (window._stSelectedExistingChar) {
      const ch = window._stSelectedExistingChar;
      if (!_charMatchesPipelineFamily(ch)) {
        const status = document.getElementById('st-gen-status');
        const runMf = _getModelFamily().toUpperCase();
        if (status) {
          status.style.display = 'block';
          status.textContent = 'Pick a ' + runMf + ' character — library is filtered to ' + runMf + ' only.';
        }
        return;
      }
      window._stCharId       = ch.char_id;
      window._stTriggerToken = ch.trigger_token;
      // 2026-07-31: NO invented defaults for an existing character. This used
      // to Object.assign the selected record over a hardcoded
      // female / brown hair / brown eyes / medium skin / 1.70m block, and every
      // key the record did not carry survived into the submitted identity — the
      // contact-sheet library passes a record with no identity keys AT ALL, so
      // a 12-year-old boy was submitted as a brown-haired adult woman (and got
      // a female narrator voice). Send char_id plus only what the library row
      // actually provided; the server resolves the rest from the bible.
      window._stCharParams   = _stIdentityFromLibraryRecord(ch);
      window._stCharIdentityFromLibrary = true;
      window._stSelectedCharRecord = ch;
      const status = document.getElementById('st-gen-status');
      if (status) { status.textContent = `✓ Using existing character ${ch.char_id}`; status.style.display = 'block'; }
      window._stCharGenerating = false;
      stNextStep(1, true);
      return;
    }

    const btn = document.getElementById('st-gen-char-btn');
    const status = document.getElementById('st-gen-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Generating…'; }
    if (status) { status.textContent = 'Launching…'; status.style.display = 'block'; }

    const _stAdvVal = id => {
      const el = document.getElementById(id);
      const v = (el && el.value || '').trim();
      return v || 'auto';
    };

    // ── Auto-name fallback ────────────────────────────────────────────────
    // When the user leaves the name blank we pick a sensible default and
    // also reflect it back into the input so they see what was assigned.
    // The backend has its own fallback for defence-in-depth.
    const _nameInput = document.getElementById('st-char-name');
    const _gender = (document.getElementById('st-gender') || {}).value || 'female';
    const _eyeColor = (document.getElementById('st-eyes') || {}).value || 'brown';
    // Auto gender + blank name: defer naming to the server — the name pool is
    // gendered and the server only rolls the gender during parsing.
    const _typedRaw = ((_nameInput && _nameInput.value) || '').trim();
    let _typedName = (_gender === 'auto' && !_typedRaw)
      ? '' : _stResolveName(_typedRaw, _gender, _eyeColor);
    if (_nameInput && _typedName) _nameInput.value = _typedName;

    const params = {
      name:               _typedName,
      gender:             document.getElementById('st-gender').value,
      hair_color:         document.getElementById('st-hair').value,
      hair_style:         (document.getElementById('st-hair-style') || {}).value || 'auto',
      eye_color:          document.getElementById('st-eyes').value,
      skin_tone:          document.getElementById('st-skin').value,
      height:             document.getElementById('st-height').value,
      age:                _stAgeValue(),
      style:              document.getElementById('st-char-style').value,
      genre:              (document.getElementById('st-char-genre') || {}).value || 'general',
      facial_hair:        (document.getElementById('st-facial-hair') || {}).value || 'none',
      muscle_mass:        _stMuscleValue(),
      extra_prompt:       (document.getElementById('st-char-extra-prompt') || {}).value || '',
      // ── Advanced Identity (Auto-default friendly) ──────────────────────
      hair_length:        _stAdvVal('st-hair-length'),
      hair_texture:       _stAdvVal('st-hair-texture'),
      eye_shape:          _stAdvVal('st-eye-shape'),
      eyebrow_style:      _stAdvVal('st-eyebrow-style'),
      face_shape:         _stAdvVal('st-face-shape'),
      nose_shape:         _stAdvVal('st-nose-shape'),
      lip_shape:          _stAdvVal('st-lip-shape'),
      distinctive_marks:  (document.getElementById('st-distinctive-marks') || {}).value || 'auto',
      ethnic_heritage:    (document.getElementById('st-ethnic-heritage') || {}).value || '',
      default_clothing:   (document.getElementById('st-default-clothing') || {}).value || 'auto',
      accessories:        (document.getElementById('st-accessories') || {}).value || 'auto',
      default_expression: _stAdvVal('st-default-expression'),
      posture:            _stAdvVal('st-posture'),
      quality_suffix:     (document.getElementById('st-quality-suffix') || {}).value || 'auto',
      negative_prompt:    (document.getElementById('st-negative-prompt') || {}).value || 'auto',
      instantid_enabled:  (document.getElementById('st-instantid-enabled') || {}).value || 'auto',
      face_detail_pass:   (document.getElementById('st-face-detail-pass') || {}).value || 'auto',
      kick_lora:          true,
      model_family:       _getModelFamily(),
    };
    window._stCharParams = params;
    // Brand-new character: this form IS the identity the user chose.
    window._stCharIdentityFromLibrary = false;
    window._stSelectedCharRecord = null;

    try {
      let resp, data;

      if (window._stUploadedFiles && window._stUploadedFiles.length > 0) {
        // Multipart: send JSON params + image files
        if (status) status.textContent = `Analyzing photo traits & starting generation (${window._stUploadedFiles.length} photo${window._stUploadedFiles.length > 1 ? 's' : ''})…`;
        window._stSetPhotoAnalysisStatus('Analyzing photo on server…', '');
        const fd = new FormData();
        fd.append('params', JSON.stringify({ ...params, invite_token: _zpubInviteToken() }));
        for (const f of window._stUploadedFiles) fd.append('photos', f);
        resp = await fetch('/api/storyteller/generate-character', { method: 'POST', body: fd });
      } else {
        // JSON: use Blender 3D generation
        if (status) status.textContent = 'Launching Blender — rendering 34 character angles…';
        resp = await fetch('/api/storyteller/generate-character', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ ...params, invite_token: _zpubInviteToken() }),
        });
      }

      data = await resp.json();
      if (!resp.ok) {
        if (status) { status.textContent = '❌ ' + (data.error || 'Character generation failed.'); status.style.display = 'block'; }
        if (btn) { btn.disabled = false; btn.textContent = 'Try Again'; btn.style.display = ''; }
        return;
      }
      window._stCharId       = data.char_id;
      window._stTriggerToken = data.trigger_token;
      if (data.params && data.params.name) {
        window._stCharParams.name = data.params.name;
        if (_nameInput) _nameInput.value = data.params.name;
      }
      if (data.model_family) window._stModelFamily = data.model_family;
      const _mfKanban = data.model_family || _getModelFamily();
      try {
        localStorage.setItem('kb_auto_template', 'character_creation');
        localStorage.setItem('kb_auto_family', _mfKanban);
        localStorage.setItem('kb_model_family', _mfKanban);
      } catch {}
      // Hide the noisy "Launching…" text — the progress ring takes over from here.
      if (status) { status.textContent = ''; status.style.display = 'none'; }
      // Hide the (now redundant) submit button entirely.
      if (btn) btn.style.display = 'none';

      // Collapse the form fields so only the progress ring + status are visible.
      const formFields = document.getElementById('st-step1-form');
      if (formFields) formFields.style.display = 'none';

      // Show progress ring (starts at 0%)
      const progressWrap = document.getElementById('st-char-progress-wrap');
      if (progressWrap) progressWrap.style.display = 'block';
      _setRingStage('blender_render');
      _startCharFunMessages();

      // Mark generating — Step 2 will be blocked until images_ready
      window._stCharGenerating = true;

      // Start LoRA polling — will auto-advance to Step 2 once images are ready
      _startLoraPoller(data.char_id);

    } catch (e) {
      if (status) { status.textContent = '❌ Network error: ' + e.message; status.style.display = 'block'; }
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; btn.style.display = ''; }
    }
  };

  // ── Ring helpers ─────────────────────────────────────────────────────────────
  // The progress % is now driven by real LoRA-training step counts
  // (2 steps = 1%, 200 steps = 100%).  These per-stage labels still drive
  // the cosmetic text under the ring, but the % shown is computed live
  // by _setRingPctFromStatus() in the poller.
  const _RING_STAGES = {
    blender_render: { pct: 2,  label: 'Finding monkeys to sculpt your character.', pill: 'render' },
    flux_fallback:  { pct: 4,  label: 'Monkeys switched to AI paintbrushes.',      pill: 'render' },
    captions:       { pct: 5,  label: 'Monkeys are taking notes.',                 pill: 'captions' },
    lora_training:  { pct: null, label: 'Monkeys are training the neural network.', pill: 'lora' },  // pct=null → let step counts drive
    preview_render: { pct: 96, label: 'Monkeys are painting the final portrait.',  pill: 'preview' },
    done:           { pct: 100, label: 'Monkeys delivered. Character ready!',      pill: null },
  };

  // Cycling "fun" messages — the final "we lost 2 monkeys" line is NOT in this
  // list anymore; it only appears when char_status='done' is confirmed by the
  // server.  The rest of the list loops so the user never runs out of motion.
  const _CHAR_FUN_MSGS = [
    'Finding monkeys to sculpt your character.',
    'Sharpening digital chisels.',
    'Monkeys harvested reference angles.',
    'Monkeys are measuring proportions.',
    'Feeding training data to the network.',
    'Monkeys are eating harvested bananas.',
    'Neural weights adjusted. Monkeys confused.',
    'Enforcing monkeys to finalize the LoRA.',
    'LoRA delivered. Monkeys taking a break.',
    'Painting the final portrait — hold steady.',
  ];
  const _CHAR_DONE_MSG = 'Your character is complete.\nWe lost 2 monkeys.';
  let _charFunIdx = 0;
  let _charFunTimer = null;
  let _charFunFrozen = false;   // true once the "done" line is locked in

  function _startCharFunMessages() {
    if (_charFunTimer) return;
    _charFunIdx = 0;
    _charFunFrozen = false;
    const el = document.getElementById('st-fun-msg');
    const _tick = () => {
      if (_charFunFrozen || !el) return;
      // Loop indefinitely through the list — never reach the "done" line on a timer.
      el.textContent = _CHAR_FUN_MSGS[_charFunIdx % _CHAR_FUN_MSGS.length];
      _charFunIdx++;
    };
    _tick();
    _charFunTimer = setInterval(_tick, 6000);
  }

  function _showCharDoneMessage() {
    _charFunFrozen = true;
    const el = document.getElementById('st-fun-msg');
    if (el) el.textContent = _CHAR_DONE_MSG;
  }

  function _stopCharFunMessages() {
    if (_charFunTimer) { clearInterval(_charFunTimer); _charFunTimer = null; }
  }

  // Inject character preview images into Step 2
  // 2026-07-31: this used to build <img src> from _charPreviewSlotNames() —
  // filenames guessed from the RUN's image-backend toggle, not from the
  // character — and so rendered whatever the preview sweep last wrote into
  // preview_flux_front.png, captioned "LoRA trained — full character
  // consistency". It now resolves the image the client already knows about
  // (contact sheet → provenance-verified preview slot → Blender renders) and
  // only makes the strong claim about a picture that really came from the LoRA.
  function _injectCharPreviewInStep2() {
    const charId = window._stCharId;
    if (!charId) return;
    const wrap  = document.getElementById('st-step2-char-preview');
    const imgs  = document.getElementById('st-step2-preview-imgs');
    const lsEl  = document.getElementById('st-step2-lora-status');
    if (!wrap || !imgs) return;

    // Probe before appending so the card never shows a broken/hidden image and
    // so the caption can describe what actually rendered.
    const _probe = (url) => new Promise(resolve => {
      const t = new Image();
      t.onload  = () => resolve(true);
      t.onerror = () => resolve(false);
      t.src = url;
    });

    fetch(`/api/storyteller/character-status/${charId}`)
      .then(r => r.json())
      .then(async (data) => {
        data = data || {};
        wrap.style.display = 'block';
        imgs.innerHTML = '';

        // Optional by design: an older server does not send preview_provenance.
        const prov = (data.preview_provenance && typeof data.preview_provenance === 'object')
          ? data.preview_provenance : null;
        if (prov) {
          window._stPreviewProvenance = window._stPreviewProvenance || {};
          window._stPreviewProvenance[charId] = prov;
        }

        const ls = data.lora_status || {};
        // The strong claim is about the PIXELS ON SCREEN, not about a
        // .safetensors existing on disk. Anything we cannot verify came out of
        // the LoRA gets the honest, softer line.
        const _setLoraLine = (loraLocked) => {
          if (!lsEl) return;
          if (ls.done) {
            lsEl.textContent = loraLocked
              ? '✓ LoRA trained — full character consistency'
              : '✓ LoRA trained — preview not LoRA-locked';
          }
          else if (ls.failed)                 lsEl.textContent = 'Using IPAdapter consistency mode';
          else if (ls.status === 'training')  lsEl.textContent = `Training… ${Math.round(ls.pct || 0)}%`;
          else                                lsEl.textContent = '';
        };
        _setLoraLine(false);   // honest default until we know what rendered

        const cands = _stPreviewCandidates(charId, { prov });

        // 1) Contact sheet — the canonical portrait when the character has one.
        const sheet = cands.filter(c => c.kind === 'sheet')[0];
        if (sheet && await _probe(sheet.url)) {
          const im = document.createElement('img');
          im.src   = sheet.url;
          im.alt   = 'Contact sheet';
          im.title = 'Contact sheet';
          im.style = 'max-width:100%;max-height:260px;object-fit:contain;border-radius:10px;background:var(--surface)';
          imgs.appendChild(im);
          const sp = prov && (prov.contact_sheet || prov.contact_sheet_url);
          // No provenance for sheets on an older server → the sheet IS the
          // character's own render, so the strong claim is the correct default.
          _setLoraLine(!sp || sp.lora_used !== false);
          return;
        }

        // 2) Preview slots — show only provenance-verified ones when any exist,
        //    so a non-LoRA sweep artifact can never be the picture we vouch for.
        const slots    = cands.filter(c => c.kind === 'slot');
        const verified = slots.filter(c => c.loraUsed === true);
        const use      = verified.length ? verified : slots;
        let shown = 0;
        for (const c of use) {
          if (!(await _probe(c.url))) continue;
          const im = document.createElement('img');
          im.src   = c.url;
          im.alt   = c.label;
          im.title = c.label;
          im.style = 'max-width:160px;max-height:220px;object-fit:contain;border-radius:10px;background:var(--surface)';
          imgs.appendChild(im);
          shown++;
        }
        if (shown) { _setLoraLine(verified.length > 0); return; }

        // 3) Blender reference renders / other library preview — never LoRA.
        for (const c of cands.filter(x => x.kind === 'other' || x.kind === 'blender')) {
          if (!(await _probe(c.url))) continue;
          const bi = document.createElement('img');
          bi.src   = c.url;
          bi.alt   = c.label || c.slot;
          bi.style = 'width:80px;height:80px;object-fit:cover;border-radius:8px;background:var(--surface)';
          imgs.appendChild(bi);
          shown++;
        }
        _setLoraLine(false);
      })
      .catch(() => { if (wrap) wrap.style.display = 'none'; });
  }

  function _setRingPct(pct) {
    const circ = 2 * Math.PI * 42;  // 263.9
    const clamped = Math.max(0, Math.min(100, pct));
    const fill = document.getElementById('st-ring-fill');
    const pctEl = document.getElementById('st-ring-pct');
    if (fill) fill.style.strokeDashoffset = circ * (1 - clamped / 100);
    if (pctEl) pctEl.textContent = Math.round(clamped) + '%';
  }

  function _setRingStage(stageName) {
    const info = _RING_STAGES[stageName];
    if (!info) return;
    // Cosmetic stage label under the ring
    const stageEl = document.getElementById('st-ring-stage');
    if (stageEl) stageEl.textContent = info.label;
    // Only set the % when the stage has a fixed pct (LoRA stage leaves it to step counts)
    if (typeof info.pct === 'number') {
      _setRingPct(info.pct);
    }
  }

  // Step-driven %: 200 steps = 100% (2 steps = 1%).  Pre-LoRA stages contribute
  // a few % at the start so the ring shows motion before SimpleTuner spins up.
  // Once char_status='done' the ring snaps to exactly 100%.
  function _setRingPctFromStatus(data) {
    const ls = data.lora_status || {};
    if (data.char_status === 'done') { _setRingPct(100); return; }
    if (ls.status === 'training' && ls.total_steps > 0) {
      // LoRA is the dominant signal — clamp at 95% so the last 5% maps to
      // "preview render" + "finalize" (covered by char_status flip).
      const stepPct = (ls.step / ls.total_steps) * 100;
      _setRingPct(Math.min(95, stepPct));
      return;
    }
    if (ls.done === true) {              // LoRA done, preview render in flight
      _setRingPct(96);
      return;
    }
    // Pre-LoRA stages handled by _setRingStage(); nothing to do here.
  }

  // ── Storyteller voice catalog — local Azure V1/V2 samples ─────────────────────
  window._stVoiceCatalogReady = false;
  window._stVoiceSamplePhrases = { v1: '', v2: '' };
  let _stVoiceSampleAudio = null;
  const _stVoiceSampleBlobCache = new Map();

  function _stVoiceSamplePlayer() {
    return document.getElementById('st-voice-sample-audio');
  }

  function _stVoicePlayError(msg) {
    const h = document.getElementById('st-voice-preview-hint-char') ||
      document.getElementById('st-voice-preview-hint-nar');
    if (h) {
      h.textContent = msg;
      h.style.color = '#c0392b';
      setTimeout(() => { h.style.color = ''; }, 6000);
    }
    console.warn('[voice-sample]', msg);
  }

  function _filterVoiceGroups(groups, gender, age) {
    return (groups || []).map(g => ({
      group: g.group,
      voices: (g.voices || []).filter(v => {
        const dg = (v.gender || 'neutral').toLowerCase();
        const genderOk = dg === 'neutral' || dg === gender;
        const ageMin = v.age_min != null ? v.age_min : 0;
        const ageMax = v.age_max != null ? v.age_max : 120;
        return genderOk && age >= ageMin && age <= ageMax;
      }),
    })).filter(g => g.voices && g.voices.length > 0);
  }

  function _stVoiceSampleUrl(voiceId, variant, voiceObj) {
    if (voiceObj) {
      const direct = variant === 'v1' ? voiceObj.v1_url : voiceObj.v2_url;
      if (direct) return direct;
    }
    return `/api/storyteller/voice-sample/${encodeURIComponent(voiceId)}/${variant}`;
  }

  async function _playLocalVoiceSample(voiceId, variant, btn, voiceObj) {
    if (!voiceId || !variant) return;
    const url = _stVoiceSampleUrl(voiceId, variant, voiceObj);
    document.querySelectorAll('.st-voice-play-btn').forEach(b => {
      b.classList.remove('st-voice-play-btn--active');
    });
    if (btn) btn.classList.add('st-voice-play-btn--active');

    let audio = _stVoiceSamplePlayer();
    if (!audio) {
      audio = new Audio();
    }
    _stVoiceSampleAudio = audio;
    audio.pause();
    audio.volume = 1;

    const clearActive = () => {
      if (btn) btn.classList.remove('st-voice-play-btn--active');
    };

    try {
      let blobUrl = _stVoiceSampleBlobCache.get(url);
      if (!blobUrl) {
        const resp = await fetch(url + (url.includes('?') ? '&' : '?') + '_=' + Date.now(), {
          credentials: 'same-origin',
          cache: 'no-store',
        });
        if (!resp.ok) {
          throw new Error(`Sample not found (HTTP ${resp.status}). Restart zero_public_server.py on this host.`);
        }
        const blob = await resp.blob();
        if (!blob || blob.size < 500) {
          throw new Error('Sample file empty — re-run scripts/warm_storyteller_azure_voice_samples.py');
        }
        blobUrl = URL.createObjectURL(blob);
        _stVoiceSampleBlobCache.set(url, blobUrl);
      }
      audio.src = blobUrl;
      audio.onended = clearActive;
      audio.onerror = () => {
        _stVoicePlayError('Could not decode audio for ' + voiceId + ' ' + variant.toUpperCase());
        clearActive();
      };
      await audio.play();
    } catch (err) {
      _stVoicePlayError(err.message || String(err));
      clearActive();
    }
  }

  function _stVoiceOptionLabel(v) {
    return `${v.label} (${v.tag})`;
  }

  function _populateVoiceSelect(sel, groups) {
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '';
    groups.forEach(g => {
      const og = document.createElement('optgroup');
      og.label = g.group;
      (g.voices || []).forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = _stVoiceOptionLabel(v);
        opt.setAttribute('data-gender', v.gender || 'neutral');
        opt.setAttribute('data-age-min', String(v.age_min != null ? v.age_min : 0));
        opt.setAttribute('data-age-max', String(v.age_max != null ? v.age_max : 120));
        og.appendChild(opt);
      });
      sel.appendChild(og);
    });
    if (prev && Array.from(sel.options).some(o => o.value === prev)) sel.value = prev;
  }

  function _buildVoicePickerPanel(panel, sel, groups) {
    if (!panel || !sel) return;
    panel.innerHTML = '';
    groups.forEach(g => {
      const gl = document.createElement('div');
      gl.className = 'st-voice-picker-group-label';
      gl.textContent = g.group;
      panel.appendChild(gl);
      (g.voices || []).forEach(v => {
        const row = document.createElement('div');
        row.className = 'st-voice-picker-row';
        row.setAttribute('role', 'option');
        row.dataset.voiceId = v.id;
        row.dataset.gender = (v.gender || 'neutral').toLowerCase();
        row.dataset.ageMin = String(v.age_min != null ? v.age_min : 0);
        row.dataset.ageMax = String(v.age_max != null ? v.age_max : 120);
        row.dataset.groupKey = g.group;
        const v1Title = (window._stVoiceSamplePhrases.v1 || 'V1 phrase').replace(/"/g, '&quot;');
        const v2Title = (window._stVoiceSamplePhrases.v2 || 'V2 phrase').replace(/"/g, '&quot;');
        row.innerHTML =
          `<span class="st-voice-picker-name">${v.label}</span>` +
          `<span class="st-voice-picker-tag">${v.tag}</span>` +
          `<span class="st-voice-play-btns">` +
          `<button type="button" class="st-voice-play-btn" data-variant="v1" title="${v1Title}"` +
          `${v.v1_ready === false ? ' disabled' : ''}>V1</button>` +
          `<button type="button" class="st-voice-play-btn" data-variant="v2" title="${v2Title}"` +
          `${v.v2_ready === false ? ' disabled' : ''}>V2</button>` +
          `</span>`;
        row.addEventListener('click', (ev) => {
          if (ev.target.closest('.st-voice-play-btn')) return;
          sel.value = v.id;
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          _syncVoicePickerActive(panel, v.id);
        });
        row.querySelectorAll('.st-voice-play-btn').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            const variant = btn.getAttribute('data-variant');
            _playLocalVoiceSample(v.id, variant, btn, v);
          });
        });
        panel.appendChild(row);
      });
    });
    _syncVoicePickerActive(panel, sel.value);
  }

  function _syncVoicePickerActive(panel, voiceId) {
    if (!panel) return;
    panel.querySelectorAll('.st-voice-picker-row').forEach(r => {
      r.classList.toggle('st-voice-picker-row--active', r.dataset.voiceId === voiceId);
    });
  }

  function _stVoicePickerLoading(on) {
    ['st-voice-type-picker-loading', 'st-narrator-voice-picker-loading'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = on ? 'block' : 'none';
    });
  }

  function _applyVoiceCatalog(charGroups, narGroups, samplePhrases) {
    const charSel = document.getElementById('st-voice-type');
    const narSel  = document.getElementById('st-narrator-voice');
    const charPanel = document.getElementById('st-voice-type-picker');
    const narPanel  = document.getElementById('st-narrator-voice-picker');
    if (samplePhrases) {
      window._stVoiceSamplePhrases = {
        v1: samplePhrases.v1 || '',
        v2: samplePhrases.v2 || '',
      };
    }
    const hChar = document.getElementById('st-voice-preview-hint-char');
    const hNar  = document.getElementById('st-voice-preview-hint-nar');
    const hint = 'Click a row to select. V1 = “' + (window._stVoiceSamplePhrases.v1 || '…') +
      '” · V2 = “' + (window._stVoiceSamplePhrases.v2 || '…') + '”';
    if (hChar) hChar.textContent = hint;
    if (hNar)  hNar.textContent  = hint;
    window._stVoiceCatalogCharFull = charGroups;
    window._stVoiceCatalogNarFull = narGroups;
    if (typeof _filterVoicesByGenderAge === 'function') {
      _filterVoicesByGenderAge();
    } else {
      _populateVoiceSelect(charSel, charGroups);
      _populateVoiceSelect(narSel, narGroups);
      _buildVoicePickerPanel(charPanel, charSel, charGroups);
      _buildVoicePickerPanel(narPanel, narSel, narGroups);
    }
    if (charSel && !charSel._stVoiceChangeWired) {
      charSel._stVoiceChangeWired = true;
      charSel.addEventListener('change', () => {
        if (charPanel) _syncVoicePickerActive(charPanel, charSel.value);
      });
    }
    if (narSel && !narSel._stVoiceChangeWired) {
      narSel._stVoiceChangeWired = true;
      narSel.addEventListener('change', () => {
        if (narPanel) _syncVoicePickerActive(narPanel, narSel.value);
      });
    }
  }

  async function _initStorytellerVoicePickers() {
    const charPanel = document.getElementById('st-voice-type-picker');
    if (window._stVoiceCatalogReady && charPanel && charPanel.children.length) return;
    _stVoicePickerLoading(true);
    let charGroups = [];
    let narGroups = [];
    let samplePhrases = null;
    try {
      const [charResp, narResp] = await Promise.all([
        fetch('/api/storyteller/voices?kind=character'),
        fetch('/api/storyteller/voices?kind=narrator'),
      ]);
      if (charResp.ok) {
        const charData = await charResp.json();
        charGroups = charData.groups || [];
        samplePhrases = charData.sample_phrases || samplePhrases;
      }
      if (narResp.ok) {
        const narData = await narResp.json();
        narGroups = narData.groups || [];
        samplePhrases = narData.sample_phrases || samplePhrases;
      }
    } catch (_e) { /* empty catalog */ }
    _applyVoiceCatalog(charGroups, narGroups, samplePhrases);
    window._stVoiceCatalogReady = true;
    _stVoicePickerLoading(false);
    if (!charGroups.length && !narGroups.length) {
      const hChar = document.getElementById('st-voice-preview-hint-char');
      if (hChar) {
        hChar.textContent = 'No voice samples on server yet. Run scripts/warm_storyteller_azure_voice_samples.py on the host.';
      }
    }
  }

  // ── Voice filter by character gender + age ───────────────────────────────────
  function _filterVoicesByGenderAge() {
    // Prefer the server-resolved identity (Auto fields are materialised at
    // parse time); fall back to the form, then to female/25.
    const _cp = window._stCharParams || {};
    const _cpGender = (_cp.gender && _cp.gender !== 'auto') ? _cp.gender : '';
    const _formGender = ((document.getElementById('st-gender') || {}).value || '');
    const gender = (_cpGender || (_formGender !== 'auto' && _formGender) || 'female').toLowerCase();
    const age = (typeof _cp.age === 'number' && !isNaN(_cp.age))
      ? _cp.age
      : parseInt((document.getElementById('st-age') || {}).value || '25', 10);
    const sel    = document.getElementById('st-voice-type');
    const panel  = document.getElementById('st-voice-type-picker');
    const narSel = document.getElementById('st-narrator-voice');
    const narPanel = document.getElementById('st-narrator-voice-picker');
    const charFull = window._stVoiceCatalogCharFull;
    const narFull  = window._stVoiceCatalogNarFull;

    if (charFull && charFull.length) {
      const charFiltered = _filterVoiceGroups(charFull, gender, age);
      _populateVoiceSelect(sel, charFiltered);
      _buildVoicePickerPanel(panel, sel, charFiltered);
      const firstMatch = charFiltered.flatMap(g => g.voices).find(v => (v.gender || '').toLowerCase() === gender);
      if (firstMatch && sel) {
        sel.value = firstMatch.id;
        if (panel) _syncVoicePickerActive(panel, firstMatch.id);
      }
    } else if (sel) {
      Array.from(sel.options).forEach(opt => {
        const dg = (opt.getAttribute('data-gender') || 'neutral').toLowerCase();
        const ageMin = parseInt(opt.getAttribute('data-age-min') || '0', 10);
        const ageMax = parseInt(opt.getAttribute('data-age-max') || '120', 10);
        const ok = (dg === 'neutral' || dg === gender) && age >= ageMin && age <= ageMax;
        opt.hidden = !ok;
        opt.disabled = !ok;
        const row = panel && panel.querySelector(`[data-voice-id="${opt.value}"]`);
        if (row) row.classList.toggle('st-voice-picker-row--hidden', !ok);
      });
      if (panel) {
        panel.querySelectorAll('.st-voice-picker-group-label').forEach(gl => {
          let next = gl.nextElementSibling;
          let anyVisible = false;
          while (next && !next.classList.contains('st-voice-picker-group-label')) {
            if (next.classList.contains('st-voice-picker-row') && !next.classList.contains('st-voice-picker-row--hidden')) {
              anyVisible = true;
              break;
            }
            next = next.nextElementSibling;
          }
          gl.classList.toggle('st-voice-picker-group-label--hidden', !anyVisible);
        });
      }
    }

    if (narFull && narFull.length && narSel) {
      const narFiltered = _filterVoiceGroups(narFull, gender, age);
      _populateVoiceSelect(narSel, narFiltered);
      _buildVoicePickerPanel(narPanel, narSel, narFiltered);
      const defaultNarrator = gender === 'female' ? 'en-US-JennyNeural' : 'en-US-BrianNeural';
      if (Array.from(narSel.options).some(o => o.value === defaultNarrator)) {
        narSel.value = defaultNarrator;
      }
      if (narPanel) _syncVoicePickerActive(narPanel, narSel.value);
    } else if (narSel) {
      const defaultNarrator = gender === 'female' ? 'en-US-JennyNeural' : 'en-US-BrianNeural';
      if (Array.from(narSel.options).some(o => o.value === defaultNarrator)) {
        narSel.value = defaultNarrator;
      }
      if (narPanel) _syncVoicePickerActive(narPanel, narSel.value);
    }
  }

  // ── LoRA training poller ──────────────────────────────────────────────────────
  function _startLoraPoller(charId) {
    if (window._stLoraPoller) clearInterval(window._stLoraPoller);
    let _lastStage = 'blender_render';
    window._stLoraPoller = setInterval(async () => {
      try {
        const resp = await fetch(`/api/storyteller/character-status/${charId}`);
        const data = await resp.json();
        const ls = data.lora_status || {};
        const pctEl   = document.getElementById('st-lora-pct');
        const notice  = document.getElementById('st-lora-notice');
        const charDone = data.char_status === 'done';
        const charFailed = data.char_status === 'error';

        // Update cosmetic stage label (the % itself is driven by _setRingPctFromStatus below)
        if (data.images_ready && _lastStage === 'blender_render') {
          _lastStage = 'captions';
          _setRingStage('captions');
        }
        if (ls.status === 'training' && _lastStage !== 'lora_training' && _lastStage !== 'done') {
          _lastStage = 'lora_training';
          _setRingStage('lora_training');
        }
        if (ls.done === true && _lastStage === 'lora_training') {
          _lastStage = 'preview_render';
          _setRingStage('preview_render');
        }
        // Single source of truth for the % shown to the user — based on real step counts.
        _setRingPctFromStatus(data);
        // Keep the legacy Step-5 "LoRA training X%" badge in sync with the ring.
        if (pctEl) {
          if (ls.total_steps > 0 && ls.status === 'training') {
            pctEl.textContent = Math.round((ls.step / ls.total_steps) * 100);
          } else if (ls.done) {
            pctEl.textContent = 100;
          }
        }

        // Only auto-advance once ALL stages are fully complete (char_status === 'done')
        // Also advance if server restarted (status='unknown') but LoRA is confirmed done on disk
        const readyToAdvance = charDone ||
          (data.char_status === 'unknown' && ls.done === true && data.images_ready);

        // Pipeline hard-failed (no previews) — show error card, do NOT advance
        if (charFailed && _lastStage !== 'done') {
          _lastStage = 'done';
          window._stCharGenerating = false;
          clearInterval(window._stLoraPoller);
          window._stLoraPoller = null;
          _stopCharFunMessages();
          const pw = document.getElementById('st-char-progress-wrap');
          if (pw) pw.style.display = 'none';
          const failCard = document.getElementById('st-lora-failed-card');
          if (failCard) {
            const titleEl = document.getElementById('st-lora-fail-title');
            const subEl = document.getElementById('st-lora-fail-subtitle');
            const reasonEl = document.getElementById('st-lora-fail-reason');
            const hintEl = document.getElementById('st-lora-fail-hint');
            const raw = data.preview_warning || data.lora_error || ls.error || data.error || '';
            const cleaned = raw.replace(/\u001b\[[0-9;]*m/g, '').slice(-400);
            if (titleEl) titleEl.textContent = '⚠️ Preview Render Failed';
            if (subEl) subEl.textContent = 'LoRA training finished, but preview images could not be produced.';
            if (reasonEl) {
              reasonEl.textContent = cleaned || 'No preview images were produced.';
            }
            if (hintEl) {
              hintEl.style.display = 'none';
              hintEl.textContent = '';
            }
            failCard.style.display = 'block';
            failCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
          return;
        }

        // LoRA failed + char pipeline done — show error card, do NOT advance
        if (data.lora_failed && charDone && _lastStage !== 'done') {
          _lastStage = 'done';
          window._stCharGenerating = false;
          clearInterval(window._stLoraPoller);
          window._stLoraPoller = null;
          _stopCharFunMessages();
          // Hide progress ring
          const pw = document.getElementById('st-char-progress-wrap');
          if (pw) pw.style.display = 'none';
          // Show LoRA failure card
          const failCard = document.getElementById('st-lora-failed-card');
          if (failCard) {
            const titleEl = document.getElementById('st-lora-fail-title');
            const subEl = document.getElementById('st-lora-fail-subtitle');
            const reasonEl = document.getElementById('st-lora-fail-reason');
            const hintEl = document.getElementById('st-lora-fail-hint');
            const raw = data.lora_error || ls.error || '';
            const cleaned = raw.replace(/\u001b\[[0-9;]*m/g, '');
            const isOom = cleaned.includes('OutOfMemoryError');
            if (titleEl) titleEl.textContent = '⚠️ LoRA Training Failed';
            if (subEl) subEl.textContent = 'The character was rendered but LoRA training crashed.';
            if (reasonEl) {
              reasonEl.textContent = isOom
                ? 'CUDA OutOfMemoryError: GPU ran out of VRAM when saving the trained model.'
                : (cleaned.slice(-300) || 'Unknown error — check training.log');
            }
            if (hintEl) {
              if (isOom) {
                hintEl.style.display = 'block';
                hintEl.innerHTML = 'Try again after a few minutes — other GPU processes may need to release VRAM first.';
              } else {
                hintEl.style.display = 'none';
                hintEl.textContent = '';
              }
            }
            failCard.style.display = 'block';
            failCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
          return;
        }

        if (readyToAdvance && window._stCurrentStep === 1) {
          window._stLoraReady    = true;
          window._stCharGenerating = false;
          clearInterval(window._stLoraPoller);
          window._stLoraPoller = null;
          _stopCharFunMessages();
          _lastStage = 'done';
          _setRingStage('done');
          _showCharDoneMessage();             // only now reveal "we lost 2 monkeys"
          _refreshCharLibraryPanels(true);  // append new char without wiping grid
          if (notice) notice.style.display = 'none';
          // In character-only mode: open the preview modal directly.
          if (window._stCharOnlyMode) {
            setTimeout(() => stOpenPreviewModal(window._stCharId), 800);
            return;
          }
          // Storyteller wizard mode: brief pause so the ring lands on 100%, then advance.
          setTimeout(() => stNextStep(1, true), 1200);
          return;
        }

        // LoRA failed mid-way — wait for char_status=done (Stage 1d FLUX still runs)
        if ((ls.status === 'failed' || data.lora_failed) && _lastStage !== 'done') {
          _lastStage = 'lora_training';
          const lsEl2 = document.getElementById('st-step2-lora-status');
          if (lsEl2 && lsEl2.textContent !== '') lsEl2.textContent = 'LoRA failed — previews still generating…';
        }
      } catch (_) {}
    }, 8000);
  }

  // ── Main Generate (Step 5) ────────────────────────────────────────────────────
  window.stGenerate = async function() {
    const storyPrompt = (document.getElementById('st-story-prompt') || {}).value || '';
    const errEl = document.getElementById('st-error-msg');
    if (!storyPrompt.trim()) {
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Please describe the story.'; }
      return;
    }
    // Block if no LoRA-ready character is attached — pipeline produces random faces without LoRA
    if (!window._stCharId) {
      if (errEl) {
        errEl.style.display = 'block';
        errEl.textContent = '⚠️ No character selected. Please generate a new character (and wait for LoRA training to complete) or choose an existing one from the library.';
      }
      return;
    }
    if (errEl) errEl.style.display = 'none';

    const btn = document.getElementById('st-generate-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Submitting…'; }

    const durSel     = document.getElementById('st-duration');
    const durMin     = durSel ? parseFloat(durSel.value) : 10;
    const eraStart   = (document.getElementById('st-era-start') || {}).value || null;
    const eraEnd     = (document.getElementById('st-era-end') || {}).value || null;
    const voiceTypeEl     = document.getElementById('st-voice-type');
    const narratorVoiceEl = document.getElementById('st-narrator-voice');
    const voiceRadio  = document.querySelector('input[name="st-voice"]:checked');
    const voiceStyle  = voiceRadio ? voiceRadio.value : 'narration';
    const narratorVoice = (voiceStyle === 'narration' && narratorVoiceEl)
      ? (narratorVoiceEl.value || '')
      : '';  // when character voice is used, leave narrator_voice empty (auto-assigned by gender)
    const characterVoice = (voiceStyle === 'character' && voiceTypeEl)
      ? (voiceTypeEl.value || '')
      : '';  // explicit Azure voice name for character voice mode
    const _vsEl      = document.getElementById('vs-select');
    const visualStyle = _vsEl ? _vsEl.value : 'cinematic';

    const _stAdvVal2 = id => {
      const el = document.getElementById(id);
      const v = (el && el.value || '').trim();
      return v || 'auto';
    };

    // Same auto-name fallback as stGenerateCharacter — make sure the story
    // pipeline never sends an empty display name through to the bible.
    const _nameInput2 = document.getElementById('st-char-name');
    const _gender2 = (document.getElementById('st-gender') || {}).value || 'female';
    const _eyeColor2 = (document.getElementById('st-eyes') || {}).value || 'brown';
    let _typedName2 = _stResolveName((_nameInput2 && _nameInput2.value) || '', _gender2, _eyeColor2);
    if (_nameInput2) _nameInput2.value = _typedName2;

    const formCharParams = {
      name:               _typedName2,
      gender:             (document.getElementById('st-gender') || {}).value || 'female',
      hair_color:         (document.getElementById('st-hair')  || {}).value || 'brown',
      eye_color:          (document.getElementById('st-eyes')  || {}).value || 'brown',
      skin_tone:          (document.getElementById('st-skin')  || {}).value || 'medium',
      height:             (document.getElementById('st-height')|| {}).value || '1.70',
      age:                parseInt((document.getElementById('st-age') || {}).value || '25', 10),
      style:              (document.getElementById('st-char-style') || {}).value || 'photorealistic',
      genre:              (document.getElementById('st-char-genre') || {}).value || 'general',
      facial_hair:        (document.getElementById('st-facial-hair') || {}).value || 'none',
      muscle_mass:        parseInt((document.getElementById('st-muscle-mass') || {}).value || '20', 10),
      extra_prompt:       (document.getElementById('st-char-extra-prompt') || {}).value || '',
      // ── Advanced Identity (forwarded so the pipeline's prompt builder
      //    uses the same descriptors that produced the trained character) ─
      hair_style:         (document.getElementById('st-hair-style') || {}).value || 'auto',
      hair_length:        _stAdvVal2('st-hair-length'),
      hair_texture:       _stAdvVal2('st-hair-texture'),
      eye_shape:          _stAdvVal2('st-eye-shape'),
      eyebrow_style:      _stAdvVal2('st-eyebrow-style'),
      face_shape:         _stAdvVal2('st-face-shape'),
      nose_shape:         _stAdvVal2('st-nose-shape'),
      lip_shape:          _stAdvVal2('st-lip-shape'),
      distinctive_marks:  (document.getElementById('st-distinctive-marks') || {}).value || 'auto',
      ethnic_heritage:    (document.getElementById('st-ethnic-heritage') || {}).value || '',
      default_clothing:   (document.getElementById('st-default-clothing') || {}).value || 'auto',
      accessories:        (document.getElementById('st-accessories') || {}).value || 'auto',
      default_expression: _stAdvVal2('st-default-expression'),
      posture:            _stAdvVal2('st-posture'),
      quality_suffix:     (document.getElementById('st-quality-suffix') || {}).value || 'auto',
      negative_prompt:    (document.getElementById('st-negative-prompt') || {}).value || 'auto',
      instantid_enabled:  (document.getElementById('st-instantid-enabled') || {}).value || 'auto',
      face_detail_pass:   (document.getElementById('st-face-detail-pass') || {}).value || 'auto',
    };
    // 2026-07-31: pipeline_storyteller reads body_build (not muscle_mass).
    const _bbForm = _stBodyBuildFromForm();
    if (_bbForm) formCharParams.body_build = _bbForm;

    // 2026-07-31: an EXISTING library character's identity comes from its
    // bible — never from this form. The Step-1 form still holds its own
    // defaults (female / brown / medium / 1.70m / age 25) and the old code
    // merged the selection ON TOP of them, so every descriptor the library row
    // happened not to carry was still submitted as the character's identity.
    let charParams;
    if (window._stCharIdentityFromLibrary && window._stCharParams) {
      charParams = Object.assign({}, window._stCharParams);
    } else {
      charParams = formCharParams;
      // Newly created character: the form IS the identity; the server-resolved
      // values (Auto fields) still win where they exist.
      if (window._stCharParams) Object.assign(charParams, window._stCharParams);
    }

    const payload = {
      story_prompt:           storyPrompt.trim(),
      char_id:                window._stCharId || '',
      character_params:       charParams,
      voice_style:            voiceStyle,
      narrator_voice:         narratorVoice,
      character_voice:        characterVoice,
      clip_duration_minutes:  durMin,
      era_start:              eraStart ? parseInt(eraStart) : null,
      era_end:                eraEnd   ? parseInt(eraEnd)   : null,
      camera_mode:            window._stCameraMode,
      visual_style:           visualStyle,
      model_family:           _getModelFamily(),
      pipeline_options:       collectPipelineOptions(),
      invite_token:           _zpubInviteToken(),
    };

    try {
      const resp = await fetch('/api/storyteller/generate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });
      const data = await resp.json();

      // 2026-07-25 FIX (broken connection): manual-permission invite links now get
      // 202 {pending:true, pending_id} — the job is PARKED for operator approval,
      // NOT queued, so there is no job_id to stream yet. Previously this fell
      // through to startStream(data.job_id === undefined) → /api/stream/undefined,
      // and the SSE stream returned "job not found" as a full-page error. Mirror the
      // documentary flow (zpub_app.js): hold, save the pending id for the approval
      // poller (zpub_pending_notification.js), and stream only once the operator
      // approves (via window._zpubOnApproved).
      if (resp.status === 202 && data.pending) {
        if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Awaiting approval…'; btn.style.opacity = '0.65'; }
        if (errEl) errEl.style.display = 'none';
        const _pendingId = data.pending_id || '';
        if (_pendingId && window._zpubSavePending) window._zpubSavePending(_pendingId, storyPrompt.trim());
        const _wiz = document.getElementById('storyteller-wizard');
        if (_wiz) _wiz.style.display = 'none';
        const _statusSec = document.getElementById('status-section');
        if (_statusSec) _statusSec.style.display = 'block';
        if (typeof showProgressCard === 'function') {
          showProgressCard(data.message || 'Your story is awaiting operator approval…');
        }
        window._zpubOnApproved = function(jobId) {
          if (!jobId) return;
          window.currentJobId = jobId;
          const w = document.getElementById('storyteller-wizard');
          if (w) w.style.display = 'none';
          const s = document.getElementById('status-section');
          if (s) s.style.display = 'block';
          if (typeof showProgressCard === 'function') showProgressCard('Starting…');
          if (typeof startStream === 'function') startStream(jobId);
        };
        return;
      }

      if (!resp.ok) {
        if (btn) { btn.disabled = false; btn.innerHTML = '🎬 Generate Story →'; }
        if (errEl) {
          errEl.style.display = 'block';
          errEl.textContent = data.error || data.message || 'Submission failed.';
        }
        return;
      }
      if (data.status === 'rejected' && data.error) {
        if (btn) { btn.disabled = false; btn.innerHTML = '🎬 Generate Story →'; }
        if (errEl) { errEl.style.display = 'block'; errEl.textContent = data.error; }
        return;
      }
      // Hand off to the main status flow
      window.currentJobId = data.job_id;
      history.pushState({}, '', `/job/${data.job_id}`);
      if (data.ahead > 0) {
        showQueueCard(data.ahead, data.eta_minutes, data.queue_position);
      } else {
        showProgressCard('Starting…');
      }
      startStream(data.job_id);
      // Hide wizard, show status
      const wiz = document.getElementById('storyteller-wizard');
      if (wiz) wiz.style.display = 'none';
      const statusSec = document.getElementById('status-section');
      if (statusSec) statusSec.style.display = 'block';
    } catch (e) {
      if (btn) { btn.disabled = false; btn.innerHTML = '🎬 Generate Story →'; }
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Network error: ' + e.message; }
    }
  };

  // ── Story prompt char counter ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function() {
    const ta = document.getElementById('st-story-prompt');
    const cc = document.getElementById('st-char-count');
    if (ta && cc) {
      ta.addEventListener('input', () => { cc.textContent = ta.value.length; });
    }
  });
})();
