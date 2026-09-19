/* One event renderer for normal, fixture and localhost preview data. */
(function () {
  var root = document.getElementById('ggongbabFeed');
  if (!root) return;

  var isLab = document.body.hasAttribute('data-gg-lab');
  var isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  var query = new URLSearchParams(location.search);
  function detectMode() {
    if (!isLab) return 'normal';
    if (query.get('preview') === '1') return isLocal ? 'preview' : 'blocked';
    return query.get('fixture') === '1' ? 'fixture' : 'normal';
  }
  var mode = detectMode();
  var DATA_URL = mode === 'preview' ? '.local/ggongbab-preview.json' : 'data/ggongbab/latest.json';
  var debugLayout = isLab && isLocal && query.get('debug-layout') === '1';
  var savedFilter = false;
  var diagnosticOpen = false;
  /* Allowlist: only these keys render, and only when the value is a finite
     number. An unexpected field in a local payload can never reach the page.
     Token counts and cost stay in the terminal summary. */
  var diagnosticKeys = ['loadedRows','dateMatched','readEligible','prefilterCandidates','previewsAvailable',
    'bodyAttempted','bodyFetched','aiAttempted','aiCalls','fallbackCalls','aiErrors','aiSkippedDueToQuota',
    'likelyEvents','explicitFood','needsReview','notEvent','publicCount'];
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
    return ymd(s) >= ymd(today);
  }
  function inFood(ev) {
    if (state.food === 'all') return true;
    return foodBucket(ev) === state.food;
  }
  function isPublic(ev) { return tri((ev.food || {}).provided) === 'true' && !ev.needs_review && !ev.needsReview; }
  function visibleEvents(today) {
    var list = (state.data && state.data.events) || [];
    return list.filter(function (ev) { return isPublic(ev) && inWhen(ev, today) && inFood(ev); }).sort(function (a, b) {
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
    var d = toKst((ev.registration || {}).deadline);
    if (!d) return '';
    var past = d < now;
    var urgent = !past && d - now <= 86400000;
    var label = past ? '신청 마감' : (ymd(d) === ymd(now) ? '오늘 마감 · ' + hm(d) : '마감 · ' + dayLabel(d) + ' ' + hm(d));
    return '<p class="gg-deadline' + (past ? ' is-soft' : urgent ? ' is-urgent' : '') + '">' + esc(label) + '</p>';
  }
  function cardHtml(ev, now) {
    var s = toKst(ev.startAt), e = toKst(ev.endAt);
    var loc = ev.location || {}, food = ev.food || {}, reg = ev.registration || {};
    var pieces = [loc.building, loc.room].filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
    var compactPlace = pieces.join('').replace(/[\s·]/g, '');
    if (loc.name && loc.name.replace(/[\s·]/g, '') !== compactPlace && pieces.indexOf(loc.name) < 0) pieces.push(loc.name);
    var place = pieces.join(' · '), map = mapLink(ev);
    var foodLabel = food.description && food.description.length <= 22 ? food.description : foodTypeLabel(food.type) || '음식 제공';
    var bucket = foodBucket(ev);
    var deadline = toKst(reg.deadline), closed = deadline && deadline < now;
    var html = '<article class="gg-card" data-id="' + esc(ev.id) + '">';
    html += '<div class="gg-card-top"><time class="gg-time' + (s ? '' : ' is-unknown') + '">' + esc(s ? hm(s) : '시간 미정') + '</time>';
    html += '<div class="gg-card-badges"><span class="gg-food-primary is-' + esc(bucket) + '"><span>' + esc(foodLabel) + '</span></span>';
    if (tri(reg.required) === 'true') html += '<span class="gg-reg-badge">' + esc(t('gg.regRequired','사전 신청')) + '</span>';
    if (tri(reg.required) === 'false') html += '<span class="gg-reg-badge is-free">' + esc(t('gg.regNotNeeded','신청 없이 참여')) + '</span>';
    html += '</div></div><h3 class="gg-title">' + esc(ev.title) + '</h3>';
    html += '<p class="gg-place' + (place ? '' : ' is-unknown') + '">' + esc(place || '장소 미정');
    if (map) html += ' · <a href="' + esc(map) + '" target="_blank" rel="noopener">' + esc(t('gg.map','지도')) + '</a>';
    html += '</p>';
    if (ev.eligibility) html += '<p class="gg-eligibility">' + esc(t('gg.eligibility','대상')) + ' · ' + esc(ev.eligibility) + '</p>';
    if (ev.organizer) html += '<p class="gg-organizer">주최 · ' + esc(ev.organizer) + '</p>';
    html += deadlineHtml(ev, now);
    if (ev.summary) html += '<p class="gg-summary">' + esc(ev.summary) + '</p>';
    var regUrl = closed ? '' : safeHref(reg.url);
    var source = (ev.sources || []).filter(function (src) { return src.type === 'kaist_public' || src.type === 'manual'; }).map(function (src) { return safeHref(src.url); }).filter(Boolean)[0];
    if (regUrl || source) {
      html += '<div class="gg-actions">';
      if (regUrl) html += '<a class="gg-btn gg-btn--primary" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' + esc(t('gg.register','신청하기')) + '</a>';
      if (source) html += '<a class="gg-btn" href="' + esc(source) + '" target="_blank" rel="noopener">공식 공지</a>';
      html += '</div>';
    }
    if ((ev.sources || []).length) html += '<p class="gg-source">' + esc((ev.sources || []).some(function (src) { return src.type === 'dooray' || src.type === 'dooray_mailbox'; }) ? 'KAIST 메일' : 'KAIST 공지') + '</p>';
    return html + '</article>';
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
    var list = ((state.data && state.data.events) || []).filter(isPublic);
    var todayN = list.filter(function (ev) { var s = toKst(ev.startAt); return s && ymd(s) === ymd(today); }).length;
    var weekEnd = endOfWeek(today);
    var weekN = list.filter(function (ev) {
      var s = toKst(ev.startAt);
      return s && ymd(s) >= ymd(today) && ymd(s) <= ymd(weekEnd);
    }).length;
    return '<p class="gg-counts"><span>' + esc(t('gg.today', '오늘')) + ' ' + todayN + '개</span><span class="gg-dot">·</span><span>' + esc(t('gg.thisWeek', '이번 주')) + ' ' + weekN + '개</span></p>';
  }
  function stateHtml(kind) {
    if (kind === 'loading') return '<div class="gg-skeleton"></div><div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
    if (kind === 'blocked') return '<div class="gg-state"><strong>Preview mode is available only on localhost.</strong></div>';
    if (kind === 'error' && mode === 'preview') return '<div class="gg-state"><strong>Preview 데이터가 아직 없습니다.</strong><code>python scripts\\dooray_web_agent.py --preview-feed --from 2026-09-01 --to 2026-09-19 --max-mails 1000 --read-state read --cdp</code></div>';
    if (kind === 'error') {
      return '<div class="gg-state"><strong>' + esc(t('gg.errorTitle', '행사 목록을 불러오지 못했어요.')) + '</strong>' + esc(t('gg.errorBody', '잠시 후 다시 시도해 주세요.')) + '<br><button type="button" data-gg-retry>' + esc(t('gg.retry', '다시 시도')) + '</button></div>';
    }
    return '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '이번 조건에 맞는 꽁밥이 아직 없어요.')) + '</strong>' + esc(t('gg.emptyBody', '다른 날짜를 보거나 필터를 바꿔 보세요.')) + '</div>';
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
    } else if (state.status === 'error' || state.status === 'blocked') {
      html += stateHtml(state.status);
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
    renderDiagnostics();
    if (debugLayout) requestAnimationFrame(reportLayout);
  }

  function fixtureData() {
    var today = nowKst();
    function stamp(day, hour) { return ymd(addDays(today, day)) + 'T' + hour + ':00:00+09:00'; }
    var events = [];
    for (var i = 0; i < 10; i++) {
      var day = i < 2 ? 0 : i === 2 ? 1 : Math.min(2, 7 - (today.getDay() || 7));
      events.push({id:'fixture-' + i, title:['캠퍼스 진로 이야기와 점심 한 끼','커피 한 잔, 연구 이야기','함께 나누는 오후의 다과','아이디어와 피자를 나누는 저녁','오늘 신청하는 캠퍼스 워크숍','미리 만나는 연구실 오픈데이','새로운 친구와 함께하는 점심','아주 긴 제목으로 확인하는 캠퍼스 진로 탐색과 융합 연구 협력 그리고 함께하는 따뜻한 식사에 관한 특별한 이야기','긴 소개글이 있는 캠퍼스 모임','다양한 전공이 함께하는 교류회'][i],
        summary: i === 8 ? '누구나 편하게 모여 새로운 연구와 진로에 관한 생각을 나눕니다. '.repeat(12) : '관심 있는 이야기를 나누고, 준비된 음식을 함께 즐겨 보세요.',
        startAt:stamp(day, i === 0 ? '12' : i === 1 ? '15' : '18'), endAt:stamp(day, i === 0 ? '13' : i === 1 ? '16' : '19'),
        location:{building:'N1',room:i === 6 ? '' : '101호',name:'KI빌딩'},
        food:{provided:'true',type:i === 0 ? 'lunchbox' : i === 1 ? 'beverage' : i === 2 ? 'refreshment' : i === 8 ? 'snack' : 'meal',description:i === 0 ? '점심 도시락' : i === 1 ? '커피' : i === 2 ? '커피 · 다과' : i === 8 ? '샌드위치' : '피자 제공'},
        registration:{required:i === 1 ? 'false' : 'true',deadline:i === 4 ? stamp(0,'23') : null,url:i === 0 || i === 4 ? 'https://example.org/register' : ''},
        organizer:i === 9 ? '다양한 전공과 연구실이 함께 기획하고 운영하는 캠퍼스 교류 및 협력 준비위원회'.repeat(3) : '',
        eligibility:i === 9 ? 'KAIST 학부생과 대학원생 및 다양한 연구에 관심 있는 모든 구성원 '.repeat(5) : 'KAIST 학부 및 대학원생',
        sources:[{type:'manual',name:'KAIST 공지',url:'https://example.org/events'}]});
    }
    events[7].title = events[7].title.repeat(3);
    return {generatedAt:new Date().toISOString(),count:events.length,events:events,_preview:{publicCount:events.length,explicitFood:events.length}};
  }
  function acceptData(data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad payload');
    state.data = data;
    state.status = 'ready';
    if (!savedFilter && !visibleEvents(nowKst()).length && data.events.some(function (ev) {
      var s = toKst(ev.startAt); return isPublic(ev) && s && ymd(s) >= ymd(nowKst());
    })) state.when = 'all';
    render();
  }
  function loadData() {
    if (mode === 'blocked') { state.status = 'blocked'; render(); return; }
    state.status = 'loading'; render();
    if (mode === 'fixture') { acceptData(fixtureData()); return; }
    fetch(DATA_URL, {cache:'no-store'}).then(function (res) {
      if (!res.ok) throw new Error('unavailable'); return res.json();
    }).then(acceptData).catch(function () { state.status = 'error'; render(); });
  }
  function renderDiagnostics() {
    var old = document.getElementById('ggDiagnostics');
    if (old) old.remove();
    if (mode !== 'preview' && mode !== 'fixture') return;
    var wrap = document.createElement('div'); wrap.id = 'ggDiagnostics';
    var label = mode.toUpperCase();
    var html = '<button class="gg-diagnostic-toggle' + (mode === 'fixture' ? ' is-fixture' : '') + '" aria-expanded="' + diagnosticOpen + '" aria-controls="ggDiagnosticPanel">' + label + '</button>';
    if (diagnosticOpen) {
      html += '<aside id="ggDiagnosticPanel" class="gg-diagnostic-panel" aria-label="' + label + ' counts"><dl>';
      var counts = (state.data && state.data._preview) || {};
      diagnosticKeys.forEach(function (key) {
        if (typeof counts[key] === 'number' && Number.isFinite(counts[key])) html += '<dt>' + esc(key) + '</dt><dd>' + esc(counts[key]) + '</dd>';
      });
      html += '</dl></aside>';
    }
    wrap.innerHTML = html;
    wrap.querySelector('button').onclick = function () { diagnosticOpen = !diagnosticOpen; renderDiagnostics(); document.querySelector('.gg-diagnostic-toggle').focus(); };
    document.body.appendChild(wrap);
  }
  function measureNav() {
    var nav = document.querySelector('.site-nav');
    var height = nav ? nav.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty('--gg-nav-offset', height + 'px');
    if (isLab) document.body.style.paddingTop = height + 'px';
  }
  function reportLayout() {
    var selectors = ['.site-nav','.ggongbab-page-wrap','.gg-hero','.gg-filters','.gg-day','.gg-card','.gg-card-top','.gg-title','.gg-actions'];
    console.table(selectors.map(function (sel) {
      var el = document.querySelector(sel), r = el && el.getBoundingClientRect();
      return {name:sel,x:r ? Math.round(r.x) : null,y:r ? Math.round(r.y) : null,w:r ? Math.round(r.width) : null,h:r ? Math.round(r.height) : null};
    }));
  }
  if (debugLayout) { var grid = document.createElement('div'); grid.className = 'gg-layout-grid'; grid.setAttribute('aria-hidden','true'); document.body.appendChild(grid); }
  window.addEventListener('resize', measureNav);
  window.addEventListener('load', measureNav);
  if (window.ResizeObserver && document.querySelector('.site-nav')) new ResizeObserver(measureNav).observe(document.querySelector('.site-nav'));
  measureNav();

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
    if (e.target.closest('[data-gg-retry]')) loadData();
  });
  document.addEventListener('babdoduk-lang', render);

  try {
    var saved = JSON.parse(localStorage.getItem('babdoduk-ggongbab-filter') || 'null');
    if (saved && ['today','tomorrow','week','all'].indexOf(saved.when) >= 0) { state.when = saved.when; savedFilter = true; }
    if (saved && ['all','meal','snack','refreshment'].indexOf(saved.food) >= 0) state.food = saved.food;
  } catch (err) {}
  loadData();
})();
