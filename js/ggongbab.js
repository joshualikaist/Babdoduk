/* 꽁밥 event feed. Reads data/ggongbab/latest.json only; never talks to a database. */
(function () {
  var root = document.getElementById('ggongbabFeed');
  if (!root) return;

  var DATA_URL = 'data/ggongbab/latest.json';
  var KST_OFFSET = 9 * 60; // minutes
  var state = { data: null, status: 'loading', error: '', when: 'week', food: 'all' };

  function t(key, fallback) {
    var lang = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function safeHref(url) {
    if (!url) return '';
    try {
      var u = new URL(url, location.href);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
      return u.href;
    } catch (e) { return ''; }
  }

  // --- KST helpers (the feed is campus-local regardless of the viewer's zone) ---
  function toKst(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return new Date(d.getTime() + (d.getTimezoneOffset() + KST_OFFSET) * 60000);
  }
  function nowKst() { return toKst(new Date().toISOString()); }
  function ymd(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function hm(d) { return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }
  function dayLabel(d) {
    var lang = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var dows = lang === 'en' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['일', '월', '화', '수', '목', '금', '토'];
    if (lang === 'en') {
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return months[d.getMonth()] + ' ' + d.getDate() + ' (' + dows[d.getDay()] + ')';
    }
    return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 (' + dows[d.getDay()] + ')';
  }
  function relDay(dayKey, today) {
    if (dayKey === ymd(today)) return t('gg.today', '오늘');
    if (dayKey === ymd(addDays(today, 1))) return t('gg.tomorrow', '내일');
    return '';
  }
  function endOfWeek(today) {
    // Sunday-ending week in KST
    var dow = today.getDay();
    return addDays(today, 7 - (dow === 0 ? 7 : dow));
  }

  // --- tri-state ("true" | "false" | "unknown"). Older payloads used booleans. ---
  function tri(value) {
    if (value === true) return 'true';
    if (value === false) return 'false';
    var s = String(value == null ? 'unknown' : value).toLowerCase();
    return (s === 'true' || s === 'false') ? s : 'unknown';
  }

  // --- filtering ---
  function foodBucket(ev) {
    var f = ev.food || {};
    if (tri(f.provided) !== 'true') return 'none';
    var type = f.type || 'unknown';
    if (type === 'meal' || type === 'lunchbox' || type === 'coupon') return 'meal';
    if (type === 'snack') return 'snack';
    if (type === 'refreshment' || type === 'beverage') return 'refreshment';
    return 'meal';
  }
  function inWhen(ev, today) {
    var s = toKst(ev.startAt);
    if (!s) return false;
    var key = ymd(s);
    if (state.when === 'today') return key === ymd(today);
    if (state.when === 'tomorrow') return key === ymd(addDays(today, 1));
    if (state.when === 'week') {
      var dayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      var weekEnd = endOfWeek(today);
      weekEnd.setHours(23, 59, 59, 999);
      return s >= dayStart && s <= weekEnd;
    }
    return true;
  }
  function inFood(ev) {
    if (state.food === 'all') return true;
    return foodBucket(ev) === state.food;
  }
  function visibleEvents(today) {
    var list = (state.data && state.data.events) || [];
    return list.filter(function (ev) { return inWhen(ev, today) && inFood(ev); }).sort(function (a, b) {
      return String(a.startAt || '').localeCompare(String(b.startAt || ''));
    });
  }

  // --- rendering ---
  function foodTypeLabel(type) {
    return t('gg.food.' + type, {
      meal: '식사', lunchbox: '도시락', snack: '간식', refreshment: '다과', beverage: '음료', coupon: '식권', other: '기타', unknown: ''
    }[type] || '');
  }
  function mapLink(ev) {
    var loc = ev.location || {};
    var q = [loc.building, loc.name].filter(Boolean).join(' ');
    if (!q) return '';
    return 'https://maps.google.com/maps?q=' + encodeURIComponent('KAIST ' + q);
  }
  function deadlineHtml(ev, now) {
    var reg = ev.registration || {};
    if (!reg.deadline) return '';
    var d = toKst(reg.deadline);
    if (!d) return '';
    var isPast = d < now;
    var sameDay = ymd(d) === ymd(now);
    var label = sameDay ? t('gg.deadlineToday', '마감 오늘') + ' ' + hm(d) : t('gg.deadline', '마감') + ' ' + dayLabel(d) + ' ' + hm(d);
    if (isPast) label = t('gg.deadlinePassed', '신청 마감됨');
    return '<p class="gg-deadline' + (isPast ? ' is-soft' : '') + '">' + esc(label) + '</p>';
  }
  function cardHtml(ev, now) {
    var s = toKst(ev.startAt);
    var e = toKst(ev.endAt);
    var loc = ev.location || {};
    var food = ev.food || {};
    var reg = ev.registration || {};
    var place = [loc.building, loc.room].filter(Boolean).join(' ') || loc.name || '';
    var placeExtra = loc.name && place !== loc.name && !(loc.building && loc.name.indexOf(loc.building) >= 0) ? loc.name : '';
    var map = mapLink(ev);
    var past = e ? e < now : (s && new Date(s.getTime() + 3 * 3600000) < now);
    var html = '<article class="gg-card' + (past ? ' is-past' : '') + '" data-id="' + esc(ev.id) + '">';
    html += '<div class="gg-time">' + (s ? esc(hm(s)) : '--:--') + (e ? '<small>~ ' + esc(hm(e)) + '</small>' : (ev.timeText ? '<small>' + esc(ev.timeText) + '</small>' : '')) + '</div>';
    html += '<div class="gg-body">';
    html += '<h3 class="gg-title">' + esc(ev.title) + '</h3>';
    if (place || placeExtra) {
      html += '<p class="gg-place">' + esc(place) + (placeExtra ? ' · ' + esc(placeExtra) : '');
      if (map) html += ' · <a href="' + esc(map) + '" target="_blank" rel="noopener">' + esc(t('gg.map', '지도')) + '</a>';
      html += '</p>';
    }
    html += '<div class="gg-tags">';
    var foodState = tri(food.provided);
    if (foodState === 'true') {
      html += '<span class="gg-tag gg-tag--food">' + esc(food.description || t('gg.foodProvided', '식사 제공')) + '</span>';
      var typeLabel = foodTypeLabel(food.type);
      if (typeLabel) html += '<span class="gg-tag gg-tag--type">' + esc(typeLabel) + '</span>';
    } else if (foodState === 'false') {
      html += '<span class="gg-tag gg-tag--none">' + esc(t('gg.foodNone', '식사 없음')) + '</span>';
    } else {
      html += '<span class="gg-tag gg-tag--unknown">' + esc(t('gg.foodUnknown', '식사 여부 미확인')) + '</span>';
    }
    // "unknown" is never drawn as "no". An unstated fact says so, or shows nothing.
    var regState = tri(reg.required);
    if (regState === 'true') {
      html += '<span class="gg-tag gg-tag--reg">' + esc(t('gg.regRequired', '사전 신청')) + '</span>';
    } else if (regState === 'false') {
      html += '<span class="gg-tag gg-tag--free">' + esc(t('gg.regNotNeeded', '신청 없이 참여')) + '</span>';
    }
    if (ev.organizer) html += '<span class="gg-tag gg-tag--org">' + esc(ev.organizer) + '</span>';
    html += '</div>';
    html += deadlineHtml(ev, now);
    if (ev.summary) html += '<p class="gg-summary">' + esc(ev.summary) + '</p>';
    if (ev.eligibility) html += '<p class="gg-meta">' + esc(t('gg.eligibility', '대상')) + ': ' + esc(ev.eligibility) + '</p>';
    var regUrl = safeHref(reg.url);
    var srcLinks = (ev.sources || []).map(function (src) { return safeHref(src.url); }).filter(Boolean);
    if (regUrl || srcLinks.length) {
      html += '<div class="gg-actions">';
      if (regUrl) html += '<a class="gg-btn gg-btn--primary" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' + esc(t('gg.register', '신청하기')) + '</a>';
      if (srcLinks.length) html += '<a class="gg-btn" href="' + esc(srcLinks[0]) + '" target="_blank" rel="noopener">' + esc(t('gg.source', '원문 보기')) + '</a>';
      html += '</div>';
    }
    var srcNames = (ev.sources || []).map(function (src) { return src.name || src.type; }).filter(Boolean);
    if (srcNames.length) html += '<p class="gg-meta">' + esc(t('gg.via', '출처')) + ': ' + esc(srcNames.join(', ')) + '</p>';
    html += '</div></article>';
    return html;
  }

  function chip(group, value, label, pressed) {
    return '<button type="button" class="gg-chip" data-group="' + group + '" data-value="' + value + '" aria-pressed="' + (pressed ? 'true' : 'false') + '">' + esc(label) + '</button>';
  }
  function filtersHtml() {
    var h = '<div class="gg-filters" role="group" aria-label="' + esc(t('gg.filtersAria', '기간과 음식 종류 필터')) + '">';
    h += '<div class="gg-filter-row">';
    h += chip('when', 'today', t('gg.today', '오늘'), state.when === 'today');
    h += chip('when', 'tomorrow', t('gg.tomorrow', '내일'), state.when === 'tomorrow');
    h += chip('when', 'week', t('gg.thisWeek', '이번 주'), state.when === 'week');
    h += chip('when', 'all', t('gg.upcoming', '전체 예정'), state.when === 'all');
    h += '</div><div class="gg-filter-row">';
    h += chip('food', 'all', t('gg.filter.all', '전체'), state.food === 'all');
    h += chip('food', 'meal', t('gg.filter.meal', '식사'), state.food === 'meal');
    h += chip('food', 'snack', t('gg.filter.snack', '간식'), state.food === 'snack');
    h += chip('food', 'refreshment', t('gg.filter.refreshment', '다과'), state.food === 'refreshment');
    h += '</div></div>';
    return h;
  }
  function countsHtml(today) {
    var list = (state.data && state.data.events) || [];
    var todayN = list.filter(function (ev) { var s = toKst(ev.startAt); return s && ymd(s) === ymd(today); }).length;
    var weekEnd = endOfWeek(today);
    var weekN = list.filter(function (ev) {
      var s = toKst(ev.startAt);
      return s && ymd(s) >= ymd(today) && ymd(s) <= ymd(weekEnd);
    }).length;
    return '<p class="gg-counts"><span>' + esc(t('gg.today', '오늘')) + ' ' + todayN + '</span><span class="gg-dot">·</span><span>' + esc(t('gg.thisWeek', '이번 주')) + ' ' + weekN + '</span></p>';
  }
  function stateHtml(kind) {
    if (kind === 'loading') return '<div class="gg-skeleton"></div><div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
    if (kind === 'error') {
      return '<div class="gg-state"><strong>' + esc(t('gg.errorTitle', '행사 목록을 불러오지 못했어요.')) + '</strong>' + esc(t('gg.errorBody', '잠시 후 다시 시도해 주세요.')) + '<br><button type="button" data-gg-retry>' + esc(t('gg.retry', '다시 시도')) + '</button></div>';
    }
    return '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '이 조건에 맞는 꽁밥 행사가 아직 없어요.')) + '</strong>' + esc(t('gg.emptyBody', '기간이나 음식 종류 필터를 바꿔 보세요. 새 행사는 30분마다 자동으로 모여요.')) + '</div>';
  }

  function render() {
    var today = nowKst();
    var html = '<header class="gg-hero"><h1>' + esc(t('ggongbab.title', '꽁밥')) + '</h1><p class="gg-tagline">' + esc(t('gg.tagline', '설명회 가고 밥도 먹자.')) + '</p>';
    if (state.status === 'ready') html += countsHtml(today);
    html += '</header>';
    html += filtersHtml();
    html += '<div class="gg-feed">';
    if (state.status === 'loading') {
      html += stateHtml('loading');
    } else if (state.status === 'error') {
      html += stateHtml('error');
    } else {
      var events = visibleEvents(today);
      if (!events.length) {
        html += stateHtml('empty');
      } else {
        var lastDay = '';
        events.forEach(function (ev) {
          var s = toKst(ev.startAt);
          var key = ymd(s);
          if (key !== lastDay) {
            lastDay = key;
            var rel = relDay(key, today);
            html += '<h2 class="gg-day">' + (rel ? '<span class="gg-day-rel' + (rel === t('gg.today', '오늘') ? ' is-today' : '') + '">' + esc(rel) + '</span>' : '') + '<span class="gg-day-date">' + esc(dayLabel(s)) + '</span></h2>';
          }
          html += cardHtml(ev, today);
        });
      }
      if (state.data && state.data.generatedAt) {
        var g = toKst(state.data.generatedAt);
        if (g) html += '<p class="gg-updated">' + esc(t('gg.updated', '업데이트')) + ' ' + esc(dayLabel(g) + ' ' + hm(g)) + ' KST</p>';
      }
    }
    html += '</div>';
    root.innerHTML = html;
  }

  function load() {
    state.status = 'loading';
    render();
    fetch(DATA_URL, { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.events)) throw new Error('bad payload');
        state.data = data;
        state.status = 'ready';
        render();
      })
      .catch(function (err) {
        state.status = 'error';
        state.error = String(err && err.message || err);
        render();
      });
  }

  root.addEventListener('click', function (e) {
    var chipEl = e.target.closest('.gg-chip');
    if (chipEl) {
      var group = chipEl.getAttribute('data-group');
      var value = chipEl.getAttribute('data-value');
      if (group === 'when') state.when = value;
      if (group === 'food') state.food = value;
      try { localStorage.setItem('babdoduk-ggongbab-filter', JSON.stringify({ when: state.when, food: state.food })); } catch (err) {}
      render();
      return;
    }
    if (e.target.closest('[data-gg-retry]')) load();
  });
  document.addEventListener('babdoduk-lang', render);

  try {
    var saved = JSON.parse(localStorage.getItem('babdoduk-ggongbab-filter') || 'null');
    if (saved && saved.when) state.when = saved.when;
    if (saved && saved.food) state.food = saved.food;
  } catch (err) {}
  load();
})();
