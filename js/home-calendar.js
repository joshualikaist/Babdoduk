/* Home free-food calendar: today's answer, the month at a glance, one selected day and what
   comes next. It reads the same validated public snapshot and past listings as the food hub,
   through the hub's own eligibility and grace-window rules (js/ggongbab-select.js), and it
   never states more than those files hold. Dates are KST whatever the browser's time zone. */
(function () {
  var F = window.BabdodukFreeFood;
  if (!F) return;

  var DAY_MS = 86400000;
  var LIVE_URL = 'data/ggongbab/latest.json';
  var ARCHIVE_URL = 'data/ggongbab/archive/index.json';
  var ARCHIVE_WINDOW_DAYS = 30;   // the past listings' own window; older days are not kept
  var MONTHS_AHEAD = 2;           // browsable beyond today's month, or further to the last event
  var UPCOMING_ROWS = 4;

  // ---- Dates as 'YYYY-MM-DD' strings, computed in UTC so no browser offset leaks in ----
  function pad(n) { return String(n).padStart(2, '0'); }
  function isoToMs(iso) { var p = iso.split('-'); return Date.UTC(+p[0], +p[1] - 1, +p[2]); }
  function msToIso(ms) {
    var d = new Date(ms);
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }
  function addDays(iso, n) { return msToIso(isoToMs(iso) + n * DAY_MS); }
  function weekdaySun(iso) { return new Date(isoToMs(iso)).getUTCDay(); } // 0 = Sunday (grid column)
  function daysInMonth(ym) { return new Date(Date.UTC(+ym.slice(0, 4), +ym.slice(5, 7), 0)).getUTCDate(); }
  function monthOf(iso) { return iso.slice(0, 7); }
  function addMonths(ym, n) {
    var m = +ym.slice(5, 7) - 1 + n;
    var y = +ym.slice(0, 4) + Math.floor(m / 12);
    return y + '-' + pad(((m % 12) + 12) % 12 + 1);
  }
  // Sunday-first weeks covering the month: 4 to 6 rows, overflow days included.
  function monthGrid(ym) {
    var first = ym + '-01';
    var lead = weekdaySun(first);
    var rows = Math.ceil((lead + daysInMonth(ym)) / 7);
    var start = addDays(first, -lead);
    var weeks = [];
    for (var r = 0; r < rows; r++) {
      var week = [];
      for (var c = 0; c < 7; c++) week.push(addDays(start, r * 7 + c));
      weeks.push(week);
    }
    return weeks;
  }
  // PageUp/PageDown: the same day number in the neighbouring month, clamped to its length.
  function shiftMonth(iso, n) {
    var ym = addMonths(monthOf(iso), n);
    return ym + '-' + pad(Math.min(+iso.slice(8, 10), daysInMonth(ym)));
  }

  // ---- Events by KST start date, from the live snapshot and the past listings ----
  function eventDay(ev) {
    var s = F.toKst(ev.startAt);
    return s ? F.ymd(s) : '';
  }
  // Live rows first, so a row that is in both files is taken once, from the live copy.
  function buildIndex(liveEvents, archiveEvents, now, windowStart) {
    var seen = {};
    var days = {};
    function add(ev) {
      if (!ev || typeof ev.id !== 'string' || !ev.id || seen[ev.id] || !F.isPublic(ev)) return;
      var day = eventDay(ev);
      if (!day) return;
      var active = F.isUpcoming(ev, now);
      if (!active && day < windowStart) return;
      seen[ev.id] = true;
      (days[day] = days[day] || []).push({ ev: ev, active: active });
    }
    (liveEvents || []).forEach(add);
    (archiveEvents || []).forEach(add);
    Object.keys(days).forEach(function (day) {
      days[day].sort(function (a, b) {
        return String(a.ev.startAt || '').localeCompare(String(b.ev.startAt || '')) || a.ev.id.localeCompare(b.ev.id);
      });
    });
    return days;
  }
  function countsOn(days, iso) {
    var active = 0;
    var past = 0;
    (days[iso] || []).forEach(function (item) { if (item.active) active++; else past++; });
    return { active: active, past: past };
  }
  function nextActiveDay(days, afterIso) {
    return Object.keys(days).filter(function (day) {
      return day > afterIso && days[day].some(function (item) { return item.active; });
    }).sort()[0] || '';
  }
  // Today when it still has something on; otherwise the next date that does; otherwise today.
  function defaultSelection(days, todayIso) {
    if (countsOn(days, todayIso).active) return todayIso;
    return nextActiveDay(days, todayIso) || todayIso;
  }
  function answerFor(days, todayIso) {
    var list = days[todayIso] || [];
    var active = list.filter(function (item) { return item.active; });
    var next = nextActiveDay(days, todayIso);
    if (active.length) {
      var start = F.toKst(active[0].ev.startAt);
      return { kind: 'today', n: active.length, time: start ? hm(start) : '' };
    }
    if (list.length) return { kind: next ? 'endedNext' : 'ended', date: next };
    return next ? { kind: 'next', date: next } : { kind: 'none' };
  }

  // ---- Place and link helpers (the hub's rules) ----
  var BUILDING_CODE = /^[A-Z]{1,3}\d{1,3}[A-Z]?$/;
  function shortPlace(loc) {
    loc = loc || {};
    var building = String(loc.building || '').trim();
    var room = String(loc.room || '').trim();
    var code = (building.match(/\(([A-Z]{1,3}\d{1,3}[A-Z]?)\)/) || [])[1] || (BUILDING_CODE.test(building) ? building : '');
    var head = code || building || String(loc.name || '').trim();
    return [head, room].filter(Boolean).join(' ');
  }
  function fullPlace(loc) {
    loc = loc || {};
    var name = String(loc.name || '').trim();
    var room = String(loc.room || '').trim();
    if (name) return room && name.indexOf(room) < 0 ? name + ' ' + room : name;
    return [String(loc.building || '').trim(), room].filter(Boolean).join(' ');
  }
  function safeHref(url) {
    if (!url) return '';
    try {
      var u = new URL(url, location.href);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
      if (/(^|\.)dooray\.com$/i.test(u.hostname)) return '';   // never a mail-system link
      return u.href;
    } catch (e) { return ''; }
  }
  // Only public web notices (KAIST notices, Babdoduk's own entries) are linked; internal sources never are.
  function publicSourceUrl(ev) {
    return (ev.sources || []).filter(function (src) { return src && (src.type === 'kaist_public' || src.type === 'manual'); })
      .map(function (src) { return safeHref(src.url); }).filter(Boolean)[0] || '';
  }
  function sourceKey(ev) {
    var types = (ev.sources || []).map(function (src) { return src && src.type; });
    if (types.indexOf('dooray') >= 0 || types.indexOf('dooray_mailbox') >= 0) return 'home.cal.src.mail';
    if (types.indexOf('portal') >= 0) return 'home.cal.src.portal';
    if (types.indexOf('kaist_public') >= 0) return 'home.cal.src.public';
    if (types.indexOf('manual') >= 0) return 'home.cal.src.manual';
    return '';
  }

  // ---- Copy ----
  var DOW_KO = ['일', '월', '화', '수', '목', '금', '토'];
  var DOW_KO_FULL = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
  var DOW_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var DOW_EN_FULL = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  var MON_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MON_EN_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
    'October', 'November', 'December'];
  var FOOD_TYPES = ['meal', 'lunchbox', 'snack', 'refreshment', 'beverage', 'coupon'];

  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function t(key, fallback) {
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang()];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function hm(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function dateLabel(iso) {
    var m = +iso.slice(5, 7);
    var d = +iso.slice(8, 10);
    var w = weekdaySun(iso);
    return lang() === 'en' ? MON_EN[m - 1] + ' ' + d + ' (' + DOW_EN[w] + ')' : m + '월 ' + d + '일 (' + DOW_KO[w] + ')';
  }
  function longDateLabel(iso) {
    var m = +iso.slice(5, 7);
    var d = +iso.slice(8, 10);
    var w = weekdaySun(iso);
    return lang() === 'en' ? DOW_EN_FULL[w] + ', ' + MON_EN_FULL[m - 1] + ' ' + d : m + '월 ' + d + '일 ' + DOW_KO_FULL[w];
  }
  function monthLabel(ym, todayIso) {
    var y = +ym.slice(0, 4);
    var m = +ym.slice(5, 7);
    var sameYear = y === +todayIso.slice(0, 4);
    if (lang() === 'en') return MON_EN_FULL[m - 1] + (sameYear ? '' : ' ' + y);
    return (sameYear ? '' : y + '년 ') + m + '월';
  }
  function fill(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (all, name) { return values[name] != null ? values[name] : all; });
  }
  function foodText(ev) {
    var food = ev.food || {};
    var type = FOOD_TYPES.indexOf(food.type) >= 0 ? food.type : '';
    var typeLabel = type ? t('home.cal.food.' + type, '') : '';
    if (lang() === 'en') return typeLabel || t('home.cal.food.other', 'Food');
    var desc = food.description && String(food.description).length <= 22 ? food.description : typeLabel || t('home.cal.food.other', '음식');
    return fill(t('home.cal.ev.food', '{food} 제공'), { food: desc });
  }

  // ---- State and rendering ----
  var root = document.getElementById('homeCal');
  if (!root) {
    window.BabdodukHomeCalendar = api();
    return;
  }
  var els = {
    today: document.getElementById('homeCalToday'),
    answer: document.getElementById('homeCalAnswer'),
    month: document.getElementById('homeCalGrid'),
    day: document.getElementById('homeCalDay'),
    next: document.getElementById('homeCalNext'),
    all: document.getElementById('homeCalAll'),
    published: document.getElementById('homeCalPublished'),
    live: document.getElementById('homeCalLive')
  };
  var state = {
    status: 'loading',          // the live snapshot: loading | ready | error
    archiveStatus: 'loading',   // the past listings: loading | ready | error
    live: null,
    archive: null,
    windowDays: ARCHIVE_WINDOW_DAYS,
    days: {},
    todayIso: '',
    windowStart: '',
    minMonth: '',
    maxMonth: '',
    view: '',
    selected: '',
    focus: '',
    open: '',
    touched: false             // a person picked a date: late data never moves their choice
  };
  var grid = null;

  function refreshIndex() {
    var now = F.nowKst();
    state.todayIso = F.ymd(now);
    state.windowStart = addDays(state.todayIso, -state.windowDays);
    var liveEvents = state.status === 'ready' ? state.live.events : [];
    var archiveEvents = state.archiveStatus === 'ready' && state.archive ? state.archive.events : [];
    state.days = state.status === 'error' ? {} : buildIndex(liveEvents, archiveEvents, now, state.windowStart);
    var todayMonth = monthOf(state.todayIso);
    var last = Object.keys(state.days).sort().pop() || state.todayIso;
    var ahead = addMonths(todayMonth, MONTHS_AHEAD);
    state.minMonth = monthOf(state.windowStart);
    state.maxMonth = monthOf(last) > ahead ? monthOf(last) : ahead;
  }
  // The approved default: today's month on screen; the day panel on today, or on the next
  // event date when today has nothing on.
  function resetView() {
    state.view = monthOf(state.todayIso);
    state.selected = state.status === 'ready' ? defaultSelection(state.days, state.todayIso) : state.todayIso;
    state.focus = rovingFocus();
    state.open = '';
  }
  function inView(iso) {
    return monthGrid(state.view).some(function (week) { return week.indexOf(iso) >= 0; });
  }
  function selectable(iso) {
    return iso >= state.windowStart && monthOf(iso) >= state.minMonth && monthOf(iso) <= state.maxMonth;
  }
  function rovingFocus() {
    if (inView(state.selected) && selectable(state.selected)) return state.selected;
    if (inView(state.todayIso)) return state.todayIso;
    var first = state.view + '-01';
    for (var i = 0; i < 31; i++) {
      var iso = addDays(first, i);
      if (monthOf(iso) !== state.view) break;
      if (selectable(iso)) return iso;
    }
    return first;
  }

  function cellLabel(iso, counts) {
    var parts = [longDateLabel(iso)];
    if (counts.active) parts.push(fill(t('home.cal.cell.active', '꽁밥 {n}개'), { n: counts.active }));
    if (counts.past) parts.push(fill(t('home.cal.cell.past', '지난 꽁밥 {n}개'), { n: counts.past }));
    return parts.join(', ');
  }
  function cellHtml(iso) {
    var cls = ['hc-cell'];
    if (monthOf(iso) !== state.view) cls.push('is-other');
    if (iso === state.todayIso) cls.push('is-today');
    var day = +iso.slice(8, 10);
    if (!selectable(iso)) {
      cls.push('is-off');
      return '<td class="' + cls.join(' ') + '" aria-disabled="true"><span class="hc-num" aria-hidden="true">' + day +
        '</span><span class="hc-marks" aria-hidden="true"></span></td>';
    }
    var counts = state.status === 'ready' ? countsOn(state.days, iso) : { active: 0, past: 0 };
    var dots = Math.min(counts.active, 2);
    var rings = Math.min(counts.past, 2 - dots);
    var marks = '';
    for (var i = 0; i < dots; i++) marks += '<span class="hc-dot"></span>';
    for (var j = 0; j < rings; j++) marks += '<span class="hc-dot is-past"></span>';
    return '<td class="' + cls.join(' ') + '" data-date="' + iso + '" tabindex="' + (iso === state.focus ? '0' : '-1') +
      '" aria-selected="' + (iso === state.selected ? 'true' : 'false') + '"' +
      (iso === state.todayIso ? ' aria-current="date"' : '') + ' aria-label="' + esc(cellLabel(iso, counts)) + '">' +
      '<span class="hc-num" aria-hidden="true">' + day + '</span><span class="hc-marks" aria-hidden="true">' + marks + '</span></td>';
  }

  var CHEVRON = {
    prev: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M14.5 6 8.5 12l6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    next: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9.5 6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    down: '<svg class="hc-ev-chev" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m6 9.5 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  // The month header is built once, so its buttons keep keyboard focus across month changes.
  function mountGrid() {
    els.month.innerHTML =
      '<div class="hc-month">' +
      '<p class="hc-month-title" id="homeCalMonth" aria-live="polite"></p>' +
      '<button type="button" class="hc-today" data-hc-today hidden></button>' +
      '<button type="button" class="hc-nav" data-hc-step="-1">' + CHEVRON.prev + '</button>' +
      '<button type="button" class="hc-nav" data-hc-step="1">' + CHEVRON.next + '</button>' +
      '</div>' +
      '<table class="hc-grid" role="grid" aria-labelledby="homeCalMonth"><thead><tr></tr></thead><tbody></tbody></table>';
    grid = {
      title: els.month.querySelector('.hc-month-title'),
      today: els.month.querySelector('[data-hc-today]'),
      prev: els.month.querySelector('[data-hc-step="-1"]'),
      next: els.month.querySelector('[data-hc-step="1"]'),
      head: els.month.querySelector('thead tr'),
      body: els.month.querySelector('tbody')
    };
  }
  function renderGrid() {
    var hadFocus = grid.body.contains(document.activeElement);
    var en = lang() === 'en';
    grid.title.textContent = monthLabel(state.view, state.todayIso);
    grid.today.textContent = t('home.cal.todayBtn', '오늘');
    grid.today.hidden = state.view === monthOf(state.todayIso);
    grid.prev.setAttribute('aria-label', t('home.cal.prev', '이전 달'));
    grid.next.setAttribute('aria-label', t('home.cal.nextMonth', '다음 달'));
    grid.prev.setAttribute('aria-disabled', String(state.view <= state.minMonth));
    grid.next.setAttribute('aria-disabled', String(state.view >= state.maxMonth));
    grid.head.innerHTML = (en ? DOW_EN : DOW_KO).map(function (name, i) {
      return '<th scope="col"><abbr title="' + (en ? DOW_EN_FULL : DOW_KO_FULL)[i] + '">' + name + '</abbr></th>';
    }).join('');
    grid.body.innerHTML = monthGrid(state.view).map(function (week) {
      return '<tr>' + week.map(cellHtml).join('') + '</tr>';
    }).join('');
    if (hadFocus) focusCell(state.focus);
  }
  function focusCell(iso) {
    var cell = grid.body.querySelector('td[data-date="' + iso + '"]');
    if (cell) cell.focus();
  }

  function metaLines(item) {
    var ev = item.ev;
    var start = F.toKst(ev.startAt);
    var when = '<span class="hc-ev-time">' + esc(start ? hm(start) : t('home.cal.ev.timeTbd', '시간 미정')) + '</span>';
    var place = shortPlace(ev.location);
    var first = (item.active ? '' : esc(t('home.cal.ev.ended', '종료')) + ' · ') + when + (place ? ' · ' + esc(place) : '');
    var second = [foodText(ev)];
    if (item.active && F.tri((ev.registration || {}).required) === 'true') second.push(t('home.cal.ev.reg', '사전 신청'));
    return '<span class="hc-ev-meta">' + first + '</span><span class="hc-ev-meta">' + esc(second.join(' · ')) + '</span>';
  }
  function detailHtml(item) {
    var ev = item.ev;
    var start = F.toKst(ev.startAt);
    var end = F.toKst(ev.endAt);
    var rows = [];
    var when = start ? hm(start) + (end && F.ymd(end) === F.ymd(start) && end > start ? '–' + hm(end) : '') : '';
    var line = [when, fullPlace(ev.location)].filter(Boolean).join(' · ');
    if (line) rows.push('<p class="hc-ev-line">' + esc(line) + '</p>');
    if (ev.eligibility) rows.push('<p class="hc-ev-line">' + esc(fill(t('home.cal.ev.who', '대상 · {who}'), { who: ev.eligibility })) + '</p>');
    var reg = ev.registration || {};
    var deadline = F.toKst(reg.deadline);
    var closed = !item.active || (deadline && deadline < F.nowKst());
    if (deadline && !closed) {
      rows.push('<p class="hc-ev-line">' + esc(fill(t('home.cal.ev.deadline', '신청 마감 · {date}'),
        { date: dateLabel(F.ymd(deadline)) + ' ' + hm(deadline) })) + '</p>');
    }
    var newTab = '<span class="home-sr-only">' + esc(t('home.banner.newTab', '(새 창에서 열림)')) + '</span>';
    var actions = [];
    var regUrl = closed ? '' : safeHref(reg.url);
    if (regUrl) {
      actions.push('<a class="btn btn-primary hc-ev-apply" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' +
        esc(t('home.cal.ev.apply', '신청하기')) + ' <span aria-hidden="true">↗</span>' + newTab + '</a>');
    }
    var source = publicSourceUrl(ev);
    if (source) {
      actions.push('<a class="hc-ev-link" href="' + esc(source) + '" target="_blank" rel="noopener">' +
        esc(t('home.cal.ev.original', '원문 보기')) + ' <span aria-hidden="true">↗</span>' + newTab + '</a>');
    }
    if (actions.length) rows.push('<p class="hc-ev-actions">' + actions.join('') + '</p>');
    var via = sourceKey(ev);
    if (via && !source) rows.push('<p class="hc-ev-src">' + esc(fill(t('home.cal.ev.source', '출처 · {source}'), { source: t(via, '') })) + '</p>');
    return rows.join('');
  }
  function renderDay() {
    if (state.status !== 'ready') {
      els.day.hidden = true;
      els.day.innerHTML = '';
      return;
    }
    var iso = state.selected;
    var rel = iso === state.todayIso ? t('home.cal.rel.today', '오늘')
      : iso === addDays(state.todayIso, 1) ? t('home.cal.rel.tomorrow', '내일') : '';
    var html = '<h3 class="hc-day-title" id="homeCalDayTitle">' + esc(dateLabel(iso)) +
      (rel ? ' <span class="hc-rel">' + esc(rel) + '</span>' : '') + '</h3>';
    var list = state.days[iso] || [];
    if (!list.length) {
      var text;
      if (iso >= state.todayIso) text = t('home.cal.empty', '일정 없음');
      else if (state.archiveStatus === 'error') text = t('home.cal.archiveError', '지난 기록을 불러오지 못했어요');
      else if (state.archiveStatus === 'loading') text = '';
      else text = t('home.cal.noRecord', '기록 없음');
      html += text ? '<p class="hc-empty">' + esc(text) + '</p>' : '';
    } else {
      html += '<ul class="hc-events">' + list.map(function (item, i) {
        var open = state.open === item.ev.id;
        return '<li class="hc-ev' + (item.active ? '' : ' is-past') + '">' +
          '<button type="button" class="hc-ev-btn" data-hc-ev="' + esc(item.ev.id) + '" aria-expanded="' + open +
          '" aria-controls="homeCalEv' + i + '"><span class="hc-ev-title">' + esc(item.ev.title) + '</span>' +
          metaLines(item) + CHEVRON.down + '</button>' +
          '<div class="hc-ev-detail" id="homeCalEv' + i + '"' + (open ? '' : ' hidden') + '>' + detailHtml(item) + '</div></li>';
      }).join('') + '</ul>';
    }
    els.day.innerHTML = html;
    els.day.hidden = false;
  }
  // Only dates after the selected day (or after today, when a past day is selected); never the selected day again.
  function renderNext() {
    var after = state.selected > state.todayIso ? state.selected : state.todayIso;
    var rows = [];
    if (state.status === 'ready') {
      Object.keys(state.days).filter(function (day) { return day > after; }).sort().forEach(function (day) {
        state.days[day].forEach(function (item) {
          if (item.active && rows.length < UPCOMING_ROWS) rows.push({ day: day, item: item });
        });
      });
    }
    if (!rows.length) {
      els.next.hidden = true;
      els.next.innerHTML = '';
      return;
    }
    var html = '<h3 class="hc-next-title" id="homeCalNextTitle">' + esc(t('home.cal.upcoming', '다가오는 꽁밥')) + '</h3>' +
      '<ul class="hc-next-list" aria-labelledby="homeCalNextTitle">';
    rows.forEach(function (row, i) {
      var first = i === 0 || rows[i - 1].day !== row.day;
      var start = F.toKst(row.item.ev.startAt);
      html += '<li><button type="button" class="hc-next-row" data-hc-go="' + row.day + '" data-hc-ev="' + esc(row.item.ev.id) + '">' +
        '<span class="hc-next-date"' + (first ? '' : ' aria-hidden="true"') + '>' + (first ? esc(dateLabel(row.day)) : '') + '</span>' +
        (first ? '' : '<span class="home-sr-only">' + esc(dateLabel(row.day)) + '</span>') +
        '<span class="hc-next-time">' + esc(start ? hm(start) : t('home.cal.ev.timeTbd', '시간 미정')) + '</span>' +
        '<span class="hc-next-name">' + esc(row.item.ev.title) + '</span></button></li>';
    });
    els.next.innerHTML = html + '</ul>';
    els.next.hidden = false;
  }
  function renderHead() {
    els.today.textContent = dateLabel(state.todayIso);
    var kind = state.status;
    var text;
    if (kind === 'loading') text = t('home.free.loading', '꽁밥 일정 확인 중');
    else if (kind === 'error') text = t('home.free.error', '꽁밥 일정을 불러오지 못했어요');
    else {
      var a = answerFor(state.days, state.todayIso);
      kind = a.kind === 'today' ? 'ready' : 'empty';
      text = fill(t('home.cal.answer.' + a.kind, ''), { n: a.n, time: a.time, date: a.date ? dateLabel(a.date) : '' });
    }
    root.setAttribute('data-state', kind);
    els.answer.removeAttribute('data-i18n');
    els.answer.textContent = text;
    els.all.removeAttribute('data-i18n');
    els.all.textContent = state.status === 'error' ? t('home.cal.hub', '꽁밥 페이지 →') : t('home.cal.all', '전체 일정 →');
    var published = state.status === 'ready' && F.toKst(state.live.generatedAt);
    els.published.textContent = published
      ? fill(t('home.free.asOf', '마지막 발행 {time}'), { time: dateLabel(F.ymd(published)) + ' ' + hm(published) }) : '';
  }
  function render() {
    renderHead();
    renderGrid();
    renderDay();
    renderNext();
  }

  function announce(iso) {
    var list = state.days[iso] || [];
    var active = list.filter(function (item) { return item.active; }).length;
    var status = active ? fill(t('home.cal.cell.active', '꽁밥 {n}개'), { n: active })
      : list.length ? fill(t('home.cal.cell.past', '지난 꽁밥 {n}개'), { n: list.length })
      : iso >= state.todayIso ? t('home.cal.empty', '일정 없음') : t('home.cal.noRecord', '기록 없음');
    els.live.textContent = longDateLabel(iso) + ' · ' + status;
  }
  function select(iso, focus) {
    if (!selectable(iso)) return;
    state.touched = true;
    state.selected = iso;
    state.open = '';
    if (!inView(iso)) state.view = monthOf(iso);
    state.focus = iso;
    renderGrid();
    renderDay();
    renderNext();
    if (focus) focusCell(iso);
    announce(iso);
  }
  function moveFocus(iso) {
    if (!selectable(iso)) return;
    state.focus = iso;
    if (!inView(iso)) {
      state.view = monthOf(iso);
      renderGrid();
    } else {
      Array.prototype.forEach.call(grid.body.querySelectorAll('td[data-date]'), function (cell) {
        cell.setAttribute('tabindex', cell.getAttribute('data-date') === iso ? '0' : '-1');
      });
    }
    focusCell(iso);
  }
  function stepMonth(n) {
    var target = addMonths(state.view, n);
    if (target < state.minMonth || target > state.maxMonth) return;
    state.view = target;
    state.focus = rovingFocus();
    renderGrid();
  }
  function goToday() {
    state.touched = false;
    resetView();
    renderGrid();
    renderDay();
    renderNext();
    focusCell(state.focus);
  }
  function toggle(button) {
    var open = button.getAttribute('aria-expanded') !== 'true';
    Array.prototype.forEach.call(els.day.querySelectorAll('.hc-ev-btn[aria-expanded="true"]'), function (other) {
      other.setAttribute('aria-expanded', 'false');
      document.getElementById(other.getAttribute('aria-controls')).hidden = true;
    });
    button.setAttribute('aria-expanded', String(open));
    document.getElementById(button.getAttribute('aria-controls')).hidden = !open;
    state.open = open ? button.getAttribute('data-hc-ev') : '';
  }

  function onClick(e) {
    var target = e.target;
    var cell = target.closest('td[data-date]');
    if (cell && root.contains(cell)) return select(cell.getAttribute('data-date'), true);
    var step = target.closest('[data-hc-step]');
    if (step) {
      if (step.getAttribute('aria-disabled') !== 'true') stepMonth(Number(step.getAttribute('data-hc-step')));
      return;
    }
    if (target.closest('[data-hc-today]')) return goToday();
    var row = target.closest('.hc-ev-btn');
    if (row) return toggle(row);
    var go = target.closest('[data-hc-go]');
    if (go) {
      var id = go.getAttribute('data-hc-ev');
      select(go.getAttribute('data-hc-go'), false);
      var button = els.day.querySelector('.hc-ev-btn[data-hc-ev="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
      if (button) {
        toggle(button);
        button.focus();
      }
    }
  }
  function onKey(e) {
    var cell = e.target.closest && e.target.closest('td[data-date]');
    if (!cell) return;
    var iso = cell.getAttribute('data-date');
    var target;
    switch (e.key) {
      case 'ArrowLeft': target = addDays(iso, -1); break;
      case 'ArrowRight': target = addDays(iso, 1); break;
      case 'ArrowUp': target = addDays(iso, -7); break;
      case 'ArrowDown': target = addDays(iso, 7); break;
      case 'Home': target = addDays(iso, -weekdaySun(iso)); break;      // Sunday of the row
      case 'End': target = addDays(iso, 6 - weekdaySun(iso)); break;    // Saturday of the row
      case 'PageUp': target = shiftMonth(iso, -1); break;
      case 'PageDown': target = shiftMonth(iso, 1); break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        select(iso, true);
        return;
      default: return;
    }
    e.preventDefault();
    moveFocus(target);
  }

  function api() {
    return {
      monthGrid: monthGrid,
      addDays: addDays,
      addMonths: addMonths,
      shiftMonth: shiftMonth,
      weekdaySun: weekdaySun,
      daysInMonth: daysInMonth,
      buildIndex: buildIndex,
      countsOn: countsOn,
      nextActiveDay: nextActiveDay,
      defaultSelection: defaultSelection,
      answerFor: answerFor,
      shortPlace: shortPlace,
      fullPlace: fullPlace,
      publicSourceUrl: publicSourceUrl
    };
  }
  window.BabdodukHomeCalendar = api();

  function getJson(url, allowMissing) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (allowMissing && res.status === 404) return { events: [] }; // not exported yet: nothing archived
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    });
  }
  function settle() {
    refreshIndex();
    if (state.touched && selectable(state.selected)) state.focus = rovingFocus();
    else resetView();
    render();
  }

  mountGrid();
  refreshIndex();
  resetView();
  render();
  root.addEventListener('click', onClick);
  els.month.addEventListener('keydown', onKey);
  document.addEventListener('babdoduk-lang', render);
  // Coming back to the tab after midnight (KST) starts again from the new today. No timers.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible' || state.status === 'loading') return;
    var before = state.todayIso;
    refreshIndex();
    if (state.todayIso !== before) resetView();
    render();
  });

  getJson(LIVE_URL).then(function (data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad');
    state.live = data;
    state.status = 'ready';
  }).catch(function () {
    state.live = null;
    state.status = 'error';
  }).then(settle);
  getJson(ARCHIVE_URL, true).then(function (data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad');
    state.archive = data;
    state.windowDays = Number(data.windowDays) > 0 ? Number(data.windowDays) : ARCHIVE_WINDOW_DAYS;
    state.archiveStatus = 'ready';
  }).catch(function () {
    state.archive = null;
    state.archiveStatus = 'error';
  }).then(function () {
    // Past markers only; the selection a person has made is kept.
    if (state.status !== 'ready') return;
    var selected = state.selected;
    var view = state.view;
    refreshIndex();
    state.selected = selectable(selected) ? selected : state.todayIso;
    state.view = view;
    state.focus = rovingFocus();
    render();
  });
})();
