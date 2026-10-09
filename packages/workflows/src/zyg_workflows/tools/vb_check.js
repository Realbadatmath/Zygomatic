#!/usr/bin/env node

// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* tools/vb_check.js — Voice Bridge registry checker (node 22, no deps).
 *
 *   node tools/vb_check.js voice_ext/<file>.js <view> <min_actions>
 *
 * Evaluates voice_ext/00_core.js and then <file> inside a vm context holding a
 * minimal fake window/document, exactly the way the bundle loads them (top level
 * may only register). Then asserts the registry contract:
 *   - no exception at top level
 *   - at least <min_actions> entries whose view === <view>
 *   - every entry has label, aliases (non-empty array of lower-case strings),
 *     el (function), run (function), say (string of <= 12 words)
 * Prints the count and exits non-zero on any violation.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const CREWS = path.resolve(__dirname, '..');
const CORE = path.join(CREWS, 'voice_ext', '00_core.js');
// The bundle prefixes exactly this line (see _serve_arch_ext_bundle's voice twin).
const BUNDLE_PREFIX = 'window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};';

function fakeElement() {
  const el = {
    id: '', value: '', checked: false, innerHTML: '', textContent: '', className: '',
    style: {}, dataset: {}, children: [], parentNode: null,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { return c; }, removeChild(c) { return c; }, insertBefore(c) { return c; },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    click() {}, focus() {}, blur() {}, scrollIntoView() {},
    getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }; }
  };
  return el;
}

function fakeStorage() {
  const store = new Map();
  return {
    getItem(k) { return store.has(String(k)) ? store.get(String(k)) : null; },
    setItem(k, v) { store.set(String(k), String(v)); },
    removeItem(k) { store.delete(String(k)); },
    clear() { store.clear(); }
  };
}

/** A contextified sandbox that looks just enough like a browser tab. */
function makeSandbox(extra) {
  const sandbox = {};
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.top = sandbox;
  sandbox.console = console;
  sandbox.setTimeout = setTimeout;
  sandbox.clearTimeout = clearTimeout;
  sandbox.setInterval = setInterval;
  sandbox.clearInterval = clearInterval;
  sandbox.queueMicrotask = queueMicrotask;
  sandbox.localStorage = fakeStorage();
  sandbox.sessionStorage = fakeStorage();
  sandbox.location = { href: 'http://127.0.0.1:8899/inspection.html', hash: '', search: '', pathname: '/inspection.html' };
  sandbox.navigator = { userAgent: 'vb_check', mediaDevices: { getUserMedia() { return Promise.reject(new Error('no mic')); } } };
  sandbox.document = {
    readyState: 'loading',
    title: 'vb_check',
    body: fakeElement(),
    head: fakeElement(),
    documentElement: fakeElement(),
    getElementById() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getElementsByClassName() { return []; },
    getElementsByTagName() { return []; },
    createElement() { return fakeElement(); },
    createTextNode() { return fakeElement(); },
    addEventListener() {},
    removeEventListener() {}
  };
  sandbox.addEventListener = function () {};
  sandbox.removeEventListener = function () {};
  sandbox.fetch = function () { return Promise.resolve({ ok: true, status: 200, json() { return Promise.resolve({ ok: true }); }, text() { return Promise.resolve(''); } }); };
  sandbox.alert = function () {};
  sandbox.requestAnimationFrame = function (fn) { return setTimeout(fn, 0); };
  sandbox.cancelAnimationFrame = function (id) { clearTimeout(id); };
  Object.assign(sandbox, extra || {});
  vm.createContext(sandbox);
  return sandbox;
}

/** Run the bundle prefix and each file (absolute paths) in the sandbox, in order. */
function loadFiles(sandbox, files) {
  new vm.Script(BUNDLE_PREFIX, { filename: 'bundle-prefix.js' }).runInContext(sandbox);
  const done = new Set();
  for (const file of files) {
    const abs = path.resolve(file);
    if (done.has(abs)) continue;
    done.add(abs);
    const src = fs.readFileSync(abs, 'utf8');
    new vm.Script(src, { filename: abs }).runInContext(sandbox);
  }
  return sandbox.VB;
}

const WORD_LIMIT = 12;

function wordCount(s) {
  return String(s).trim().split(/\s+/).filter(Boolean).length;
}

/** Validate every registry entry; returns a list of human-readable violations. */
function checkRegistry(VB, view, minActions) {
  const bad = [];
  if (!VB || typeof VB !== 'object') return ['window.VB was not created'];
  const actions = VB.actions || {};
  const names = Object.keys(actions);

  for (const name of names) {
    const spec = actions[name];
    const at = (msg) => bad.push(`${name}: ${msg}`);
    if (!spec || typeof spec !== 'object') { at('is not an object'); continue; }
    if (typeof spec.view !== 'string' || !spec.view.trim()) at('view must be a non-empty string');
    if (typeof spec.label !== 'string' || !spec.label.trim()) at('label must be a non-empty string');

    if (!Array.isArray(spec.aliases) || spec.aliases.length === 0) {
      at('aliases must be a non-empty array');
    } else {
      spec.aliases.forEach((a, i) => {
        if (typeof a !== 'string' || !a.trim()) at(`aliases[${i}] must be a non-empty string`);
        else if (a !== a.toLowerCase()) at(`aliases[${i}] "${a}" must be lower-case`);
      });
    }

    if (typeof spec.el !== 'function') at('el must be a function');
    if (typeof spec.run !== 'function') at('run must be a function');

    if (typeof spec.say !== 'string') at('say must be a string');
    else if (wordCount(spec.say) > WORD_LIMIT) at(`say is ${wordCount(spec.say)} words (max ${WORD_LIMIT})`);
  }

  const inView = names.filter((n) => actions[n] && actions[n].view === view);
  if (inView.length < minActions) {
    bad.push(`only ${inView.length} action(s) with view "${view}", need at least ${minActions}`);
  }
  return bad;
}

function main(argv) {
  const [file, view, minRaw] = argv;
  if (!file || !view || minRaw === undefined) {
    console.error('usage: node tools/vb_check.js voice_ext/<file>.js <view> <min_actions>');
    return 2;
  }
  const minActions = Number(minRaw);
  if (!Number.isFinite(minActions) || minActions < 0) {
    console.error(`vb_check: <min_actions> must be a non-negative number, got "${minRaw}"`);
    return 2;
  }
  const target = path.resolve(file);
  if (!fs.existsSync(target)) {
    console.error(`vb_check: no such file: ${target}`);
    return 2;
  }

  let VB;
  const sandbox = makeSandbox();
  try {
    VB = loadFiles(sandbox, [CORE, target]);
  } catch (err) {
    console.error(`vb_check: top-level exception while loading ${path.basename(target)}: ${err && err.stack ? err.stack : err}`);
    return 1;
  }

  const violations = checkRegistry(VB, view, minActions);
  const actions = (VB && VB.actions) || {};
  const names = Object.keys(actions);
  const inView = names.filter((n) => actions[n] && actions[n].view === view);

  console.log(`vb_check ${path.relative(CREWS, target)}: ${names.length} action(s) registered, ${inView.length} in view "${view}" (min ${minActions})`);
  if (inView.length) console.log(`  ${inView.sort().join(', ')}`);

  if (violations.length) {
    console.error(`vb_check: ${violations.length} violation(s)`);
    violations.forEach((v) => console.error(`  - ${v}`));
    return 1;
  }
  console.log('vb_check: OK');
  return 0;
}

module.exports = { makeSandbox, loadFiles, checkRegistry, fakeElement, fakeStorage, CORE, BUNDLE_PREFIX };

if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}
