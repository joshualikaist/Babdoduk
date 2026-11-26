'use strict';

const fs = require('fs');
const path = require('path');
const LAB = 'babdoduk-lab.vercel.app';
const PANES = new Set(['designer1', 'designer2', 'developer1', 'developer2', 'copy1', 'founder1', 'critic']);
// Five reviewers since 2026-11-26 (one designer, one developer); seven for runs started before that.
const KINDS = new Set(['start', 'step', 'say', 'finding', 'comment', 'done']);

function valid(body) {
  if (!body || !Number.isFinite(Date.parse(body.updatedAt))) return false;
  const d = body.timeline;
  if (!d || typeof d.run !== 'string' || !/^[a-f0-9]{16}$/.test(d.run)
      || typeof d.complete !== 'boolean' || !Number.isFinite(d.end) || d.end < 0
      || !Array.isArray(d.panes) || (d.panes.length !== 5 && d.panes.length !== 7)
      || !Array.isArray(d.events) || d.events.length > 10000 || !Array.isArray(d.phases)) return false;
  if (new Set(d.panes.map(p => p && p.id)).size !== d.panes.length
      || !d.panes.every(p => p && PANES.has(p.id) && typeof p.name === 'string' && p.name.length <= 30)) return false;
  let previous = 0;
  return d.events.every(e => {
    const ok = e && Number.isFinite(e.t) && e.t >= previous && e.t <= d.end
      && PANES.has(e.pane) && KINDS.has(e.kind) && typeof e.text === 'string' && e.text.length <= 400;
    if (ok) previous = e.t;
    return ok;
  }) && d.phases.every(p => p && Number.isFinite(p.t) && typeof p.title === 'string' && p.title.length <= 30);
}

async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex, nofollow');
  // Use the actual request host. A supplied forwarding header cannot enable this on production.
  if (String((req.headers || {}).host || '').toLowerCase() !== LAB) {
    res.statusCode = 404; res.end(); return;
  }
  if (req.method !== 'GET') {
    res.statusCode = 405; res.setHeader('Allow', 'GET'); res.end(); return;
  }
  try {
    const text = fs.readFileSync(path.join(__dirname, '../js/ggongbab-public-config.js'), 'utf8');
    const url = (text.match(/SUPABASE_URL:\s*'([^']+)'/) || [])[1];
    if (!url) throw new Error('config');
    const upstream = await fetch(url + '/storage/v1/object/public/panel-live/current.json?v=' + Math.floor(Date.now() / 5000), {
      method: 'GET', cache: 'no-store', signal: AbortSignal.timeout(3000)
    });
    if (!upstream.ok) throw new Error('unavailable');
    const body = await upstream.json();
    if (!valid(body)) throw new Error('invalid');
    // Do not pass unexpected backend columns to the browser.
    const d = body.timeline;
    const timeline = {
      run: d.run, complete: d.complete, end: d.end,
      panes: d.panes.map(p => ({ id: p.id, name: p.name, emoji: String(p.emoji || '').slice(0, 8) })),
      phases: d.phases.map(p => ({ t: p.t, title: p.title })),
      events: d.events.map(e => ({ t: e.t, pane: e.pane, kind: e.kind, text: e.text }))
    };
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    const output = { updatedAt: body.updatedAt, timeline };
    if (body.status && body.status.code === 'rate_limit' && Number.isFinite(Date.parse(body.status.retryAt))) {
      output.status = { code: 'rate_limit', retryAt: body.status.retryAt };
    }
    res.end(JSON.stringify(output));
  } catch (err) {
    res.statusCode = 503; res.setHeader('Retry-After', '5'); res.end();
  }
}

module.exports = handler;
module.exports.valid = valid;
