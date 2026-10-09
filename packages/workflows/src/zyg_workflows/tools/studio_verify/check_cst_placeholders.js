// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Counts Character Studio tools that are still placeholders (no f:, fs: or act:).
// Exit 0 only when the count is 0. Usage: node check_cst_placeholders.js [inspection.html]
const fs = require('fs'), path = require('path');
const p = process.argv[2] || path.join(__dirname, '..', '..', 'inspection.html');
const src = fs.readFileSync(p, 'utf8');
const a = src.indexOf('var CS_TOOLS = [');
if (a < 0) { console.log('CS_TOOLS not found'); process.exit(1); }
const b = src.indexOf('\n];', a);
const lit = src.slice(a + 'var CS_TOOLS = '.length, b + 2);
let CS_TOOLS; try { CS_TOOLS = eval(lit); } catch (e) { console.log('eval failed: ' + e.message); process.exit(1); }
let total = 0, ph = [];
for (const s of CS_TOOLS) for (const t of s.items) { total++; if (!(t.f || t.fs || t.act)) ph.push(s.sec + '/' + t.id); }
console.log('tools', total, 'placeholders', ph.length, ph.join(' '));
process.exit(ph.length ? 1 : 0);
