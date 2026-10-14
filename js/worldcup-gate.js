/* The 먹방 월드컵's launch gate (owner 2026-10-14: it runs Oct 16 - Oct 23, 2026). One clock for every page
   that shows the world cup: the home page's promo (index.html), the news page's card (event.html) and the
   game page (worldcup.html). The window is the activity's `start` and `end` in data/content/events.json,
   written below by scripts/sync_site_chrome.py (edit that, not this).

     soon   today (KST) is before the first day: the start screen is a teaser, the start is locked
            ("🔒 10/16 오픈" with a countdown), worldcup.html?go=1 starts nothing.
     live   from the first day to the last day, both included (the last minute is 23:59 KST).
     ended  after the last day. The news page's card turns into a past row; worldcup.html stays playable
            with a small "이벤트 종료" note and the home promo is hidden.

   The clock is the browser's, read as Korea time (UTC+9) whatever the visitor's timezone.

   Lab only: the activity's `previewFrom` (a date) is honoured only on babdoduk-lab.vercel.app and on
   localhost, where the world cup counts as started from that day, so it can be tested before the
   launch. Production, previews and any other host ignore it.

   Elements the gate fills (refresh() runs at load, every 30 s, on a language switch and when the tab
   returns), all by attribute so a page needs no code of its own:
     data-wc-show="soon live"        hidden unless the phase is one of these
     data-wc-fmt="<i18n key>"        text = the key with {date} (the first day; data-wc-date="end" for the last)
     data-wc-countdown               "D-2 · 1일 3시간 남음" while soon, else empty (spans .wc-cd-d and .wc-cd-rest)
     data-wc-src="<path>"            an <img> that gets this `src` only once the world cup is live: before the
                                     launch no photo is requested (owner 2026-10-14: nothing revealed)
   A phase change fires `babdoduk-wc-phase` on the document. */
// @content:worldcup-gate
window.BABDODUK_WC_WINDOW = {"start": "2026-10-16", "end": "2026-10-23", "previewFrom": "2026-10-13"};
// @end content
(function () {
  'use strict';
  var win = window.BABDODUK_WC_WINDOW || {};
  var MINUTE = 60000, DAY = 86400000, KST = 9 * 3600000;
  var last = null;

  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function t(key, fallback) {
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang()];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function fill(text, values) {
    return String(text).replace(/\{(\w+)\}/g, function (match, name) {
      return values[name] != null ? values[name] : match;
    });
  }
  function pad(n) { return String(n).padStart(2, '0'); }
  // A moment as its Korean calendar date, YYYY-MM-DD.
  function dateOf(ms) {
    var d = new Date(ms + KST);               // read with the UTC getters: they are then the Korean clock
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }
  function labHost() {
    var host = location.hostname;
    return host === 'babdoduk-lab.vercel.app' || host === 'localhost' || host === '127.0.0.1';
  }
  // The first day the world cup counts as started on this host.
  function startDate() {
    var early = win.previewFrom;
    return labHost() && early && early < win.start ? early : win.start;
  }
  function phase(now) {
    if (!win.start || !win.end) return 'live';
    var today = dateOf(now == null ? Date.now() : now);
    if (today < startDate()) return 'soon';
    return today > win.end ? 'ended' : 'live';
  }
  function opensAt() { return Date.parse(startDate() + 'T00:00:00+09:00'); }
  // "10/16", or "Oct 16" in English.
  function shortDate(date) {
    var part = String(date).split('-'), m = Number(part[1]), d = Number(part[2]);
    var months = String(t('wc.months', '')).split(',');
    return fill(t('wc.dateShort', '{m}/{d}'), { m: m, d: d, mon: months[m - 1] || m });
  }
  // "D-2 · 1일 3시간 남음": the days to go on the calendar, then the time left in its two largest units.
  // Returned as [days, rest] so a narrow layout can keep just "D-2"; ['', ''] once it is time.
  function countdownParts(now) {
    now = now == null ? Date.now() : now;
    var left = opensAt() - now;
    if (!(left > 0)) return ['', ''];
    var days = Math.round((Date.parse(startDate() + 'T00:00:00Z') - Date.parse(dateOf(now) + 'T00:00:00Z')) / DAY);
    var minutes = Math.floor(left / MINUTE), d = Math.floor(minutes / 1440), h = Math.floor(minutes % 1440 / 60), m = minutes % 60;
    var body = d >= 1 ? fill(t('wc.countdown.long', '{d}일 {h}시간 남음'), { d: d, h: h })
      : h >= 1 ? fill(t('wc.countdown.hours', '{h}시간 {m}분 남음'), { h: h, m: m })
        : fill(t('wc.countdown.minutes', '{m}분 남음'), { m: Math.max(m, 1) });
    return [fill(t('wc.countdown.d', 'D-{n}'), { n: days }), ' · ' + body];
  }
  function countdown(now) { return countdownParts(now).join(''); }
  function each(selector, fn) { [].forEach.call(document.querySelectorAll(selector), fn); }
  function refresh() {
    var now = Date.now(), current = phase(now);
    each('[data-wc-show]', function (el) {
      el.hidden = el.getAttribute('data-wc-show').split(' ').indexOf(current) < 0;
    });
    each('[data-wc-fmt]', function (el) {
      var date = el.getAttribute('data-wc-date') === 'end' ? win.end : win.start;
      el.textContent = fill(t(el.getAttribute('data-wc-fmt')), { date: shortDate(date) });
    });
    each('[data-wc-src]', function (el) {
      if (current === 'live' && !el.getAttribute('src')) el.setAttribute('src', el.getAttribute('data-wc-src'));
    });
    each('[data-wc-countdown]', function (el) {
      var parts = current === 'soon' ? countdownParts(now) : ['', ''];
      el.textContent = '';
      ['wc-cd-d', 'wc-cd-rest'].forEach(function (name, i) {
        if (!parts[i]) return;
        var span = document.createElement('span');
        span.className = name;
        span.textContent = parts[i];
        el.appendChild(span);
      });
    });
    document.documentElement.setAttribute('data-wc-phase', current);
    if (last !== null && last !== current) document.dispatchEvent(new CustomEvent('babdoduk-wc-phase', { detail: current }));
    last = current;
  }

  window.BabdodukWorldcup = {
    phase: phase, startDate: startDate, endDate: function () { return win.end; }, opensAt: opensAt,
    countdown: countdown, refresh: refresh,
    // "10/16" ("Oct 16"): the first day, or the last with 'end'.
    dateLabel: function (which) { return shortDate(which === 'end' ? win.end : win.start); },
    // Lab only: the world cup counts as started before its first day on this host.
    preview: function () { return startDate() !== win.start; }
  };
  refresh();
  setInterval(refresh, 30000);
  document.addEventListener('babdoduk-lang', refresh);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });
})();
