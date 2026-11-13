/* 내 꽁밥 캘린더 구독 (owner 2026-11-12; docs/CALENDAR_FEED.md). GET /cal/<token>.ics (vercel.json routes it
 * here as ?t=<token>) answers a calendar file with the starred free-food events of the token's owner, so a
 * phone that subscribed once shows every later star by itself, with an alert 30 minutes before.
 *
 * It reads only public things: the token's list through the anon function calendar_feed_events
 * (supabase/migrations/013_calendar_feed.sql) with the site's publishable key, and the published feed
 * (data/ggongbab/latest.json, archive) for the current time and place of each event. The entries are
 * written by the site's own calendar code (js/ggongbab-select.js, js/ggongbab-live.js), loaded here as is,
 * so a subscribed entry is the same as the one the star's add screen makes.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const KST = 'Asia/Seoul';
// Our own sites only. The request's host decides which of them the calendar reads its feed from and links
// to; any other host (a preview address, or a forged x-forwarded-host) gets the production site, so the
// server never fetches from, or writes links to, an address a request names (security audit 2026-11-13).
const ORIGINS = new Set(['www.babdodukms.com', 'babdodukms.com', 'babdoduk.vercel.app', 'babdoduk-lab.vercel.app']);
const DEFAULT_ORIGIN = 'https://www.babdodukms.com';

function siteOrigin(headers) {
  const h = headers || {};
  const host = String(h['x-forwarded-host'] || h.host || '').split(',')[0].trim().toLowerCase();
  return ORIGINS.has(host) ? 'https://' + host : DEFAULT_ORIGIN;
}

function publicConfig() {
  const text = fs.readFileSync(path.join(ROOT, 'js/ggongbab-public-config.js'), 'utf8');
  const url = (text.match(/SUPABASE_URL:\s*'([^']+)'/) || [])[1];
  const key = (text.match(/SUPABASE_PUBLISHABLE_KEY:\s*'([^']+)'/) || [])[1];
  return { url, key };
}

// The browser modules, run once in a small sandbox with only what they read at load.
let site = null;
function siteCode() {
  if (site) return site;
  const window = { navigator: { userAgent: '' }, document: {}, localStorage: null, location: { origin: '' } };
  const context = vm.createContext({ window, URLSearchParams, Date, Intl, Math, JSON, encodeURIComponent, unescape, escape, console });
  for (const file of ['js/ggongbab-select.js', 'js/ggongbab-live.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, file), 'utf8'), context, { filename: file });
  }
  site = { F: window.BabdodukFreeFood, L: window.BabdodukLive };
  return site;
}

// One VEVENT block per event: the site's own single-event file, without its calendar wrapper.
function eventBlock(ev, origin) {
  const { L } = siteCode();
  const link = origin + '/ggongbab.html?e=' + encodeURIComponent(ev.id);
  const text = L.icsText(ev, { url: link, details: '참여 조건과 변경 사항은 밥도둑에서 확인하세요.\n' + link });
  const start = text.indexOf('BEGIN:VEVENT');
  const end = text.indexOf('END:VEVENT') + 'END:VEVENT'.length;
  return text.slice(start, end);
}

function calendar(blocks, name) {
  const head = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Babdoduk//my-ggongbab//KO', 'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH', 'X-WR-CALNAME:' + name, 'X-WR-TIMEZONE:' + KST,
    // A hint to check often; iPhone decides the actual interval (docs/CALENDAR_FEED.md).
    'REFRESH-INTERVAL;VALUE=DURATION:PT15M', 'X-PUBLISHED-TTL:PT15M'];
  return head.concat(blocks, ['END:VCALENDAR']).join('\r\n') + '\r\n';
}

async function getJson(url, options) {
  try {
    const res = await fetch(url, options);
    return res.ok ? await res.json() : null;
  } catch (err) {
    return null;
  }
}

// Each saved item against the newest public data (the same rule as 마이 밥도둑): the current listing, else
// its archived copy, else the snapshot saved with the star. A deadline-only listing has no time to add.
function entries(saved, feed, archive) {
  const { F, L } = siteCode();
  const live = F.occurrences((feed && feed.events || []).filter(F.isPublic));
  const past = F.occurrences((archive && archive.events || []).filter(F.isPublic));
  const byId = new Map();
  past.concat(live).forEach((ev) => byId.set(ev.id, ev));
  const out = [];
  for (const row of saved || []) {
    const seen = row.seen || {};
    const ev = byId.get(row.event_id) ||
      (seen.startAt ? { id: row.event_id, title: seen.title || '', startAt: seen.startAt, endAt: seen.endAt || null,
        location: seen.place ? { name: String(seen.place) } : null } : null);
    if (ev && L.canCalendar(ev)) out.push(ev);
  }
  return out;
}

async function handler(req, res) {
  const url = new URL(req.url, DEFAULT_ORIGIN);
  const token = url.searchParams.get('t') || '';
  if (!TOKEN.test(token)) { res.statusCode = 404; res.end('not found'); return; }
  const origin = siteOrigin(req.headers);
  const { url: base, key } = publicConfig();
  const saved = await getJson(base + '/rest/v1/rpc/calendar_feed_events', {
    method: 'POST',
    headers: { apikey: key, Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ p_token: token })
  });
  if (!Array.isArray(saved)) { res.statusCode = 503; res.setHeader('Retry-After', '300'); res.end('try again later'); return; }
  // An empty list (or an unknown token) needs no feed: nothing is fetched for it.
  const [feed, archive] = saved.length ? await Promise.all([
    getJson(origin + '/data/ggongbab/latest.json'),
    getJson(origin + '/data/ggongbab/archive/index.json')
  ]) : [null, null];
  const blocks = entries(saved, feed, archive).map((ev) => eventBlock(ev, origin));
  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/calendar; charset=utf-8');
  res.setHeader('Cache-Control', 'private, no-store');
  res.setHeader('X-Robots-Tag', 'noindex');
  res.end(calendar(blocks, '밥도둑 내 꽁밥'));
}

module.exports = handler;
module.exports.entries = entries;
module.exports.calendar = calendar;
module.exports.eventBlock = eventBlock;
module.exports.siteOrigin = siteOrigin;
// The site's own free-food code in Node, also used by the push alert sender (scripts/push/send.js).
module.exports.siteCode = siteCode;
