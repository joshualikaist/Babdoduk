#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const webpush = require('./webpush');
const { siteCode } = require('../../api/cal');

const ROOT = path.join(__dirname, '..', '..');
const LEAD_MS = 30 * 60 * 1000;
const KEEP_MS = 2 * 24 * 3600 * 1000;
const DROP_AFTER = 10;
const PAGE = 1000;
const MAX_PAGES = 100;
const SUBJECT = 'https://www.babdodukms.com';
const FEEDS = ['https://www.babdodukms.com/data/ggongbab/latest.json', 'https://babdoduk-lab.vercel.app/data/ggongbab/latest.json'];

// ---- what is due ----------------------------------------------------------------------------------------
function dueEvents(feed, nowMs) {
  const { F, L } = siteCode();
  return F.occurrences(((feed && feed.events) || []).filter(F.isPublic)).filter((ev) => {
    const start = Date.parse(ev.startAt);
    return L.canCalendar(ev) && !isNaN(start) && start - LEAD_MS <= nowMs && nowMs < start;
  });
}

function kstTime(iso) {
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })
    .format(new Date(iso));
}

function message(ev, device, nowMs) {
  const { L } = siteCode();
  const mins = Math.max(1, Math.round((Date.parse(ev.startAt) - nowMs) / 60000));
  const place = L.placeText(ev);
  const en = device.lang === 'en';
  const when = en ? 'Starts in ' + mins + ' min · ' + kstTime(ev.startAt) : mins + '분 뒤 시작 · ' + kstTime(ev.startAt);
  return {
    title: '🍚 ' + String(ev.title || (en ? 'Free food' : '꽁밥')).slice(0, 80),
    body: (place ? when + ' · ' + place : when).slice(0, 200),
    url: device.site + '/ggongbab.html?e=' + encodeURIComponent(ev.id),
    tag: 'gg-' + ev.id
  };
}

// ---- local record of what went out -------------------------------------------------------------------------
function hashOf(endpoint) { return crypto.createHash('sha256').update(endpoint).digest('hex').slice(0, 24); }
function sentKey(device, ev) { return hashOf(device.endpoint) + '|' + ev.id + '|' + Date.parse(ev.startAt); }

function readSent(file) {
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
  } catch (err) {
    return {};
  }
}
function writeSent(file, sent, nowMs) {
  const keep = {};
  for (const [key, at] of Object.entries(sent)) if (nowMs - Date.parse(at) < KEEP_MS) keep[key] = at;
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(keep), { mode: 0o600 });
  fs.renameSync(tmp, file);
}

// ---- the database (backend key; never printed) ----------------------------------------------------------
function db(env, fetchImpl) {
  const base = env.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/push_devices';
  const headers = { apikey: env.SUPABASE_SECRET_KEY, Authorization: 'Bearer ' + env.SUPABASE_SECRET_KEY };
  const where = (endpoint) => '?endpoint=eq.' + encodeURIComponent(endpoint);
  return {
    async devicesFor(ids) {
      const list = '{' + ids.map((id) => '"' + id + '"').join(',') + '}';
      const query = base + '?select=endpoint,p256dh,auth,events,lang,site,failures&events=ov.' + encodeURIComponent(list) +
        '&order=endpoint.asc&limit=' + PAGE + '&offset=';
      const out = [];
      for (let pages = 0; pages < MAX_PAGES; pages++) {
        const res = await fetchImpl(query + out.length, { headers });
        if (!res.ok) throw new Error('devices: HTTP ' + res.status);
        const page = await res.json();
        if (!Array.isArray(page)) throw new Error('devices: not a list');
        out.push(...page);
        if (page.length < PAGE) return out;
      }
      throw new Error('devices: more than ' + PAGE * MAX_PAGES + ' rows');
    },
    async forget(endpoint) {
      await fetchImpl(base + where(endpoint), { method: 'DELETE', headers });
    },
    async refused(device) {
      if (device.failures + 1 >= DROP_AFTER) return this.forget(device.endpoint);
      await fetchImpl(base + where(device.endpoint), {
        method: 'PATCH', headers: Object.assign({ 'Content-Type': 'application/json' }, headers),
        body: JSON.stringify({ failures: device.failures + 1 })
      });
    }
  };
}

async function readFeed(fetchImpl, urls) {
  for (const url of urls) {
    try {
      const res = await fetchImpl(url, { headers: { 'Cache-Control': 'no-cache' } });
      if (res.ok) return await res.json();
    } catch (err) {  }
  }
  return null;
}

async function run({ nowMs, fetchImpl, env, keys, sentFile, feeds = FEEDS, dryRun = false, log = console.log }) {
  const summary = { due: 0, devices: 0, sent: 0, gone: 0, refused: 0, later: 0 };
  const feed = await readFeed(fetchImpl, feeds);
  if (!feed) { log('push: the public feed could not be read; trying again next run'); summary.feed = false; return summary; }
  const due = dueEvents(feed, nowMs);
  summary.due = due.length;
  if (!due.length) return summary;
  const store = db(env, fetchImpl);
  const devices = await store.devicesFor(due.map((ev) => ev.id));
  summary.devices = devices.length;
  const sent = readSent(sentFile);
  try {
  for (const device of devices) {
    const wanted = new Set(device.events || []);
    for (const ev of due) {
      if (!wanted.has(ev.id) || sent[sentKey(device, ev)]) continue;
      const msg = message(ev, device, nowMs);
      if (dryRun) { log('push (dry run): ' + hashOf(device.endpoint).slice(0, 8) + ' ← ' + msg.title + ' / ' + msg.body); continue; }
      let req = null;
      try { req = webpush.pushRequest(device, msg, keys, SUBJECT, { ttl: (Date.parse(ev.startAt) - nowMs) / 1000, now: nowMs }); }
      catch (err) { req = null; }
      let status = 400;
      if (req) {
        try { status = (await fetchImpl(req.url, Object.assign({ signal: AbortSignal.timeout(10000) }, req.init))).status; }
        catch (err) { status = 0; }
      }
      if (status >= 200 && status < 300) {
        sent[sentKey(device, ev)] = new Date(nowMs).toISOString();
        summary.sent++;
      } else if (status === 404 || status === 410) {
        await quietly(() => store.forget(device.endpoint));
        summary.gone++;
        break;
      } else if (status === 400 || status === 403 || status === 413) {
        sent[sentKey(device, ev)] = new Date(nowMs).toISOString();
        await quietly(() => store.refused(device));
        summary.refused++;
      } else {
        summary.later++;
      }
    }
  }
  } finally {
    if (!dryRun) writeSent(sentFile, sent, nowMs);
  }
  return summary;
}

async function quietly(fn) {
  try { await fn(); return true; } catch (err) { return false; }
}

// ---- the ops computer's setup -----------------------------------------------------------------------------
function readEnv(file) {
  const out = {};
  try {
    for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
      const m = line.match(/^\s*(SUPABASE_URL|SUPABASE_SECRET_KEY)\s*=\s*(.*?)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2');
    }
  } catch (err) {  }
  for (const name of ['SUPABASE_URL', 'SUPABASE_SECRET_KEY']) if (process.env[name]) out[name] = process.env[name];
  return out;
}
function keyFile() {
  return process.env.BABDODUK_PUSH_KEYS || path.join(os.homedir(), '.config/babdoduk/credentials/babdoduk_push-vapid');
}

async function main(argv) {
  const dryRun = argv.includes('--dry-run');
  const env = readEnv(process.env.BABDODUK_ENV || path.join(ROOT, '.env'));
  if (!env.SUPABASE_URL || !env.SUPABASE_SECRET_KEY) { console.error('push: SUPABASE_URL or SUPABASE_SECRET_KEY is missing in .env'); return 1; }
  let keys;
  try { keys = JSON.parse(fs.readFileSync(keyFile(), 'utf8')); } catch (err) {
    console.error('push: no key file; run scripts/push/keygen.js once (docs/PUSH_ALERTS.md)');
    return 1;
  }
  const summary = await run({
    nowMs: Date.now(), fetchImpl: fetch, env, keys, dryRun,
    sentFile: process.env.BABDODUK_PUSH_SENT || path.join(ROOT, '.local/push/sent.json')
  });
  if (summary.due || summary.feed === false) console.log('push: ' + JSON.stringify(summary));
  return 0;
}

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (err) => {
    console.error('push: ' + String(err && err.message || err).replace(/sb_secret_[A-Za-z0-9_-]+/g, '[key]'));
    process.exitCode = 1;
  });
}

module.exports = { dueEvents, message, run, readEnv, sentKey, LEAD_MS, PAGE };
