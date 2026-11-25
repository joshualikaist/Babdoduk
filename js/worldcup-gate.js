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
  function dateOf(ms) {
    var d = new Date(ms + KST);
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }
  function labHost() {
    var host = location.hostname;
    return host === 'babdoduk-lab.vercel.app' || host === 'localhost' || host === '127.0.0.1';
  }
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
  function shortDate(date) {
    var part = String(date).split('-'), m = Number(part[1]), d = Number(part[2]);
    var months = String(t('wc.months', '')).split(',');
    return fill(t('wc.dateShort', '{m}/{d}'), { m: m, d: d, mon: months[m - 1] || m });
  }
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
      if (current !== 'live' || el.getAttribute('src')) return;
      if (el.getAttribute('data-wc-srcset')) el.setAttribute('srcset', el.getAttribute('data-wc-srcset'));
      el.setAttribute('src', el.getAttribute('data-wc-src'));
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
    dateLabel: function (which) { return shortDate(which === 'end' ? win.end : win.start); },
    preview: function () { return startDate() !== win.start; }
  };
  refresh();
  var timer = setInterval(function () {
    if (document.hidden) return;
    refresh();
    if (last === 'ended') clearInterval(timer);
  }, 30000);
  if (last === 'ended') clearInterval(timer);
  document.addEventListener('babdoduk-lang', refresh);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });
})();
