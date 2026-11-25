'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const KST = 'Asia/Seoul';
const ORIGINS = new Set(['www.babdodukms.com', 'babdodukms.com', 'babdoduk-lab.vercel.app']);
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
    'REFRESH-INTERVAL;VALUE=DURATION:PT15M', 'X-PUBLISHED-TTL:PT15M'];
  return head.concat(blocks, ['END:VCALENDAR']).join('\r\n') + '\r\n';
}

const RETIRED = 'babdoduk:retired';
const RETIRED_NAME = '밥도둑 지난 구독 · 지워 주세요';
function icsEscape(text) {
  return String(text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\r|\n/g, '\\n');
}
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

const PROFILE_ID = 'com.babdodukms.calendar';
function xml(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
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

function entries(saved, feed, archive, now) {
  const { F, L } = siteCode();
  const live = F.occurrences((feed && feed.events || []).filter(F.isPublic));
  const past = F.occurrences((archive && archive.events || []).filter(F.isPublic));
  const byId = new Map();
  past.concat(live).forEach((ev) => byId.set(ev.id, ev));
  const known = !!(feed && archive);
  const nowKst = F.toKst((now || new Date()).toISOString());
  const out = [];
  for (const row of saved || []) {
    const seen = row.seen || {};
    let ev = byId.get(row.event_id);
    if (!ev && seen.startAt) {
      ev = { id: row.event_id, title: seen.title || '', startAt: seen.startAt, endAt: seen.endAt || null,
        location: seen.place ? { name: String(seen.place) } : null };
      const end = F.eventEnd(ev);
      if (known && !(end && end < nowKst)) continue;
    }
    if (ev && L.canCalendar(ev)) out.push(ev);
  }
  return out;
}

async function handler(req, res) {
  const url = new URL(req.url, DEFAULT_ORIGIN);
  const token = url.searchParams.get('t') || '';
  if (!TOKEN.test(token)) { res.statusCode = 404; res.end('not found'); return; }
  const origin = siteOrigin(req.headers);
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
  const [feed, archive] = saved.length ? await Promise.all([
    getJson(origin + '/data/ggongbab/latest.json'),
    getJson(origin + '/data/ggongbab/archive/index.json')
  ]) : [null, null];
  const blocks = entries(saved, feed, archive, new Date()).map((ev) => eventBlock(ev, origin));
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
module.exports.siteCode = siteCode;
