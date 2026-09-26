/* One event renderer for normal, fixture and localhost preview data. */
(function () {
  var root = document.getElementById('ggongbabFeed');
  if (!root || !window.BabdodukFreeFood) return;
  var F = window.BabdodukFreeFood;

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
  var staleMenuFixture = isLab && isLocal && mode === 'fixture' && query.get('stale-menu') === '1';
  var savedFilter = false;
  var diagnosticOpen = false;
  var diagnosticKeys = ['loadedRows','dateMatched','readEligible','prefilterCandidates','previewsAvailable',
    'bodyAttempted','bodyFetched','aiAttempted','aiCalls','fallbackCalls','aiErrors','aiSkippedDueToQuota',
    'likelyEvents','explicitFood','needsReview','notEvent','publicCount',
    'sourceDoorayCandidates','sourcePortalCandidates','sourcePublicCandidates'];
  var TAB_KEY = 'babdoduk-foodhub-tab';
  var state = {
    activeSection: 'free',
    free: { status: 'loading', data: null, error: '' },
    menu: { status: 'loading', data: null, error: '', meal: 'lunch' },
    when: 'all',
    food: 'all'
  };
  var menuCtl = null;

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
  var toKst = F.toKst, nowKst = F.nowKst, ymd = F.ymd, tri = F.tri, isPublic = F.isPublic, isUpcoming = F.isUpcoming;
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
    var dow = today.getDay();
    return addDays(today, 7 - (dow === 0 ? 7 : dow));
  }
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
  function publicList() {
    return ((state.free.data && state.free.data.events) || []).filter(isPublic);
  }
  function todayUpcoming(now) {
    return F.todayUpcoming(publicList(), now);
  }
  function earliestToday(now) {
    var upcoming = todayUpcoming(now).filter(function (ev) {
      var s = toKst(ev.startAt);
      return s && s >= now;
    });
    return upcoming[0] || null;
  }
  function visibleEvents(today) {
    return publicList().filter(function (ev) { return inWhen(ev, today) && isUpcoming(ev, today) && inFood(ev); }).sort(function (a, b) {
      return String(a.startAt || '').localeCompare(String(b.startAt || ''));
    });
  }
  function futurePublic(now) {
    return F.futurePublic(publicList(), now);
  }
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
  function sourceLabel(ev) {
    var types = (ev.sources || []).map(function (src) { return src.type; });
    if (types.indexOf('dooray') >= 0 || types.indexOf('dooray_mailbox') >= 0) return t('gg.source.mail', 'KAIST 메일');
    if (types.indexOf('portal') >= 0) return t('gg.source.portal', 'KAIST 포탈');
    if (types.indexOf('kaist_public') >= 0) return t('gg.source.public', 'KAIST 공식 공지');
    if (types.indexOf('manual') >= 0) return t('gg.source.manual', '밥도둑 등록');
    return '';
  }
  function deadlineHtml(ev, now) {
    var d = toKst((ev.registration || {}).deadline);
    if (!d) return '';
    var past = d < now;
    var urgent = !past && d - now <= 86400000;
    var label = past ? t('gg.deadlineClosed', '신청 마감')
      : ymd(d) === ymd(now) ? t('gg.deadlineTodayAt', '오늘 마감 · {time}').replace('{time}', hm(d))
      : t('gg.deadlineAt', '마감 · {date}').replace('{date}', dayLabel(d) + ' ' + hm(d));
    return '<p class="gg-deadline' + (past ? ' is-soft' : urgent ? ' is-urgent' : '') + '">' + esc(label) + '</p>';
  }
  function cardHtml(ev, now, featured) {
    var s = toKst(ev.startAt), e = toKst(ev.endAt);
    var loc = ev.location || {}, food = ev.food || {}, reg = ev.registration || {};
    var pieces = [loc.building, loc.room].filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
    var compactPlace = pieces.join('').replace(/[\s·]/g, '');
    if (loc.name && loc.name.replace(/[\s·]/g, '') !== compactPlace && pieces.indexOf(loc.name) < 0) pieces.push(loc.name);
    var place = pieces.join(' · '), map = mapLink(ev);
    var foodLabel = food.description && food.description.length <= 22 ? food.description : foodTypeLabel(food.type) || t('gg.foodFallback', '음식 제공');
    var bucket = foodBucket(ev);
    var deadline = toKst(reg.deadline), closed = deadline && deadline < now;
    var html = '<article class="gg-card' + (featured ? ' is-featured' : '') + '" data-id="' + esc(ev.id) + '"' + (featured ? ' data-featured="1"' : '') + '>';
    if (featured) html += '<p class="gg-featured-label">' + esc(t('gg.next', '다음 꽁밥')) + '</p>';
    html += '<div class="gg-card-top"><time class="gg-time' + (s ? '' : ' is-unknown') + '">' + esc(s ? hm(s) : t('gg.timeTbd', '시간 미정')) + '</time>';
    html += '<div class="gg-card-badges"><span class="gg-food-primary is-' + esc(bucket) + '"><span>' + esc(foodLabel) + '</span></span>';
    if (tri(reg.required) === 'true') html += '<span class="gg-reg-badge">' + esc(t('gg.regRequired','사전 신청')) + '</span>';
    if (tri(reg.required) === 'false') html += '<span class="gg-reg-badge is-free">' + esc(t('gg.regNotNeeded','신청 없이 참여')) + '</span>';
    html += '</div></div><h3 class="gg-title">' + esc(ev.title) + '</h3>';
    html += '<p class="gg-place' + (place ? '' : ' is-unknown') + '">' + esc(place || t('gg.placeTbd', '장소 미정'));
    if (map) html += ' · <a href="' + esc(map) + '" target="_blank" rel="noopener">' + esc(t('gg.map','지도')) + '</a>';
    html += '</p>';
    if (ev.eligibility) html += '<p class="gg-eligibility">' + esc(t('gg.eligibility','대상')) + ' · ' + esc(ev.eligibility) + '</p>';
    if (ev.organizer) html += '<p class="gg-organizer">' + esc(t('gg.organizer', '주최')) + ' · ' + esc(ev.organizer) + '</p>';
    html += deadlineHtml(ev, now);
    if (ev.summary) html += '<p class="gg-summary">' + esc(ev.summary) + '</p>';
    var regUrl = closed ? '' : safeHref(reg.url);
    var source = (ev.sources || []).filter(function (src) { return src.type === 'kaist_public' || src.type === 'manual'; }).map(function (src) { return safeHref(src.url); }).filter(Boolean)[0];
    if (regUrl || source) {
      html += '<div class="gg-actions">';
      if (regUrl) html += '<a class="gg-btn gg-btn--primary" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' + esc(t('gg.register','신청하기')) + '</a>';
      if (source) html += '<a class="gg-btn" href="' + esc(source) + '" target="_blank" rel="noopener">' + esc(t('gg.officialNotice', '공식 공지')) + '</a>';
      html += '</div>';
    }
    var via = sourceLabel(ev);
    if (via) html += '<p class="gg-source">' + esc(via) + '</p>';
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
  function radarCopy(count) {
    if (count <= 0) return t('gg.radar.zero', '🌵 오늘은 꽁밥 가뭄');
    if (count <= 2) return t('gg.radar.some', '🍙 한 끼는 건질 수 있어요');
    return t('gg.radar.many', '🔥 오늘 꽁밥 풍년');
  }
  function radarHtml(now) {
    var today = todayUpcoming(now);
    var next = earliestToday(now);
    var html = '<section class="gg-radar" aria-label="' + esc(t('gg.radar.label', '오늘의 꽁밥 레이더')) + '">';
    html += '<p class="gg-radar-label">' + esc(t('gg.radar.label', '오늘의 꽁밥 레이더')) + '</p>';
    html += '<h2 class="gg-radar-title">' + esc(radarCopy(today.length)) + '</h2>';
    html += '<p class="gg-radar-count">' + esc(t('gg.radar.count', '오늘 {n}개').replace('{n}', String(today.length))) + '</p>';
    if (next) {
      var s = toKst(next.startAt);
      var food = (next.food || {}).description || foodTypeLabel((next.food || {}).type) || t('gg.foodProvided', '식사 제공');
      var loc = next.location || {};
      var place = loc.building || loc.name || '';
      html += '<p class="gg-radar-next"><strong>' + esc(t('gg.radar.next', '가장 빠른 꽁밥')) + '</strong>' +
        esc((s ? hm(s) : t('gg.timeTbd', '시간 미정')) + ' · ' + food + (place ? ' · ' + place : '')) + '</p>';
      html += '<button type="button" class="gg-radar-cta" data-gg-scroll="' + esc(next.id) + '">' + esc(t('gg.radar.cta', '자세히 보기 →')) + '</button>';
    }
    return html + '</section>';
  }
  function metricHtml(now, menuSnap) {
    var freeN = todayUpcoming(now).length;
    menuSnap = menuSnap || (menuCtl && menuCtl.snapshot ? menuCtl.snapshot() : { status: state.menu.status, stale: true, restaurantCount: 0 });
    var menuPart;
    if (menuSnap.status === 'loading' || state.menu.status === 'loading') menuPart = t('gg.metric.menuLoading', '학식 확인 중');
    else if (menuSnap.status === 'error' || state.menu.status === 'error') menuPart = t('gg.metric.menuError', '학식 불러오기 실패');
    else if (menuSnap.stale) menuPart = t('gg.metric.menuStale', '학식 업데이트 중');
    else menuPart = t('gg.metric.menu', '학식 {n}곳').replace('{n}', String(menuSnap.restaurantCount || 0));
    var freePart = state.free.status === 'ready'
      ? t('gg.metric.free', '오늘 꽁밥 {n}개').replace('{n}', String(freeN))
      : state.free.status === 'loading' ? t('gg.metric.freeLoading', '오늘 꽁밥 확인 중')
      : t('gg.metric.freeError', '꽁밥 불러오기 실패');
    return '<p class="gg-counts">' + esc(freePart + ' · ' + menuPart) + '</p>';
  }
  function tabsHtml() {
    var todayN = todayUpcoming(nowKst()).length;
    var html = '<div class="food-hub-tabs" role="tablist" aria-label="' + esc(t('gg.tabsAria', '꽁밥과 학식')) + '">';
    var free = state.activeSection === 'free';
    html += '<button type="button" class="food-hub-tab" role="tab" id="foodHubTabFree" data-hub-tab="free" aria-controls="foodHubFree" aria-selected="' + free + '" tabindex="' + (free ? 0 : -1) + '">🎁 ' + esc(t('gg.tab.free', '꽁밥')) + '  ' + todayN + '</button>';
    html += '<button type="button" class="food-hub-tab" role="tab" id="foodHubTabMenu" data-hub-tab="menu" aria-controls="foodHubMenu" aria-selected="' + !free + '" tabindex="' + (free ? -1 : 0) + '">🍚 ' + esc(t('gg.tab.menu', '오늘의 학식')) + '</button>';
    return html + '</div>';
  }
  function emptyFreeHtml(now) {
    var menuSnap = menuCtl && menuCtl.snapshot ? menuCtl.snapshot() : { restaurantCount: 0, stale: true };
    var menuN = menuSnap.stale ? 0 : (menuSnap.restaurantCount || 0);
    var html = '<div class="gg-state">';
    html += '<strong>' + esc(t('gg.emptyTodayTitle', '🌵 오늘은 꽁밥 가뭄이에요')) + '</strong>';
    html += esc(t('gg.emptyTodayBody', '아직 확인된 꽁밥 행사가 없어요. 대신 오늘 학식 {n}곳의 메뉴가 있어요.').replace('{n}', String(menuN)));
    html += '<br><button type="button" class="km-cta" data-hub-tab="menu">' + esc(t('gg.toMenu', '오늘 학식 보러가기 →')) + '</button></div>';
    if (!futurePublic(now).length) {
      html += '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '이번 조건에 맞는 꽁밥이 아직 없어요.')) + '</strong>' + esc(t('gg.emptyBody', '다른 날짜를 보거나 필터를 바꿔 보세요.')) + '</div>';
    }
    return html;
  }
  function stateHtml(kind) {
    if (kind === 'loading') return '<div class="gg-skeleton"></div><div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
    if (kind === 'blocked') return '<div class="gg-state"><strong>Preview mode is available only on localhost.</strong></div>';
    if (kind === 'error' && mode === 'preview') return '<div class="gg-state"><strong>Preview 데이터가 아직 없습니다.</strong><code>python scripts\\dooray_web_agent.py --preview-feed --from 2026-09-01 --to 2026-09-19 --max-mails 1000 --read-state read --cdp</code></div>';
    if (kind === 'error') {
      var html = '<div class="gg-state"><strong>' + esc(t('gg.errorTitle', '행사 목록을 불러오지 못했어요.')) + '</strong>' + esc(t('gg.errorBody', '잠시 후 다시 시도해 주세요.'));
      html += '<br><button type="button" data-gg-retry>' + esc(t('gg.retry', '다시 시도')) + '</button>';
      html += '<button type="button" class="km-cta is-ghost" data-hub-tab="menu">' + esc(t('gg.toMenu', '오늘 학식 보러가기 →')) + '</button></div>';
      return html;
    }
    return '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '이번 조건에 맞는 꽁밥이 아직 없어요.')) + '</strong>' + esc(t('gg.emptyBody', '다른 날짜를 보거나 필터를 바꿔 보세요.')) + '</div>';
  }
  // What this list is (the public current and upcoming rows only; ended rows
  // leave it) and when the snapshot was published. It makes no freshness claim
  // beyond that time.
  function feedNoteHtml() {
    var html = '<div class="gg-feed-note"><p class="gg-lifecycle">' +
      esc(t('gg.lifecycle', '공개된 현재·예정 꽁밥만 보여 드려요. 끝난 일정은 목록에서 자동으로 내려가요.')) + '</p>';
    var g = state.free.data && toKst(state.free.data.generatedAt);
    if (g) html += '<p class="gg-updated">' + esc(t('gg.updated', '마지막 발행')) + ' ' + esc(dayLabel(g) + ' ' + hm(g)) + ' KST</p>';
    return html + '</div>';
  }
  function freePaneHtml(now) {
    var html = '';
    if (state.free.status === 'ready') html += radarHtml(now);
    else if (state.free.status === 'loading') html += '<div class="gg-skeleton" style="height:160px"></div>';
    html += filtersHtml();
    html += '<div class="gg-feed">';
    if (state.free.status === 'loading') html += stateHtml('loading');
    else if (state.free.status === 'error' || state.free.status === 'blocked') html += stateHtml(state.free.status);
    else {
      html += feedNoteHtml();
      var events = visibleEvents(now);
      var featuredId = (earliestToday(now) || {}).id;
      if (!events.length) {
        if (!todayUpcoming(now).length) html += emptyFreeHtml(now);
        else html += stateHtml('empty');
      } else {
        var lastDay = '';
        events.forEach(function (ev) {
          var s = toKst(ev.startAt);
          var key = ymd(s);
          if (key !== lastDay) {
            lastDay = key;
            var rel = relDay(key, now);
            html += '<h2 class="gg-day">' + (rel ? '<span class="gg-day-rel' + (rel === t('gg.today', '오늘') ? ' is-today' : '') + '">' + esc(rel) + '</span>' : '') + '<span class="gg-day-date">' + esc(dayLabel(s)) + '</span></h2>';
          }
          html += cardHtml(ev, now, ev.id === featuredId);
        });
      }
    }
    return html + '</div>';
  }
  function render() {
    var now = nowKst();
    var focus = focusSelector();
    var html = '<header class="gg-hero"><h1>' + esc(t('ggongbab.title', '오늘의 꽁밥')) + '</h1><p class="gg-tagline">' + esc(t('gg.tagline', 'KAIST 학식 메뉴와 공개된 꽁밥 일정을 한곳에서 확인해요.')) + '</p>';
    html += metricHtml(now);
    html += '</header>';
    html += tabsHtml();
    html += '<div id="foodHubFree" class="food-hub-free" role="tabpanel" aria-labelledby="foodHubTabFree"' + (state.activeSection === 'free' ? '' : ' hidden') + '>';
    html += freePaneHtml(now);
    html += '</div>';
    html += '<div id="foodHubMenu" class="food-hub-menu" role="tabpanel" aria-labelledby="foodHubTabMenu"' + (state.activeSection === 'menu' ? '' : ' hidden') + '></div>';
    html += '<aside class="gg-choose" aria-labelledby="ggChooseTitle"><p class="gg-choose-title" id="ggChooseTitle">' + esc(t('gg.choose.title', '뭘 먹을지 아직 못 정했다면')) + '</p>';
    html += '<p class="gg-choose-body">' + esc(t('gg.choose.body', '학식·꽁밥과 별개로 음식 아이디어를 골라 드려요. 실제 판매 여부는 가게에서 확인해 주세요.')) + '</p>';
    html += '<a class="gg-choose-link" href="mukbang.html#what">' + esc(t('gg.choose.cta', '메뉴 고르기 →')) + '</a></aside>';
    root.innerHTML = html;
    if (focus) {
      var again = root.querySelector(focus);
      if (again) again.focus({ preventScroll: true });
    }
    bindMenu(now);
    renderDiagnostics();
    if (debugLayout) requestAnimationFrame(reportLayout);
  }
  // render() replaces the feed markup; keep a keyboard user's place on the same control.
  function focusSelector() {
    var el = document.activeElement;
    if (!el || el === root || !root.contains(el)) return '';
    if (el.id) return '#' + el.id;
    var parts = [];
    Array.prototype.forEach.call(el.attributes, function (attr) {
      if (attr.name.indexOf('data-') === 0) parts.push('[' + attr.name + '="' + String(attr.value).replace(/["\\]/g, '') + '"]');
    });
    return parts.length ? el.tagName.toLowerCase() + parts.join('') : '';
  }
  function bindMenu(now) {
    var host = document.getElementById('foodHubMenu');
    if (!host || !window.BabdodukKaistMenu) return;
    var freeN = todayUpcoming(now).length;
    var freeText = t('gg.menu.freeHint', '꽁밥은 {n}개 있어요.').replace('{n}', String(freeN));
    if (menuCtl) {
      menuCtl.setFreeCountText(freeText);
      menuCtl.mount(host);
      return;
    }
    var opts = {
      onChange: function (snap) {
        state.menu.status = snap.status;
        state.menu.data = snap.data;
        state.menu.error = snap.error || '';
        var metric = document.querySelector('.gg-counts');
        if (metric) metric.outerHTML = metricHtml(nowKst(), snap);
      },
      freeCountText: freeText
    };
    if (mode === 'fixture') {
      opts.getData = function () { return window.BabdodukKaistMenu.fixtureMenu(staleMenuFixture, nowKst()); };
    }
    menuCtl = window.BabdodukKaistMenu.attach(host, opts);
  }
  function fixtureData() {
    var today = nowKst();
    function stamp(day, hour) { return ymd(addDays(today, day)) + 'T' + hour + ':00:00+09:00'; }
    var titles = ['캠퍼스 진로 이야기와 점심 한 끼','커피 한 잔, 연구 이야기','함께 나누는 오후의 다과','아이디어와 피자를 나누는 저녁','오늘 신청하는 캠퍼스 워크숍','미리 만나는 연구실 오픈데이','새로운 친구와 함께하는 점심','아주 긴 제목으로 확인하는 캠퍼스 진로 탐색과 융합 연구 협력 그리고 함께하는 따뜻한 식사에 관한 특별한 이야기','긴 소개글이 있는 캠퍼스 모임','다양한 전공이 함께하는 교류회'];
    var sourceCycle = [
      [{ type: 'dooray', name: 'Dooray' }],
      [{ type: 'portal', name: 'KAIST Portal' }],
      [{ type: 'kaist_public', name: 'KAIST 공지', url: 'https://example.org/events' }],
      [{ type: 'manual', name: 'Manual', url: 'https://example.org/events' }]
    ];
    var events = [];
    for (var i = 0; i < 10; i++) {
      var day = i < 3 ? 0 : i === 3 ? 1 : Math.min(2, 7 - (today.getDay() || 7));
      events.push({
        id: 'fixture-' + i,
        title: titles[i],
        summary: i === 8 ? '누구나 편하게 모여 새로운 연구와 진로에 관한 생각을 나눕니다. '.repeat(12) : '관심 있는 이야기를 나누고, 준비된 음식을 함께 즐겨 보세요.',
        startAt: stamp(day, i === 0 ? '12' : i === 1 ? '15' : '18'),
        endAt: stamp(day, i === 0 ? '13' : i === 1 ? '16' : '19'),
        location: { building: 'N1', room: i === 6 ? '' : '101호', name: 'KI빌딩' },
        food: { provided: 'true', type: i === 0 ? 'lunchbox' : i === 1 ? 'beverage' : i === 2 ? 'refreshment' : i === 8 ? 'snack' : 'meal', description: i === 0 ? '점심 도시락' : i === 1 ? '커피' : i === 2 ? '커피 · 다과' : i === 8 ? '샌드위치' : '피자 제공' },
        registration: { required: i === 1 ? 'false' : 'true', deadline: i === 4 ? stamp(0, '23') : null, url: i === 0 || i === 4 ? 'https://example.org/register' : '' },
        organizer: i === 9 ? '다양한 전공과 연구실이 함께 기획하고 운영하는 캠퍼스 교류 및 협력 준비위원회'.repeat(3) : '',
        eligibility: i === 9 ? 'KAIST 학부생과 대학원생 및 다양한 연구에 관심 있는 모든 구성원 '.repeat(5) : 'KAIST 학부 및 대학원생',
        sources: sourceCycle[i % 4]
      });
    }
    events[7].title = events[7].title.repeat(3);
    return { generatedAt: new Date().toISOString(), count: events.length, events: events, _preview: { publicCount: events.length, explicitFood: events.length } };
  }
  function acceptFree(data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad payload');
    state.free.data = data;
    state.free.status = 'ready';
    if (!savedFilter && !visibleEvents(nowKst()).length && data.events.some(function (ev) {
      var s = toKst(ev.startAt); return isPublic(ev) && s && ymd(s) >= ymd(nowKst());
    })) state.when = 'all';
    render();
  }
  function loadFree() {
    if (mode === 'blocked') { state.free.status = 'blocked'; render(); return; }
    state.free.status = 'loading';
    render();
    if (mode === 'fixture') { acceptFree(fixtureData()); return; }
    fetch(DATA_URL, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('unavailable'); return res.json();
    }).then(acceptFree).catch(function () { state.free.status = 'error'; render(); });
  }
  function setTab(tab) {
    if (tab !== 'menu') tab = 'free';
    state.activeSection = tab;
    try { localStorage.setItem(TAB_KEY, tab); } catch (err) {}
    var freePane = document.getElementById('foodHubFree');
    var menuPane = document.getElementById('foodHubMenu');
    document.querySelectorAll('.food-hub-tab').forEach(function (btn) {
      var on = btn.getAttribute('data-hub-tab') === tab;
      btn.setAttribute('aria-selected', String(on));
      btn.setAttribute('tabindex', on ? '0' : '-1');
    });
    if (freePane) freePane.hidden = tab !== 'free';
    if (menuPane) menuPane.hidden = tab !== 'menu';
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
      var counts = (state.free.data && state.free.data._preview) || {};
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
    var selectors = ['.site-nav','.ggongbab-page-wrap','.gg-hero','.food-hub-tabs','.gg-radar','.gg-filters','.gg-day','.gg-card','.gg-card-top','.gg-title','.gg-actions','.km-card'];
    console.table(selectors.map(function (sel) {
      var el = document.querySelector(sel), r = el && el.getBoundingClientRect();
      return { name: sel, x: r ? Math.round(r.x) : null, y: r ? Math.round(r.y) : null, w: r ? Math.round(r.width) : null, h: r ? Math.round(r.height) : null };
    }));
  }
  if (debugLayout) { var grid = document.createElement('div'); grid.className = 'gg-layout-grid'; grid.setAttribute('aria-hidden', 'true'); document.body.appendChild(grid); }
  window.addEventListener('resize', measureNav);
  window.addEventListener('load', measureNav);
  if (window.ResizeObserver && document.querySelector('.site-nav')) new ResizeObserver(measureNav).observe(document.querySelector('.site-nav'));
  measureNav();

  root.addEventListener('click', function (e) {
    var tabEl = e.target.closest('[data-hub-tab]');
    if (tabEl) {
      setTab(tabEl.getAttribute('data-hub-tab'));
      return;
    }
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
    var scrollBtn = e.target.closest('[data-gg-scroll]');
    if (scrollBtn) {
      var target = document.querySelector('[data-id="' + scrollBtn.getAttribute('data-gg-scroll') + '"]');
      if (target) {
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        target.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' });
        target.setAttribute('tabindex', '-1');
        target.focus({ preventScroll: true });
      }
      return;
    }
    if (e.target.closest('[data-gg-retry]')) loadFree();
  });
  root.addEventListener('keydown', function (e) {
    var tab = e.target.closest && e.target.closest('.food-hub-tab');
    if (!tab) return;
    var tabs = Array.prototype.slice.call(root.querySelectorAll('.food-hub-tab'));
    var at = tabs.indexOf(tab), next = -1;
    if (e.key === 'ArrowRight') next = (at + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (at - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    setTab(tabs[next].getAttribute('data-hub-tab'));
    tabs[next].focus();
  });
  document.addEventListener('babdoduk-lang', render);

  try {
    var saved = JSON.parse(localStorage.getItem('babdoduk-ggongbab-filter') || 'null');
    if (saved && ['today', 'tomorrow', 'week', 'all'].indexOf(saved.when) >= 0) { state.when = saved.when; savedFilter = true; }
    if (saved && ['all', 'meal', 'snack', 'refreshment'].indexOf(saved.food) >= 0) state.food = saved.food;
  } catch (err) {}
  try {
    var tabSaved = localStorage.getItem(TAB_KEY);
    if (tabSaved === 'menu' || tabSaved === 'free') state.activeSection = tabSaved;
  } catch (err) {}
  if (location.hash === '#menu' || location.hash === '#free') state.activeSection = location.hash.slice(1);
  window.addEventListener('hashchange', function () {
    if (location.hash === '#menu' || location.hash === '#free') setTab(location.hash.slice(1));
  });
  loadFree();
})();
