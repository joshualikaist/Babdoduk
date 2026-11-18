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

// An old address (017_calendar_leftover.sql; owner 2026-11-19, "구독은 쌓여"): a website cannot delete a phone's
// subscription, so the calendar left behind by a newer connection shows one all-day notice, today, asking to
// delete it, and no alert. The same id every time, so it never multiplies.
const RETIRED = 'babdoduk:retired';
const RETIRED_NAME = '밥도둑 지난 구독 · 지워 주세요';
function icsEscape(text) {
  return String(text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\r|\n/g, '\\n');
}
// RFC 5545 folds content lines at 75 octets; never split a character.
function fold(line) {
  const out = [];
  let cur = '', bytes = 0;
  for (const ch of line) {
    const size = Buffer.byteLength(ch);
    if (bytes + size > (out.length ? 74 : 75)) { out.push(cur); cur = ''; bytes = 0; }
    cur += ch; bytes += size;
  }
  out.push(cur);
  return out.join('\r\n ');
}
function kstDate(ms) {
  const d = new Date(ms + 9 * 3600000);
  return d.getUTCFullYear() + String(d.getUTCMonth() + 1).padStart(2, '0') + String(d.getUTCDate()).padStart(2, '0');
}
function retiredBlock(nowMs) {
  const stamp = new Date(nowMs).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return ['BEGIN:VEVENT', 'UID:retired-subscription@babdodukms.com', 'DTSTAMP:' + stamp,
    'DTSTART;VALUE=DATE:' + kstDate(nowMs), 'DTEND;VALUE=DATE:' + kstDate(nowMs + 86400000),
    'SUMMARY:' + icsEscape(RETIRED_NAME),
    'DESCRIPTION:' + icsEscape('더 이상 쓰지 않는 예전 구독이에요. 새 연결은 그대로 작동해요.\n' +
      '캘린더 앱 아래쪽 "캘린더"에서 이 캘린더 옆 ⓘ를 눌러 맨 아래 빨간 버튼으로 지워 주세요.'),
    'TRANSP:TRANSPARENT', 'END:VEVENT'].map(fold).join('\r\n');
}

// The iPhone connection as a configuration profile (owner 2026-11-19: "구독은 쌓여 ... 다른 방식을 찾아내봐").
// A webcal subscription cannot be removed by a website, so every second 연결 left one more calendar behind. A
// profile's top-level PayloadIdentifier decides "whether a new profile should replace an existing one or should
// be added" (Apple, Configuration Profile Reference), so this one identifier, the same for every account and
// site, makes a second install replace the first: the phone always holds exactly one 밥도둑 calendar, and
// removing the profile in Settings removes it. The payload is Apple's calendar subscription
// (com.apple.subscribedcalendar.account, iPhone and iPad only) pointing at this account's private address.
const PROFILE_ID = 'com.babdodukms.calendar';
function xml(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
// A stable UUID per address and part, so the same address always gives the same profile.
function uuidOf(seed) {
  const h = require('crypto').createHash('sha256').update(seed).digest('hex');
  return [h.slice(0, 8), h.slice(8, 12), '4' + h.slice(13, 16), ((parseInt(h[16], 16) & 3) | 8).toString(16) + h.slice(17, 20),
    h.slice(20, 32)].join('-').toUpperCase();
}
function profile(token, origin) {
  const feed = origin + '/cal/' + token + '.ics';
  const s = (key, value) => '<key>' + key + '</key><string>' + xml(value) + '</string>';
  return '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n' +
    '<plist version="1.0"><dict>' +
    '<key>PayloadContent</key><array><dict>' +
    s('PayloadType', 'com.apple.subscribedcalendar.account') + '<key>PayloadVersion</key><integer>1</integer>' +
    s('PayloadIdentifier', PROFILE_ID + '.subscription') + s('PayloadUUID', uuidOf('sub:' + feed)) +
    s('PayloadDisplayName', '밥도둑 꽁밥') + s('SubCalAccountDescription', '밥도둑 꽁밥') +
    s('SubCalAccountHostName', feed) + '<key>SubCalAccountUseSSL</key><true/>' +
    '</dict></array>' +
    s('PayloadDisplayName', '밥도둑 캘린더') +
    s('PayloadDescription', '별 누른 꽁밥이 아이폰 캘린더에 들어가요. 다시 설치하면 예전 것을 바꿔서 하나만 남아요.') +
    s('PayloadIdentifier', PROFILE_ID) + s('PayloadOrganization', '밥도둑') +
    '<key>PayloadRemovalDisallowed</key><false/>' + s('PayloadType', 'Configuration') +
    s('PayloadUUID', uuidOf('profile:' + feed)) + '<key>PayloadVersion</key><integer>1</integer>' +
    '</dict></plist>\n';
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
  // The profile only wraps the address: nothing is read for it, and it counts as no calendar read.
  if (url.searchParams.get('profile') === '1') {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/x-apple-aspen-config; charset=utf-8');
    res.setHeader('Content-Disposition', 'attachment; filename="babdoduk-calendar.mobileconfig"');
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Robots-Tag', 'noindex');
    res.end(profile(token, origin));
    return;
  }
  const { url: base, key } = publicConfig();
  const saved = await getJson(base + '/rest/v1/rpc/calendar_feed_events', {
    method: 'POST',
    headers: { apikey: key, Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ p_token: token })
  });
  if (!Array.isArray(saved)) { res.statusCode = 503; res.setHeader('Retry-After', '300'); res.end('try again later'); return; }
  if (saved.some((row) => row && row.event_id === RETIRED)) {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'text/calendar; charset=utf-8');
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Robots-Tag', 'noindex');
    res.end(calendar([retiredBlock(Date.now())], RETIRED_NAME));
    return;
  }
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
module.exports.retiredBlock = retiredBlock;
module.exports.profile = profile;
module.exports.PROFILE_ID = PROFILE_ID;
// The site's own free-food code in Node, also used by the push alert sender (scripts/push/send.js).
module.exports.siteCode = siteCode;
