#!/usr/bin/env node

// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * driver.js — operate a Nomologin persona's already-signed-in Chrome.
 *
 * ATTACHES, never launches. The browser is one the operator signed into by hand and may
 * still be using; puppeteer.connect + browser.disconnect() is the whole contract. Calling
 * browser.close() here would shut a live window in someone's face, so it is never called.
 *
 * Batch CLI, not a service. One invocation runs many actions over one connection, which
 * pays Node's ~250 ms startup once without adding a supervised process, a hub port or a
 * systemd unit to a stack that has been bitten by service-environment bugs before.
 *
 *   node driver.js <debug-port> '<json>'        # {"actions":[{...},...]}  or  {...}
 *
 * Every action returns a plain object; failures return {error} in place, so one bad step
 * in a batch does not lose the results of the steps that already ran.
 */

import puppeteer from 'puppeteer-core';

const PORT = process.argv[2];
const RAW = process.argv[3] || '{}';

// Typing delay per keystroke. Not disguise: controlled React inputs and fields with
// per-key validation silently drop a value set all at once — the field looks filled and
// submits empty.
const KEY_DELAY = Number(process.env.ZYG_NOMOLOGIN_KEY_DELAY || 45);
const NAV_TIMEOUT = Number(process.env.ZYG_NOMOLOGIN_NAV_TIMEOUT || 45000);

/* Enumerating what a person could actually click, per frame. Runs inside the page.
   Cross-origin iframes are why this is a frame-level function rather than one pass over
   the top document: consent walls and embedded composers live in them, and a driver that
   cannot see into them is blind exactly where posting flows get stuck. */
const ENUMERATE = () => {
  const SEL = ['a', 'button', 'input', 'textarea', 'select', 'summary',
    '[role=button]', '[role=link]', '[role=textbox]', '[role=searchbox]',
    '[role=combobox]', '[role=checkbox]', '[role=radio]', '[role=switch]',
    '[role=tab]', '[role=menuitem]', '[role=option]',
    '[contenteditable=""]', '[contenteditable=true]'].join(',');
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 90);
  const label = (el) => {
    // A password's value never leaves the page.
    const v = el.type === 'password' ? '' : el.value || '';
    for (const b of [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
      clean(el.innerText), v, el.getAttribute('title'), el.getAttribute('alt'),
      el.getAttribute('name')]) {
      if (b && clean(b)) return clean(b);
    }
    return '';
  };
  const cssPath = (el) => {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) {
      return '#' + CSS.escape(el.id);
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      if (cur.id) { parts.unshift('#' + CSS.escape(cur.id)); break; }
      let seg = cur.tagName.toLowerCase();
      const nm = cur.getAttribute('name');
      if (nm) seg += '[name="' + nm.replace(/"/g, '\\"') + '"]';
      else {
        const p = cur.parentElement;
        if (p) {
          const sibs = Array.from(p.children).filter((c) => c.tagName === cur.tagName);
          if (sibs.length > 1) seg += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
        }
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  };
  const out = [];
  document.querySelectorAll(SEL).forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 3 || r.height < 3) return;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return;
    if (parseFloat(st.opacity) === 0) return;
    out.push({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || el.getAttribute('role') || '',
      label: label(el),
      sel: cssPath(el),
      inview: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
      disabled: !!el.disabled,
    });
  });
  return {
    url: location.href,
    title: document.title,
    scroll: Math.round(scrollY),
    height: Math.round(document.body ? document.body.scrollHeight : 0),
    elements: out.slice(0, 200),
  };
};

async function pages(browser) {
  const ps = await browser.pages();
  return ps.filter((p) => !p.url().startsWith('devtools://'));
}

/* Which tab to act on. An index is positional; `match` is a substring of url or title and
   is what the assistant should prefer — tab order changes when the operator clicks. */
async function pick(browser, spec) {
  const ps = await pages(browser);
  if (!ps.length) throw new Error('no open tabs — Open the persona first');
  if (spec === undefined || spec === null || spec === '') return ps[0];
  if (typeof spec === 'number' || /^\d+$/.test(String(spec))) {
    const i = Number(spec);
    if (i < 0 || i >= ps.length) throw new Error(`tab ${i} does not exist (${ps.length} open)`);
    return ps[i];
  }
  const needle = String(spec).toLowerCase();
  for (const p of ps) {
    if (p.url().toLowerCase().includes(needle)) return p;
    if ((await p.title()).toLowerCase().includes(needle)) return p;
  }
  throw new Error(`no tab matching ${JSON.stringify(String(spec))}`);
}

/* Elements across every frame, numbered in one flat list. The index the assistant clicks
   carries its frame with it. */
async function survey(page) {
  const frames = page.frames();
  const all = [];
  let top = null;
  for (let fi = 0; fi < frames.length; fi++) {
    let got;
    try {
      got = await frames[fi].evaluate(ENUMERATE);
    } catch {
      continue;                     // a frame can navigate out from under the evaluate
    }
    if (fi === 0) top = got;
    for (const el of got.elements) {
      all.push({ i: all.length, frame: fi, ...el });
    }
  }
  return {
    url: page.url(),
    title: await page.title(),
    scroll: top ? top.scroll : 0,
    height: top ? top.height : 0,
    frames: frames.length,
    elements: all,
  };
}

/* Resolve an index back to a live handle. Re-surveys rather than trusting a stale list and
   refuses when the element under that index is no longer the one described — a page that
   repaints between look and click is the normal case, and a silently shifted index clicks
   the wrong thing on a live signed-in session. */
async function handleFor(page, a) {
  if (a.selector) {
    for (const f of page.frames()) {
      const h = await f.$(a.selector).catch(() => null);
      if (h) return { handle: h, label: a.selector };
    }
    throw new Error(`no element matches ${a.selector} — read the page again`);
  }
  const s = await survey(page);
  const el = s.elements[a.index];
  if (!el) throw new Error(`element ${a.index} does not exist (${s.elements.length} on the page)`);
  if (a.expect && !(el.label || '').toLowerCase().includes(String(a.expect).toLowerCase())) {
    throw new Error(`element ${a.index} is now ${el.tag} ${JSON.stringify(el.label)}, `
      + `not ${JSON.stringify(a.expect)} — the page changed, read it again`);
  }
  if (el.disabled) throw new Error(`element ${a.index} (${JSON.stringify(el.label)}) is disabled`);
  const frame = page.frames()[el.frame];
  const h = await frame.$(el.sel);
  if (!h) throw new Error(`element ${a.index} vanished between reading and clicking`);
  return { handle: h, label: el.label };
}

const ACTIONS = {
  async status(browser) {
    const ps = await pages(browser);
    return {
      connected: true,
      version: await browser.version(),
      tabs: await Promise.all(ps.map(async (p, i) => ({ i, url: p.url(), title: await p.title() }))),
    };
  },

  async tabs(browser) {
    const ps = await pages(browser);
    return Promise.all(ps.map(async (p, i) => ({ i, url: p.url(), title: await p.title() })));
  },

  async navigate(browser, a) {
    const page = await pick(browser, a.tab);
    let url = a.url;
    if (!/^https?:\/\//.test(url)) url = 'https://' + url;
    // domcontentloaded, not networkidle: a social feed never goes idle, and waiting for it
    // means every navigate burns the full timeout before returning a page that was ready.
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
    await new Promise((r) => setTimeout(r, 800));
    return { url: page.url(), title: await page.title() };
  },

  async state(browser, a) {
    return survey(await pick(browser, a.tab));
  },

  async text(browser, a) {
    const page = await pick(browser, a.tab);
    const limit = a.limit || 12000;
    let txt = await page.evaluate(() => (document.body ? document.body.innerText : ''));
    txt = txt.replace(/\n{3,}/g, '\n\n');
    return {
      url: page.url(), title: await page.title(), chars: txt.length,
      truncated: txt.length > limit, text: txt.slice(0, limit),
    };
  },

  async shot(browser, a) {
    const page = await pick(browser, a.tab);
    await page.screenshot({ path: a.path, fullPage: !!a.full });
    return { path: a.path, url: page.url() };
  },

  async click(browser, a) {
    const page = await pick(browser, a.tab);
    if (a.x !== undefined && a.y !== undefined) {
      await page.mouse.move(a.x, a.y);
      await page.mouse.click(a.x, a.y);
      await new Promise((r) => setTimeout(r, 400));
      return { clicked: `(${a.x},${a.y})`, url: page.url() };
    }
    const { handle, label } = await handleFor(page, a);
    await handle.scrollIntoViewIfNeeded().catch(() => {});
    await handle.hover().catch(() => {});
    await handle.click();            // real CDP input events, at the element's own frame
    await new Promise((r) => setTimeout(r, 400));
    return { clicked: label, url: page.url() };
  },

  async type(browser, a) {
    const page = await pick(browser, a.tab);
    if (a.index !== undefined || a.selector) {
      const { handle } = await handleFor(page, a);
      await handle.scrollIntoViewIfNeeded().catch(() => {});
      await handle.click();
      if (a.clear !== false) {
        // Select-all then type: .value = '' skips the input events a controlled component
        // listens for, and the field reverts on the next render.
        await handle.evaluate((el) => {
          if (el.select) el.select();
          else if (el.isContentEditable) document.execCommand('selectAll');
        });
        await page.keyboard.press('Backspace');
      }
    }
    await page.keyboard.type(String(a.text), { delay: a.human === false ? 0 : KEY_DELAY });
    if (a.enter) await page.keyboard.press('Enter');
    await new Promise((r) => setTimeout(r, 300));
    const now = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return null;
      if (el.type === 'password') return '(password)';
      return String(el.value !== undefined ? el.value : el.textContent || '').slice(0, 120);
    });
    return { typed: String(a.text).length, field_now: now, url: page.url() };
  },

  async press(browser, a) {
    const page = await pick(browser, a.tab);
    await page.keyboard.press(a.key);
    await new Promise((r) => setTimeout(r, 300));
    return { pressed: a.key, url: page.url() };
  },

  async scroll(browser, a) {
    const page = await pick(browser, a.tab);
    const dy = a.dy === undefined ? 600 : a.dy;
    await page.mouse.wheel({ deltaY: dy });
    await new Promise((r) => setTimeout(r, 400));
    return page.evaluate(() => ({
      scroll: Math.round(scrollY),
      height: Math.round(document.body ? document.body.scrollHeight : 0),
    }));
  },

  async wait(browser, a) {
    const page = await pick(browser, a.tab);
    const timeout = a.timeout || 20000;
    try {
      await page.waitForSelector(a.selector, { timeout, visible: true });
      return { found: true };
    } catch {
      // Not an error: "the button never appeared" is information to act on.
      return { found: false, waited: timeout, url: page.url() };
    }
  },

  async back(browser, a) {
    const page = await pick(browser, a.tab);
    await page.goBack({ waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT }).catch(() => {});
    return { url: page.url(), title: await page.title() };
  },

  async sleep(browser, a) {
    await new Promise((r) => setTimeout(r, Math.min(a.ms || 1000, 30000)));
    return { slept: a.ms || 1000 };
  },
};

async function main() {
  if (!PORT) {
    console.log(JSON.stringify({ ok: false, error: 'usage: driver.js <debug-port> <json>' }));
    process.exit(2);
  }
  let spec;
  try {
    spec = JSON.parse(RAW);
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: `bad json: ${e.message}` }));
    process.exit(2);
  }
  const actions = spec.actions || [spec];

  let browser;
  try {
    browser = await puppeteer.connect({
      browserURL: `http://127.0.0.1:${PORT}`,
      // null keeps the operator's own window size. A viewport override would visibly
      // resize a window someone is looking at.
      defaultViewport: null,
    });
  } catch (e) {
    console.log(JSON.stringify({
      ok: false,
      error: `cannot reach the browser on 127.0.0.1:${PORT} (${e.message}) — the persona `
        + 'is not open, or was opened before browser control existed; Stop it and Open it again',
    }));
    process.exit(1);
  }

  const results = [];
  try {
    for (const a of actions) {
      const fn = ACTIONS[a.action];
      if (!fn) { results.push({ action: a.action, error: `unknown action ${a.action}` }); continue; }
      try {
        results.push({ action: a.action, ...(await fn(browser, a)) });
      } catch (e) {
        // In place, so one bad step does not lose the steps that already ran.
        results.push({ action: a.action, error: e.message });
      }
    }
  } finally {
    // disconnect, NEVER close: this is the operator's live window.
    browser.disconnect();
  }
  console.log(JSON.stringify({ ok: true, results }, null, 2));
}

main().catch((e) => {
  console.log(JSON.stringify({ ok: false, error: e.message }));
  process.exit(1);
});
