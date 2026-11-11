/* 꽁밥 LIVE, Phase 1 (docs/GGONGBAB_LIVE.md): what the hub adds on top of the published snapshot.
   - Saved listings, kept in this browser only (localStorage `babdoduk-ggongbab-saved`, schema v1).
     A saved row keeps the listing's id and what the visitor saw when saving (time, place, title), never
     the whole event: the page always shows the newest published copy, and the "seen" values are only
     there to say what changed since.
   - Filters read only what the data states: the audience as written (an inferred one is "확인 필요"),
     the campus area from a KAIST building number (N/E/W), the KST date.
   - One listing to a calendar (a Google Calendar link or an .ics file with a 30-minute alert), never the
     whole feed; and, for visitors who said yes once, the calendar's add screen right after a star.
   - Share links: ggongbab.html?e=<id> for one listing, ?week=<Monday> for a week.
   No network calls, no accounts, no analytics. Needs js/ggongbab-select.js (BabdodukFreeFood). */
(function (global) {
  var F = global.BabdodukFreeFood;
  if (!F) return;

  // ---------- Saved listings ----------
  var SAVED_KEY = 'babdoduk-ggongbab-saved';
  var BACKUP_KEY = 'babdoduk-ggongbab-saved-unreadable';
  var VERSION = 1;
  var MAX_SAVED = 300;
  var ID_RE = /^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$/;

  function clip(value, n) { return typeof value === 'string' ? value.slice(0, n) : ''; }
  function placeText(ev) {
    var loc = (ev && ev.location) || {};
    var seen = [];
    [loc.building, loc.room, loc.name].forEach(function (piece) {
      piece = String(piece || '').trim();
      if (piece && seen.indexOf(piece) < 0) seen.push(piece);
    });
    return seen.join(' · ');
  }
  // What the visitor saw when saving; only these fields, only as text.
  function seenOf(ev) {
    return {
      title: clip(String(ev.title || ''), 200),
      startAt: clip(String(ev.startAt || ''), 40),
      endAt: clip(String(ev.endAt || ''), 40),
      place: clip(placeText(ev), 200)
    };
  }
  function cleanItem(item) {
    if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !ID_RE.test(item.id)) return null;
    var seen = item.seen && typeof item.seen === 'object' ? item.seen : {};
    return {
      id: item.id,
      savedAt: clip(item.savedAt, 40),
      seen: { title: clip(seen.title, 200), startAt: clip(seen.startAt, 40), endAt: clip(seen.endAt, 40), place: clip(seen.place, 200) }
    };
  }
  // {items, writable}. Unreadable data is set aside once (never silently thrown away) and the list
  // starts empty; a newer schema than this page knows is shown but never rewritten.
  function readStore(storage) {
    var raw = null;
    try { raw = storage.getItem(SAVED_KEY); } catch (err) { return { items: [], writable: false }; }
    if (raw == null || raw === '') return { items: [], writable: true };
    var data;
    try { data = JSON.parse(raw); } catch (err) { data = null; }
    if (!data || typeof data !== 'object' || !Array.isArray(data.items) || typeof data.v !== 'number') {
      try { if (storage.getItem(BACKUP_KEY) == null) storage.setItem(BACKUP_KEY, String(raw).slice(0, 20000)); } catch (err) {}
      try { storage.removeItem(SAVED_KEY); } catch (err) {}
      return { items: [], writable: true, recovered: true };
    }
    var seenIds = {};
    var items = data.items.map(cleanItem).filter(function (item) {
      if (!item || seenIds[item.id]) return false;
      seenIds[item.id] = true;
      return true;
    }).slice(0, MAX_SAVED);
    return { items: items, writable: data.v === VERSION };
  }
  function createStore(storage) {
    storage = storage || safeStorage();
    var state = readStore(storage);
    function write() {
      if (!state.writable) return false;
      try {
        storage.setItem(SAVED_KEY, JSON.stringify({ v: VERSION, items: state.items }));
        return true;
      } catch (err) { return false; }
    }
    function find(id) {
      for (var i = 0; i < state.items.length; i++) if (state.items[i].id === id) return state.items[i];
      return null;
    }
    return {
      list: function () { return state.items.slice(); },
      has: function (id) { return !!find(id); },
      get: find,
      writable: function () { return state.writable; },
      recovered: function () { return !!state.recovered; },
      add: function (ev, now) {
        if (!ev || !ID_RE.test(String(ev.id || '')) || find(ev.id)) return false;
        if (state.items.length >= MAX_SAVED) return false;
        state.items.unshift({ id: ev.id, savedAt: (now || new Date()).toISOString(), seen: seenOf(ev) });
        return write();
      },
      remove: function (id) {
        var before = state.items.length;
        state.items = state.items.filter(function (item) { return item.id !== id; });
        return state.items.length !== before && write();
      },
      // "확인했어요": the visitor has seen the change, so the current copy becomes what they saw.
      acknowledge: function (ev) {
        var item = find(ev.id);
        if (!item) return false;
        item.seen = seenOf(ev);
        return write();
      },
      reload: function () { state = readStore(storage); }
    };
  }
  function safeStorage() {
    try { return global.localStorage; } catch (err) { return null; }
  }
  // What changed between what the visitor saw and the newest copy: [{field, before, after}].
  // Times compare as instants, so "+09:00" and "Z" spellings of the same time are no change.
  function sameInstant(a, b) {
    if (!a && !b) return true;
    var x = Date.parse(a), y = Date.parse(b);
    if (isNaN(x) || isNaN(y)) return String(a || '') === String(b || '');
    return x === y;
  }
  function changes(item, ev) {
    if (!item || !ev) return [];
    var seen = item.seen || {};
    var out = [];
    if (seen.startAt && (!sameInstant(seen.startAt, ev.startAt) || !sameInstant(seen.endAt, ev.endAt))) {
      out.push({ field: 'time', before: { startAt: seen.startAt, endAt: seen.endAt }, after: { startAt: ev.startAt, endAt: ev.endAt } });
    }
    var place = placeText(ev);
    if (seen.place && place && seen.place !== place) out.push({ field: 'place', before: seen.place, after: place });
    return out;
  }

  // ---------- Filters ----------
  // A KAIST building number starts with its campus area: N (north), E (east), W (west).
  var AREA_CODE = /(?:^|[^A-Za-z0-9])([NEW])(\d{1,2})(?:-\d{1,2})?(?![0-9])/;
  function areaOf(ev) {
    var loc = (ev && ev.location) || {};
    var texts = [loc.building, loc.room, loc.name];
    for (var i = 0; i < texts.length; i++) {
      var m = AREA_CODE.exec(String(texts[i] || ''));
      if (m) return { N: 'north', E: 'east', W: 'west' }[m[1]];
    }
    return 'unknown';
  }
  // Who a listing is for, only as the source wrote it. An inferred audience, or none, is "check".
  var WHO = [
    ['fresh', /새내기|신입생|\d{2}\s*학번|freshm(a|e)n|first[- ]year/i],
    ['undergrad', /학부생|학사\s*과정|학부\s*학생|재학생|새내기|신입생|\d{2}\s*학번|undergrad/i],
    ['grad', /대학원|석사|박사|연구자|연구원|graduate|master'?s|ph\.?\s?d|postdoc|researcher/i]
  ];
  var OPEN = /누구나|제한\s*없|모든\s*(KAIST\s*)?(구성원|사람|분|학생)|관심\s*있는\s*(모든|분|사람|여러분)|관심\s*있으신\s*분|anyone|everyone|open to all|all (are )?welcome/i;
  function audienceText(ev) {
    var a = ev && ev.audience;
    if (a && typeof a.text === 'string' && a.text.trim()) return a.basis === 'inferred' ? '' : a.text.trim();
    return ev && typeof ev.eligibility === 'string' ? ev.eligibility.trim() : '';
  }
  function whoOf(ev) {
    var text = audienceText(ev);
    if (!text) return ['check'];
    var groups = WHO.filter(function (row) { return row[1].test(text); }).map(function (row) { return row[0]; });
    if (!groups.length && OPEN.test(text)) groups.push('open');
    return groups.length ? groups : ['check'];
  }

  // ---------- KST dates ----------
  function ymdToUtc(key) {
    var p = String(key).split('-');
    return Date.UTC(+p[0], +p[1] - 1, +p[2]);
  }
  function utcToYmd(ms) {
    var d = new Date(ms);
    return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
  }
  function addDaysYmd(key, n) { return utcToYmd(ymdToUtc(key) + n * 86400000); }
  function weekdayOf(key) { return new Date(ymdToUtc(key)).getUTCDay(); }    // 0 = Sunday
  // Monday of the KST week that holds `key` (Monday to Sunday, as the hub's "이번 주").
  function mondayOf(key) { return addDaysYmd(key, -((weekdayOf(key) + 6) % 7)); }
  function isYmd(key) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(key || '')) && utcToYmd(ymdToUtc(key)) === key;
  }
  // [first, last] day keys for a date filter: 'all' | 'today' | 'week' | 'next' | 'w:<Monday>'.
  function dayRange(filter, now) {
    var today = F.ymd(now);
    if (filter === 'today') return [today, today];
    if (filter === 'week') return [today, addDaysYmd(mondayOf(today), 6)];
    if (filter === 'next') { var next = addDaysYmd(mondayOf(today), 7); return [next, addDaysYmd(next, 6)]; }
    if (/^w:/.test(String(filter))) {
      var monday = String(filter).slice(2);
      if (isYmd(monday)) return [monday, addDaysYmd(monday, 6)];
    }
    return null;
  }
  function inDays(ev, filter, now) {
    var range = dayRange(filter, now);
    if (!range) return true;
    var s = F.toKst(ev.startAt);
    if (!s) return false;
    var key = F.ymd(s);
    return key >= range[0] && key <= range[1];
  }
  // Now relative to the listing's own times: 'soon' (not started), 'now' (running), 'ended'.
  function phaseOf(ev, now) {
    var s = F.toKst(ev.startAt), end = F.eventEnd(ev);
    if (end && end < now) return 'ended';
    if (s && s <= now && !F.isDeadlineOnly(ev)) return 'now';
    return 'soon';
  }

  // ---------- Calendar ----------
  var ALARM_MINUTES = 30;
  function utcStamp(iso) {
    if (!iso || typeof iso !== 'string') return '';        // new Date(null) would be 1970
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  }
  // A calendar entry needs a real event time: a deadline-only giveaway has none, and an ended
  // listing is not offered. An unknown end is never made up: the entry then starts and ends at once.
  function canCalendar(ev, now) {
    if (!ev || !utcStamp(ev.startAt) || F.isDeadlineOnly(ev)) return false;
    return !now || F.isUpcoming(ev, now);
  }
  function calendarTimes(ev) {
    var start = utcStamp(ev.startAt);
    var end = utcStamp(ev.endAt);
    if (!end || Date.parse(ev.endAt) < Date.parse(ev.startAt)) end = start;
    return { start: start, end: end };
  }
  function googleCalendarUrl(ev, opts) {
    var times = calendarTimes(ev);
    var params = new URLSearchParams();
    params.set('action', 'TEMPLATE');
    params.set('text', String(ev.title || ''));
    params.set('dates', times.start + '/' + times.end);
    params.set('ctz', 'Asia/Seoul');
    var place = placeText(ev);
    if (place) params.set('location', place);
    if (opts && opts.details) params.set('details', opts.details);
    return 'https://calendar.google.com/calendar/render?' + params.toString();
  }
  function icsEscape(text) {
    return String(text == null ? '' : text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
  }
  // RFC 5545 folds content lines at 75 octets; count UTF-8 bytes, never split a character.
  function fold(line) {
    var out = [], cur = '', bytes = 0;
    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      var code = line.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff && i + 1 < line.length) { ch += line[++i]; }
      var size = unescape(encodeURIComponent(ch)).length;
      var limit = out.length ? 74 : 75;
      if (bytes + size > limit) { out.push(cur); cur = ''; bytes = 0; }
      cur += ch; bytes += size;
    }
    out.push(cur);
    return out.join('\r\n ');
  }
  function icsText(ev, opts) {
    var times = calendarTimes(ev);
    var lines = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Babdoduk//ggongbab//KO', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
      'BEGIN:VEVENT',
      'UID:' + icsEscape(String(ev.id).replace(/#/g, '-')) + '@babdodukms.com',
      'DTSTAMP:' + utcStamp((opts && opts.stamp) || new Date().toISOString()),
      'DTSTART:' + times.start
    ];
    if (times.end !== times.start) lines.push('DTEND:' + times.end);
    lines.push('SUMMARY:' + icsEscape(ev.title));
    var place = placeText(ev);
    if (place) lines.push('LOCATION:' + icsEscape(place));
    if (opts && opts.details) lines.push('DESCRIPTION:' + icsEscape(opts.details));
    if (opts && opts.url) lines.push('URL:' + icsEscape(opts.url));
    // The reminder rides in the file (owner 2026-11-11: an alert 30 minutes before the start).
    lines.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + icsEscape(ev.title), 'TRIGGER:-PT' + ALARM_MINUTES + 'M', 'END:VALARM');
    lines.push('END:VEVENT', 'END:VCALENDAR');
    return lines.map(fold).join('\r\n') + '\r\n';
  }
  function icsFileName(ev) {
    var s = F.toKst(ev.startAt);
    return 'babdoduk-' + (s ? F.ymd(s) : 'event') + '.ics';
  }

  function downloadIcs(ev, opts) {
    var doc = global.document;
    try {
      var blob = new Blob([icsText(ev, opts)], { type: 'text/calendar;charset=utf-8' });
      var a = doc.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = icsFileName(ev);
      doc.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      return true;
    } catch (err) {
      return false;
    }
  }

  // ---------- The star also adds to the calendar (owner 2026-11-11) ----------
  // A web page cannot write into a phone's calendar on its own. The closest is to open the calendar's
  // own add screen right after a star, for visitors who said yes once. The answer is kept in this
  // browser: 'on' or 'off'; nothing stored means not asked yet. Without storage the question is never
  // asked, since the answer could not be kept.
  var STAR_CAL_KEY = 'babdoduk-star-calendar';
  function starCalendar() {
    try {
      var value = global.localStorage.getItem(STAR_CAL_KEY);
      return value === 'on' || value === 'off' ? value : '';
    } catch (err) {
      return 'off';
    }
  }
  function setStarCalendar(on) {
    try { global.localStorage.setItem(STAR_CAL_KEY, on ? 'on' : 'off'); return true; } catch (err) { return false; }
  }
  // Apple devices (iPadOS says Macintosh) open an .ics file in an "add to calendar" screen that keeps
  // the file's 30-minute alert; elsewhere Google Calendar's add page opens, with the visitor's own
  // default reminder. The kakaotalk in-app browser does neither reliably, so it is sent to the buttons.
  function calendarRoute(ua) {
    ua = ua == null ? (global.navigator || {}).userAgent || '' : ua;
    if (inTalkApp(ua)) return 'manual';
    return /iPhone|iPad|iPod|Macintosh/i.test(ua) ? 'ics' : 'google';
  }
  // Must run inside the click that asked for it, or the browser blocks the new window or download.
  // Resolves to 'ics' | 'google' | 'blocked' | 'manual'.
  function addToCalendar(ev, opts, ua) {
    var route = calendarRoute(ua);
    if (route === 'manual') return 'manual';
    if (route === 'ics') return downloadIcs(ev, opts) ? 'ics' : 'blocked';
    var win = global.open(googleCalendarUrl(ev, opts), '_blank');
    if (!win) return 'blocked';
    try { win.opener = null; } catch (err) {}
    return 'google';
  }
  // The one-time question: a small panel at the bottom of the screen that covers nothing it needs.
  // `text` holds the page's strings (title, body, yes, no, later). `answer(choice)` gets true, false,
  // or null (closed with Escape: ask again next time) and runs inside the click, so a yes can still
  // open the calendar.
  function askStarCalendar(text, answer) {
    var doc = global.document;
    var old = doc.getElementById('starCalAsk');
    if (old) old.remove();
    var box = doc.createElement('div');
    box.id = 'starCalAsk';
    box.className = 'starcal';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-labelledby', 'starCalAskTitle');
    box.setAttribute('aria-describedby', 'starCalAskBody');
    box.innerHTML = '<p class="starcal-title" id="starCalAskTitle"></p><p class="starcal-body" id="starCalAskBody"></p>' +
      '<div class="starcal-actions"><button type="button" class="starcal-yes" data-starcal="yes"></button>' +
      '<button type="button" class="starcal-no" data-starcal="no"></button></div><p class="starcal-later"></p>';
    box.querySelector('.starcal-title').textContent = text.title;
    box.querySelector('.starcal-body').textContent = text.body;
    box.querySelector('.starcal-yes').textContent = text.yes;
    box.querySelector('.starcal-no').textContent = text.no;
    box.querySelector('.starcal-later').textContent = text.later;
    function close(choice) {
      box.remove();
      doc.removeEventListener('keydown', onKey, true);
      if (choice !== null) setStarCalendar(choice);
      answer(choice);
    }
    function onKey(e) { if (e.key === 'Escape' && box.isConnected) { e.preventDefault(); close(null); } }
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-starcal]');
      if (b) close(b.getAttribute('data-starcal') === 'yes');
    });
    doc.addEventListener('keydown', onKey, true);
    doc.body.appendChild(box);
    box.querySelector('.starcal-yes').focus({ preventScroll: true });
    return box;
  }

  // ---------- Share ----------
  function pageUrl(base) {
    var u = new URL('ggongbab.html', base || global.location.href);
    u.search = ''; u.hash = '';
    return u;
  }
  function eventLink(id, base) {
    var u = pageUrl(base);
    u.searchParams.set('e', id);
    return u.href;
  }
  function weekLink(monday, base) {
    var u = pageUrl(base);
    u.searchParams.set('week', monday);
    return u.href;
  }
  // The kakaotalk in-app browser (its user agent says so); downloads may not work there.
  function inTalkApp(ua) { return /kakaotalk/i.test(ua == null ? (global.navigator || {}).userAgent || '' : ua); }
  // The kakaotalk app's scheme for leaving its in-app browser.
  function openExternalUrl(url) { return 'kakaotalk://web/openExternal?url=' + encodeURIComponent(url); }
  // Resolves 'shared' | 'copied' | 'manual' | 'cancelled'. 'manual' means the caller shows the text to copy.
  function share(payload) {
    var nav = global.navigator || {};
    var text = payload.text ? payload.text + '\n' + payload.url : payload.url;
    function copy() {
      if (nav.clipboard && nav.clipboard.writeText && global.isSecureContext !== false) {
        return nav.clipboard.writeText(text).then(function () { return 'copied'; }, function () { return 'manual'; });
      }
      return Promise.resolve('manual');
    }
    if (typeof nav.share === 'function' && !payload.copyOnly) {
      return nav.share({ title: payload.title, text: payload.text, url: payload.url }).then(function () { return 'shared'; }, function (err) {
        return err && err.name === 'AbortError' ? 'cancelled' : copy();
      });
    }
    return copy();
  }

  global.BabdodukLive = {
    SAVED_KEY: SAVED_KEY,
    createStore: createStore,
    readStore: readStore,
    seenOf: seenOf,
    changes: changes,
    placeText: placeText,
    areaOf: areaOf,
    whoOf: whoOf,
    dayRange: dayRange,
    inDays: inDays,
    mondayOf: mondayOf,
    addDaysYmd: addDaysYmd,
    isYmd: isYmd,
    phaseOf: phaseOf,
    canCalendar: canCalendar,
    googleCalendarUrl: googleCalendarUrl,
    icsText: icsText,
    icsFileName: icsFileName,
    downloadIcs: downloadIcs,
    ALARM_MINUTES: ALARM_MINUTES,
    STAR_CAL_KEY: STAR_CAL_KEY,
    starCalendar: starCalendar,
    setStarCalendar: setStarCalendar,
    calendarRoute: calendarRoute,
    addToCalendar: addToCalendar,
    askStarCalendar: askStarCalendar,
    eventLink: eventLink,
    weekLink: weekLink,
    inTalkApp: inTalkApp,
    openExternalUrl: openExternalUrl,
    share: share
  };
})(window);
