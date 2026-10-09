// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* tests/vb_core.test.js — Voice Bridge core executor.
 * Run: node --test tests/vb_core.test.js
 * No browser, no network: 00_core.js is loaded into the vb_check vm sandbox with a
 * fake fetch and a fake EventSource.
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const { makeSandbox, loadFiles, CORE } = require('../tools/vb_check.js');

/** Load the core with a recording fetch; returns {VB, posts}. */
function boot(extra) {
  const posts = [];
  const sandbox = makeSandbox(Object.assign({
    fetch(url, opt) {
      let body = null;
      try { body = JSON.parse((opt && opt.body) || 'null'); } catch (e) { body = null; }
      posts.push({ url, body });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    }
  }, extra || {}));
  const VB = loadFiles(sandbox, [CORE]);
  return { VB, posts, sandbox };
}

function action(tag, run) {
  return {
    view: 'home',
    label: 'test ' + tag,
    aliases: ['test ' + tag],
    args: null,
    el() { return null; },
    run,
    say: 'done'
  };
}

const settle = () => new Promise((r) => setTimeout(r, 25));

test('core loads and registers its own actions', () => {
  const { VB } = boot();
  assert.strictEqual(typeof VB.exec, 'function');
  assert.strictEqual(VB.state, 'idle');
  assert.strictEqual(VB.currentView(), 'home');
  const names = VB.registry().map((r) => r.name);
  assert.ok(names.includes('core.stop'), 'core.stop is registered');
  assert.ok(names.includes('core.say'), 'core.say is registered');
  assert.strictEqual(VB.aliases['stop'], 'core.stop');
});

test('exec de-duplicates on action id: the same id runs once', async () => {
  const { VB } = boot();
  let runs = 0;
  VB.actions['test.count'] = action('count', () => { runs += 1; return 'counted'; });

  const first = await VB.exec({ id: 'dup-1', name: 'test.count' });
  const second = await VB.exec({ id: 'dup-1', name: 'test.count' });

  assert.strictEqual(runs, 1, 'run() fired exactly once for two identical ids');
  assert.strictEqual(first.ok, true);
  assert.strictEqual(second.duplicate, true);
});

test('unknown action is acked with ok:false / "unknown action"', async () => {
  const { VB, posts } = boot();
  const result = await VB.exec({ id: 'unknown-1', name: 'nope.nope' });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'unknown action');

  await settle();
  const ack = posts.find((p) => p.url === '/inspect/api/voice/ack' && p.body && p.body.id === 'unknown-1');
  assert.ok(ack, 'an ack was POSTed to /inspect/api/voice/ack');
  assert.strictEqual(ack.body.ok, false);
  assert.strictEqual(ack.body.error, 'unknown action');
  assert.strictEqual(ack.body.view, 'home');
});

test('a successful action acks ok:true with detail and view', async () => {
  const { VB, posts } = boot();
  VB.actions['test.ok'] = action('ok', () => 'all good');
  const result = await VB.exec({ id: 'ok-1', name: 'test.ok' });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.detail, 'all good');

  await settle();
  const ack = posts.find((p) => p.url === '/inspect/api/voice/ack' && p.body && p.body.id === 'ok-1');
  assert.ok(ack, 'success acked');
  assert.strictEqual(ack.body.ok, true);
  assert.strictEqual(ack.body.detail, 'all good');
  assert.strictEqual(ack.body.view, 'home');
  assert.strictEqual(ack.body.say, 'done');
});

test('a throwing action acks ok:false with the message', async () => {
  const { VB, posts } = boot();
  VB.actions['test.boom'] = action('boom', () => { throw new Error('knob not found'); });
  const result = await VB.exec({ id: 'boom-1', name: 'test.boom' });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'knob not found');

  await settle();
  const ack = posts.find((p) => p.url === '/inspect/api/voice/ack' && p.body && p.body.id === 'boom-1');
  assert.ok(ack);
  assert.strictEqual(ack.body.error, 'knob not found');
});

test('actions run strictly one after another', async () => {
  const { VB } = boot();
  const order = [];
  const slow = (tag, ms) => action(tag, () => new Promise((resolve) => {
    order.push('start:' + tag);
    setTimeout(() => { order.push('end:' + tag); resolve(tag); }, ms);
  }));

  VB.actions['test.a'] = slow('a', 40);   // the slowest is queued first on purpose
  VB.actions['test.b'] = slow('b', 10);
  VB.actions['test.c'] = slow('c', 1);

  await Promise.all([
    VB.exec({ id: 'ser-1', name: 'test.a' }),
    VB.exec({ id: 'ser-2', name: 'test.b' }),
    VB.exec({ id: 'ser-3', name: 'test.c' })
  ]);

  assert.deepStrictEqual(order, ['start:a', 'end:a', 'start:b', 'end:b', 'start:c', 'end:c']);
});

test('core.stop aborts the queue and says nothing', async () => {
  const { VB } = boot();
  let ran = 0;
  VB.actions['test.slow'] = action('slow', () => new Promise((r) => setTimeout(r, 20)));
  VB.actions['test.later'] = action('later', () => { ran += 1; });

  const slow = VB.exec({ id: 'stop-1', name: 'test.slow' });
  const later = VB.exec({ id: 'stop-2', name: 'test.later' });
  const stop = await VB.exec({ id: 'stop-3', name: 'core.stop' });   // jumps the queue

  const dropped = await later;
  await slow;
  await settle();

  assert.strictEqual(ran, 0, 'the queued action never ran');
  assert.strictEqual(stop.ok, true);
  assert.strictEqual(stop.detail, 'dropped 1');
  assert.strictEqual(stop.say, '', 'core.stop says nothing');
  assert.strictEqual(dropped.ok, false);
  assert.strictEqual(dropped.error, 'aborted');
  assert.strictEqual(VB.actions['core.stop'].say, '');
});

test('SSE: the driver tab connects and runs an action event once', async () => {
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.handlers = {};
      this.closed = false;
      FakeEventSource.last = this;
    }
    addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); }
    close() { this.closed = true; }
    fire(type, data) {
      (this.handlers[type] || []).forEach((fn) => fn({ data: JSON.stringify(data) }));
    }
  }

  const store = new Map([['vb.driver', 'tok-42']]);
  const { VB } = boot({
    EventSource: FakeEventSource,
    localStorage: {
      getItem: (k) => (store.has(String(k)) ? store.get(String(k)) : null),
      setItem: (k, v) => store.set(String(k), String(v)),
      removeItem: (k) => store.delete(String(k))
    }
  });

  assert.strictEqual(VB.driver, 'tok-42', 'driver token read from localStorage');
  const es = VB.connect();
  assert.ok(es, 'EventSource opened');
  assert.strictEqual(es.url, '/inspect/api/voice/events?driver=tok-42');

  let hits = 0;
  let spoken = null;
  VB.speak = (text) => { spoken = text; };
  VB.actions['test.sse'] = action('sse', () => { hits += 1; });

  es.fire('action', { id: 'sse-1', name: 'test.sse' });
  es.fire('action', { id: 'sse-1', name: 'test.sse' });   // same id: dropped
  es.fire('say', { id: 'say-1', text: 'ready in 2 seconds' });
  await settle();

  assert.strictEqual(hits, 1, 'the duplicated SSE action ran once');
  assert.strictEqual(spoken, 'ready in 2 seconds');
});

test('registry() summarises name, view, label, aliases, args', () => {
  const { VB } = boot();
  const entry = VB.registry().find((r) => r.name === 'core.say');
  assert.deepStrictEqual(Object.keys(entry).sort(), ['aliases', 'args', 'label', 'name', 'view']);
  assert.strictEqual(entry.view, 'home');
  assert.ok(Array.isArray(entry.aliases) && entry.aliases.length > 0);
  assert.ok(entry.args && typeof entry.args.text === 'string');
});

test('waitFor resolves when the predicate turns truthy and rejects on timeout', async () => {
  const { VB } = boot();
  let flag = null;
  setTimeout(() => { flag = 'here'; }, 60);
  assert.strictEqual(await VB.waitFor(() => flag, 1000), 'here');
  await assert.rejects(() => VB.waitFor(() => null, 120), /timed out/);
});

test('boot() runs VB.ready callbacks once and the DRIVER tab posts hello with the registry', async () => {
  const { VB, posts } = boot();
  VB.driver = 'tok-boot';          // this tab holds the token
  let calls = 0;
  VB.ready.push(() => { calls += 1; });
  VB.boot();
  VB.boot();                       // idempotent
  assert.strictEqual(calls, 1);

  await settle();
  const hello = posts.find((p) => p.url === '/inspect/api/voice/hello');
  assert.ok(hello, 'hello POSTed');
  assert.strictEqual(hello.body.driver, 'tok-boot');
  assert.strictEqual(hello.body.view, 'home');
  assert.ok(Array.isArray(hello.body.registry));
  assert.ok(hello.body.registry.some((r) => r.name === 'core.stop'));
});

// A watcher tab has no token; the server keys the registry on one and answers
// 400 without it, so the handshake stays silent exactly like VB.connect does.
test('a watcher tab (no driver token) posts no hello at all', async () => {
  const { VB, posts } = boot();
  assert.strictEqual(VB.driver, null);
  VB.boot();
  VB.helloView();
  await settle();
  assert.deepStrictEqual(posts.filter((p) => p.url === '/inspect/api/voice/hello'), []);
});

test('the checker itself passes on 00_core.js', () => {
  assert.ok(path.isAbsolute(CORE));
  const { checkRegistry } = require('../tools/vb_check.js');
  const { VB } = boot();
  assert.deepStrictEqual(checkRegistry(VB, 'home', 0), []);
});
