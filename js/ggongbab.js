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
  var diagnosticOpen = false;
  var diagnosticKeys = ['loadedRows','dateMatched','readEligible','prefilterCandidates','previewsAvailable',
    'bodyAttempted','bodyFetched','aiAttempted','aiCalls','fallbackCalls','aiErrors','aiSkippedDueToQuota',
    'likelyEvents','explicitFood','needsReview','notEvent','publicCount',
    'sourceDoorayCandidates','sourcePortalCandidates','sourcePublicCandidates'];
  var TAB_KEY = 'babdoduk-foodhub-tab';
  // Past listings: a separate static file, loaded on its own so a failure never touches the live feed.
  var ARCHIVE_URL = 'data/ggongbab/archive/index.json';
  var ARCHIVE_WINDOW_DAYS = 30;
  var state = {
    activeSection: 'free',
    free: { status: 'loading', data: null },
    menu: { status: 'loading' },
    archive: { status: 'loading', data: null, expanded: false },
    news: { status: 'loading', items: [] },
    open: {},                 // the listings opened to their details (2026-11-05)
    food: 'all',
    // 꽁밥 LIVE (docs/GGONGBAB_LIVE.md): the optional filters, never saved (the date is relative to
    // today; the saved filter object keeps its {when, food} shape), the saved listings and the share link.
    day: 'all', who: 'all', area: 'all',
    moreFilters: false,
    savedOpen: false,
    calOpen: {},              // the listings whose calendar choices are open
    copy: null,               // {key, text}: what to copy by hand when sharing and copying both failed
    entry: { id: '', week: '', done: false, notice: null }
  };
  var L = window.BabdodukLive;
  var savedStore = L ? L.createStore() : null;
  // 마이 밥도둑 (docs/MY_BABDODUK.md): someone signed in on this browser sees and edits the account's
  // list instead; guests never load the sign-in client. The guest list in this browser stays as it is.
  var accountMode = '';
  if (L && window.BabdodukAccount) {
    window.BabdodukAccount.attachSavedStore(function (store, failed) {
      if (store) { savedStore = store; accountMode = 'account'; pushChanged(); } else if (failed) accountMode = 'failed';
      render();
    }, function (kind) {
      if (kind === 'failed') { announce(t('gg.live.syncFail', '저장하지 못했어요. 다시 시도해 주세요.')); render(); }
    });
  }
  // 별 누른 꽁밥 30분 전 알림 (docs/PUSH_ALERTS.md): 'hidden' until the browser says otherwise.
  var P = L ? window.BabdodukPush || null : null;
  var pushState = 'hidden';
  function langCode() { return window.babdodukGetLang && window.babdodukGetLang() === 'en' ? 'en' : 'ko'; }
  function savedIds() { return savedStore ? savedStore.list().map(function (item) { return item.id; }) : []; }
  function pushRefresh() {
    if (!P) return;
    P.status().then(function (s) {
      var was = pushState;
      pushState = s;
      if (s === 'on') P.sync(savedIds(), langCode());
      if (was !== s) render();
    });
  }
  function pushChanged() { if (P && pushState === 'on') P.changed(savedIds(), langCode()); }
  var NOTICE_KEY = 'babdoduk-notice-ggongbab-live';
  var DAY_FILTERS = ['all', 'today', 'week', 'next'];
  var WHO_FILTERS = ['all', 'fresh', 'undergrad', 'grad', 'open', 'check'];
  var AREA_FILTERS = ['all', 'north', 'east', 'west', 'unknown'];
  var menuCtl = null;
  var feedCtl = null;
  // Query isolation also applies to the public page, where lab fixtures remain
  // unreachable: those URLs use the public JSON, never a database connection.
  var allowLiveFeed = mode === 'normal' && query.get('preview') !== '1' && query.get('fixture') !== '1';

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
  var hasFood = F.hasFood, hasGiveaway = F.hasGiveaway, isDeadlineOnly = F.isDeadlineOnly;
  // The food-type row: the food buckets, then giveaways (a listing of its own, never a food type).
  var FOOD_FILTERS = ['all', 'meal', 'snack', 'refreshment', 'giveaway'];
  var GIFT = '<span aria-hidden="true">🎁</span> ';
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
  function foodBucket(ev) {
    var f = ev.food || {};
    if (tri(f.provided) !== 'true') return 'none';
    var type = f.type || 'unknown';
    if (type === 'meal' || type === 'lunchbox' || type === 'coupon') return 'meal';
    if (type === 'snack') return 'snack';
    if (type === 'refreshment' || type === 'beverage') return 'refreshment';
    return 'meal';
  }
  // Everything from today on (owner 2026-11-05: the day tiles went, "사람들이 내려보면서 보면되지").
  // Rows are one per session day already (F.occurrences), so a row matches on its own start.
  function fromToday(ev, today) {
    var s = toKst(ev.startAt);
    return !!s && ymd(s) >= ymd(today);
  }
  // A food chip matches only rows with explicit food (a giveaway-only row is in no food bucket);
  // the giveaway chip matches every giveaway, with or without food.
  function inFood(ev) {
    if (state.food === 'all') return true;
    if (state.food === 'giveaway') return hasGiveaway(ev);
    return foodBucket(ev) === state.food;
  }
  function publicList() {
    return ((state.free.data && state.free.data.events) || []).filter(isPublic);
  }
  // Free food only (F.todayUpcoming): the radar, the hero metric, the tab and the cafeteria hint
  // count it; a giveaway-only listing is shown but never counted.
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
  // The optional filters: date (KST), who the source says it is for, campus area by building number.
  function inMore(ev, now) {
    if (!L) return true;
    if (state.day !== 'all' && !L.inDays(ev, state.day, now)) return false;
    if (state.who !== 'all' && L.whoOf(ev).indexOf(state.who) < 0) return false;
    if (state.area !== 'all' && L.areaOf(ev) !== state.area) return false;
    return true;
  }
  function moreCount() {
    return (state.day !== 'all') + (state.who !== 'all') + (state.area !== 'all');
  }
  function filtersActive() { return state.food !== 'all' || moreCount() > 0; }
  function visibleEvents(today) {
    return publicList().filter(function (ev) { return fromToday(ev, today) && isUpcoming(ev, today) && inFood(ev) && inMore(ev, today); }).sort(function (a, b) {
      return String(a.startAt || '').localeCompare(String(b.startAt || ''));
    });
  }
  function futurePublic(now) {
    return F.futurePublic(publicList(), now);
  }
  function foodTypeLabel(type) {
    return t('gg.food.' + type, '');      // the page's tables carry every type (data/content/labels.json)
  }
  function mapLink(ev) {
    var loc = ev.location || {};
    var q = [loc.building, loc.name].filter(Boolean).join(' ');
    if (!q) return '';
    return 'https://maps.google.com/maps?q=' + encodeURIComponent('KAIST ' + q);
  }
  function sourceLabel(ev) {
    var group = F.sourceGroup(ev);
    return group ? t('gg.source.' + group, '') : '';
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
  function pageLang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function placePieces(ev) {
    var loc = ev.location || {};
    return [loc.building, loc.room].filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
  }
  // The full place, for the details. The written-out name joins only when it adds something and is
  // in the page's language: a bilingual mail's English building names stayed on the Korean page
  // ("E6-1 / E4 · 1501 / C101 · Natural Science Building, …", 2026-11-05).
  function placeLabel(ev) {
    var loc = ev.location || {};
    var pieces = placePieces(ev);
    var compactPlace = pieces.join('').replace(/[\s·]/g, '');
    var held = pieces.some(function (piece) { return piece.indexOf(loc.name) >= 0; });
    if (loc.name && loc.name.replace(/[\s·]/g, '') !== compactPlace && !held &&
        (!pieces.length || F.inLang(loc.name, pageLang()))) pieces.push(loc.name);
    return pieces.join(' · ');
  }
  // The row's place: the building and room only (the name when there is nothing else).
  function shortPlace(ev) {
    var pieces = placePieces(ev);
    return pieces.length ? pieces.join(' · ') : String((ev.location || {}).name || '');
  }
  // Only for explicit food: a giveaway-only listing never gets a food label or the "음식 제공" fallback.
  function foodLabelOf(ev) {
    if (!hasFood(ev)) return '';
    var food = ev.food || {};
    return food.description && food.description.length <= 22 ? food.description : foodTypeLabel(food.type) || t('gg.foodFallback', '음식 제공');
  }
  // The stated food in full, for the details: only in the page's language and only when it says more
  // than the dish on the row ("현장 참석자 샌드위치 제공" says who gets it; "샌드위치" does not).
  function foodDetailOf(ev) {
    var text = String((ev.food || {}).description || '').trim();
    if (!hasFood(ev) || !text || !F.inLang(text, pageLang())) return '';
    var bare = function (value) { return value.replace(/제공|및|그리고|\band\b|[\s·,+&/()와과]/gi, '').toLowerCase(); };
    return bare(text) === bare(F.dishLabel(ev, t)) ? '' : text;
  }
  // The food badge: the dish in a word or two (F.dishes).
  function foodBadgeHtml(ev) {
    if (!hasFood(ev)) return '';
    var html = '<span class="gg-food-primary is-' + esc(foodBucket(ev)) + '"><span>' + esc(F.dishLabel(ev, t)) + '</span>';
    return html + '</span>';
  }
  function giveawayText(ev) {
    return hasGiveaway(ev) ? String(ev.giveaway.description || '').trim() : '';
  }
  // A deadline-only giveaway's date is its sign-up deadline, never an event time.
  function signUpByText(s) {
    return t('gg.giveaway.signUpBy', '신청 마감 {date}').replace('{date}', dayLabel(s) + ' ' + hm(s));
  }
  // Only public web pages (KAIST notices, Babdoduk's own entries, an Instagram post) are linked;
  // internal sources never are. {type, url} or null.
  function publicSource(ev) {
    var link = F.sourceLink(ev), url = link ? safeHref(link.url) : '';
    return url ? { type: link.type, url: url } : null;
  }
  // One listing (owner 2026-11-05: "시간 | 행사 / 세부내용(작은 글씨, 연하게)", the food in bold):
  //   12:00   샌드위치 (🎁 경품)                         신청
  //           2026 노벨 … 강연회 · E9 양승택오디토리움      (small, muted, two lines at most)
  // A transparent button covers the row (not the opened details) and opens the rest (food in full, the whole place and map,
  // giveaway, audience, organizer, deadline, summary, links, source); links sit above it.
  var cardSeq = 0;
  function cardHtml(ev, now, featured) {
    var s = toKst(ev.startAt);
    var reg = ev.registration || {}, sign = F.signUp(ev);
    var place = placeLabel(ev), map = mapLink(ev), where = shortPlace(ev);
    var gift = hasGiveaway(ev), giftText = giveawayText(ev);
    var deadlineOnly = isDeadlineOnly(ev);
    var deadline = toKst(reg.deadline), closed = deadline && deadline < now;
    var regUrl = closed ? '' : safeHref(sign.url);
    var open = !!state.open[ev.id];
    var n = ++cardSeq, detailId = 'ggCard' + n, titleId = 'ggCardTitle' + n;
    var html = '<article class="gg-card' + (featured ? ' is-featured' : '') + (open ? ' is-open' : '') + '" data-id="' + esc(ev.id) + '"' + (featured ? ' data-featured="1"' : '') + '>';
    html += '<div class="gg-card-top' + (deadlineOnly ? ' is-deadline' : '') + '">' +
      '<button type="button" class="gg-card-toggle" data-gg-open="' + esc(ev.id) + '" aria-expanded="' + open +
      '" aria-controls="' + detailId + '" aria-labelledby="' + titleId + '"></button><div class="gg-clock">';
    if (!deadlineOnly) html += '<time class="gg-time' + (s ? '' : ' is-unknown') + '">' + esc(s ? hm(s) : t('gg.timeTbd', '시간 미정')) + '</time>';
    html += '</div><div class="gg-card-main">';
    // A deadline-only giveaway leads with its sign-up deadline, not an event time.
    if (deadlineOnly) html += '<p class="gg-time is-deadline' + (closed ? ' is-closed' : '') + '">' + esc(signUpByText(s)) + '</p>';
    html += '<p class="gg-card-badges">' + foodBadgeHtml(ev);
    if (gift) html += '<span class="gg-gift-badge">' + GIFT + esc(t('gg.giveaway.label', '경품')) + '</span>';
    if (featured) html += '<span class="gg-featured-label">' + esc(t('gg.next', '다음 꽁밥')) + '</span>';
    if (L && L.phaseOf(ev, now) === 'now') html += '<span class="gg-now-label">' + esc(t('gg.live.now', '진행 중')) + '</span>';
    var changed = savedChanges(ev);
    if (changed.length) html += '<span class="gg-changed-label">' + esc(t('gg.live.changed', '변경됨')) + '</span>';
    html += '</p><p class="gg-sub"><span class="gg-title" id="' + titleId + '" role="heading" aria-level="3">' + esc(ev.title) + '</span>' +
      '<span class="gg-where' + (where ? '' : ' is-unknown') + '"> · ' + esc(where || t('gg.placeTbd', '장소 미정')) + '</span></p></div>';
    // The row's link says when signing up is required ("사전 신청"), so no second badge is needed.
    if (regUrl) html += '<a class="gg-row-reg" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' +
      esc(sign.required === 'true' ? t('gg.registerRequiredShort', '사전 신청') : t('gg.registerShort', '신청')) +
      '<span class="gg-sr"> ' + esc(ev.title) + ' ' + esc(t('gg.newTab', '(새 창)')) + '</span></a>';
    else if (sign.required === 'true') html += '<span class="gg-reg-badge">' + esc(t('gg.regRequired','사전 신청')) + '</span>';
    html += saveButtonHtml(ev);
    html += '</div>';
    html += '<div class="gg-detail" id="' + detailId + '"' + (open ? '' : ' hidden') + '>';
    html += changesHtml(ev, changed);
    var foodText = foodDetailOf(ev);
    if (foodText) html += '<p class="gg-food-line">' + esc(t('gg.foodLine', '음식 · {food}').replace('{food}', foodText)) + '</p>';
    html += '<p class="gg-place' + (place ? '' : ' is-unknown') + '">' + esc(place || t('gg.placeTbd', '장소 미정'));
    if (map) html += ' · <a href="' + esc(map) + '" target="_blank" rel="noopener">' + esc(t('gg.map','지도')) + '</a>';
    html += '</p>';
    if (giftText) html += '<p class="gg-giveaway">' + esc(t('gg.giveaway.label', '경품')) + ' · ' + esc(giftText) + '</p>';
    var who = F.audienceOf(ev, function (name) { return t('gg.audience.estimated', '{who} (추정)').replace('{who}', name); });
    if (who) html += '<p class="gg-eligibility">' + esc(t('gg.eligibility','대상')) + ' · ' + esc(who) + '</p>';
    if (ev.organizer) html += '<p class="gg-organizer">' + esc(t('gg.organizer', '주최')) + ' · ' + esc(ev.organizer) + '</p>';
    if (sign.required === 'false') html += '<p class="gg-reg-note">' + esc(t('gg.regNotNeeded','신청 없이 참여')) + '</p>';
    if (!deadlineOnly) html += deadlineHtml(ev, now);   // a deadline-only giveaway already leads with it
    if (ev.summary) html += '<p class="gg-summary">' + esc(ev.summary) + '</p>';
    var joinUrl = safeHref(sign.join);
    var source = publicSource(ev);
    if (regUrl || joinUrl || source) {
      html += '<div class="gg-actions">';
      if (regUrl) html += '<a class="gg-btn gg-btn--primary" href="' + esc(regUrl) + '" target="_blank" rel="noopener">' + esc(t('gg.register','신청하기')) + '</a>';
      if (joinUrl) html += '<a class="gg-btn' + (regUrl ? '' : ' gg-btn--primary') + '" href="' + esc(joinUrl) + '" target="_blank" rel="noopener">' + esc(t('gg.join','온라인 참여')) + '</a>';
      if (source) html += '<a class="gg-btn" href="' + esc(source.url) + '" target="_blank" rel="noopener">' +
        esc(source.type === 'instagram' ? t('gg.instagramPost', '인스타그램 원문') : t('gg.officialNotice', '공식 공지')) + '</a>';
      html += '</div>';
    }
    var via = sourceLabel(ev);
    if (via) html += '<p class="gg-source">' + esc(via) + '</p>';
    html += toolsHtml(ev, now, n);
    return html + '</div></article>';
  }
  // ---- 꽁밥 LIVE: save, share, calendar (js/ggongbab-live.js) ----
  function savedChanges(ev) {
    return savedStore && savedStore.has(ev.id) ? L.changes(savedStore.get(ev.id), ev) : [];
  }
  function whenText(startAt, endAt) {
    var s = toKst(startAt), e = toKst(endAt);
    if (!s) return t('gg.timeTbd', '시간 미정');
    var text = dayLabel(s) + ' ' + hm(s);
    if (e && e > s) text += '–' + (ymd(e) === ymd(s) ? '' : dayLabel(e) + ' ') + hm(e);
    return text;
  }
  // The row's star: a toggle named by the listing, so a screen reader hears what it saves.
  function saveButtonHtml(ev) {
    if (!savedStore) return '';
    var on = savedStore.has(ev.id);
    return '<button type="button" class="gg-save" data-gg-save="' + esc(ev.id) + '" aria-pressed="' + on + '" aria-label="' +
      esc(t('gg.live.saveAria', '{title} 저장').replace('{title}', ev.title || '')) + '"><span aria-hidden="true">' + (on ? '★' : '☆') + '</span></button>';
  }
  // What changed since the visitor saved it: their own earlier copy against the newest one. Nothing is
  // compared when the feed itself carries no earlier state.
  function changesHtml(ev, changed) {
    if (!changed.length) return '';
    var html = '<div class="gg-changes">';
    changed.forEach(function (c) {
      var before = c.field === 'time' ? whenText(c.before.startAt, c.before.endAt) : c.before;
      var after = c.field === 'time' ? whenText(c.after.startAt, c.after.endAt) : c.after;
      html += '<p class="gg-change">' + esc(t('gg.live.change.' + c.field, c.field === 'time' ? '시간 변경' : '장소 변경')) + ' · ' +
        '<span class="gg-change-before">' + esc(t('gg.live.change.before', '저장할 때 {v}').replace('{v}', before)) + '</span> → ' +
        '<strong>' + esc(t('gg.live.change.after', '지금 {v}').replace('{v}', after)) + '</strong></p>';
    });
    return html + '<button type="button" class="gg-btn gg-ack" data-gg-ack="' + esc(ev.id) + '">' + esc(t('gg.live.ack', '확인했어요')) + '</button></div>';
  }
  function toolsHtml(ev, now, n) {
    if (!L) return '';
    var html = '<div class="gg-tools">';
    if (savedStore) {
      var on = savedStore.has(ev.id);
      html += '<button type="button" class="gg-btn gg-tool" data-gg-save="' + esc(ev.id) + '" aria-pressed="' + on + '">' +
        '<span aria-hidden="true">' + (on ? '★' : '☆') + '</span> ' + esc(on ? t('gg.live.saved', '저장됨') : t('gg.live.save', '저장')) + '</button>';
    }
    html += '<button type="button" class="gg-btn gg-tool" data-gg-share="' + esc(ev.id) + '">' + esc(t('gg.live.share', '공유')) + '</button>';
    var calOk = L.canCalendar(ev, now);
    var calId = 'ggCal' + n;
    if (calOk) html += '<button type="button" class="gg-btn gg-tool" data-gg-cal="' + esc(ev.id) + '" aria-expanded="' + !!state.calOpen[ev.id] +
      '" aria-controls="' + calId + '">' + esc(t('gg.live.calendar', '캘린더에 추가')) + '</button>';
    html += '</div>';
    // Closed, the calendar box holds nothing (no hidden links in the listing's link list).
    if (calOk && !state.calOpen[ev.id]) html += '<div class="gg-cal" id="' + calId + '" hidden></div>';
    else if (calOk) {
      html += '<div class="gg-cal" id="' + calId + '">';
      html += '<a class="gg-btn" href="' + esc(L.googleCalendarUrl(ev, { details: calendarDetails(ev) })) + '" target="_blank" rel="noopener">' +
        esc(t('gg.live.calGoogle', 'Google 캘린더')) + '<span class="gg-sr"> ' + esc(t('gg.newTab', '(새 창)')) + '</span></a>';
      html += '<button type="button" class="gg-btn" data-gg-ics="' + esc(ev.id) + '">' + esc(t('gg.live.calFile', '캘린더 파일 (.ics)')) + '</button>';
      if (L.inTalkApp()) html += talkAppNoteHtml();
      html += '</div>';
    }
    if (state.copy && state.copy.key === ev.id) html += copyBoxHtml();
    return html;
  }
  function talkAppNoteHtml() {
    return '<p class="gg-cal-note">' + esc(t('gg.live.kakaoNote', '카카오톡 안에서는 파일 받기가 안 될 수 있어요')) +
      ' · <a href="' + esc(L.openExternalUrl(location.href)) + '">' + esc(t('gg.live.openBrowser', '기본 브라우저로 열기')) + '</a></p>';
  }
  function copyBoxHtml() {
    return '<label class="gg-copy"><span>' + esc(t('gg.live.copyHint', '길게 눌러 복사하세요')) + '</span>' +
      '<textarea readonly rows="3">' + esc(state.copy.text) + '</textarea></label>';
  }
  function calendarDetails(ev) {
    var lines = [];
    var dish = hasFood(ev) ? F.dishLabel(ev, t) : '';
    if (dish) lines.push(t('gg.live.calFood', '꽁밥 · {food}').replace('{food}', dish));
    lines.push(L.eventLink(ev.id));
    return lines.join('\n');
  }
  // `icon` is decorative markup: the label alone names the chip.
  function chip(group, value, label, pressed, icon) {
    return '<button type="button" class="gg-chip" data-group="' + group + '" data-value="' + value + '" aria-pressed="' + (pressed ? 'true' : 'false') + '">' + (icon || '') + esc(label) + '</button>';
  }
  function filtersHtml() {
    var h = '<div class="gg-filters' + (state.moreFilters ? ' is-expanded' : '') + '" role="group" aria-label="' + esc(t('gg.filtersAria', '음식 종류와 경품 필터')) + '">';
    h += '<div class="gg-filter-row">';
    h += chip('food', 'all', t('gg.filter.all', '전체'), state.food === 'all');
    h += chip('food', 'meal', t('gg.filter.meal', '식사'), state.food === 'meal');
    h += chip('food', 'snack', t('gg.filter.snack', '간식'), state.food === 'snack');
    h += chip('food', 'refreshment', t('gg.filter.refreshment', '다과'), state.food === 'refreshment');
    h += chip('food', 'giveaway', t('gg.filter.giveaway', '경품'), state.food === 'giveaway', GIFT);
    h += '</div>';
    if (L) h += moreFiltersHtml();
    h += '</div>';
    return h;
  }
  // Date, who and where: behind one button, so the phone's first screen keeps the list.
  function moreFiltersHtml() {
    var n = moreCount();
    var h = '<button type="button" class="gg-more" data-gg-more aria-expanded="' + state.moreFilters + '" aria-controls="ggMoreFilters">' +
      esc(t('gg.live.more', '날짜·대상·위치')) + (n ? ' <span class="gg-more-count">' + n + '</span>' : '') +
      '<span aria-hidden="true" class="gg-more-caret">' + (state.moreFilters ? '▴' : '▾') + '</span></button>';
    h += '<div class="gg-more-panel" id="ggMoreFilters"' + (state.moreFilters ? '' : ' hidden') + '>';
    // Closed, the panel holds nothing: no hidden chips for a tab order or a tap-size audit to meet.
    if (!state.moreFilters) return h + '</div>';
    var days = DAY_FILTERS.slice();
    if (/^w:/.test(state.day)) days.push(state.day);
    h += filterGroup('day', t('gg.live.f.day', '날짜'), days.map(function (v) {
      return [v, /^w:/.test(v) ? weekLabel(v.slice(2)) : t('gg.live.day.' + v, v)];
    }));
    h += filterGroup('who', t('gg.live.f.who', '대상'), WHO_FILTERS.map(function (v) { return [v, t('gg.live.who.' + v, v)]; }));
    h += filterGroup('area', t('gg.live.f.area', '위치'), AREA_FILTERS.map(function (v) { return [v, t('gg.live.area.' + v, v)]; }));
    if (filtersActive()) h += '<button type="button" class="gg-btn gg-reset" data-gg-reset>' + esc(t('gg.live.reset', '필터 초기화')) + '</button>';
    return h + '</div>';
  }
  function filterGroup(group, label, values) {
    var h = '<div class="gg-filter-row gg-filter-more" role="group" aria-label="' + esc(label) + '"><span class="gg-filter-label" aria-hidden="true">' + esc(label) + '</span>';
    values.forEach(function (pair) { h += chip(group, pair[0], pair[1], state[group] === pair[0]); });
    return h + '</div>';
  }
  function shortDate(key) {
    var d = toKst(key + 'T12:00:00+09:00');
    return d ? dayLabel(d).replace(/\s*\(.*\)$/, '') : key;
  }
  function weekLabel(monday) { return t('gg.live.weekOf', '{date} 주').replace('{date}', shortDate(monday)); }
  function radarCopy(count) {
    if (count <= 0) return t('gg.radar.zero', '🌵 오늘은 꽁밥 가뭄');
    if (count <= 2) return t('gg.radar.some', '🍙 한 끼는 건질 수 있어요');
    return t('gg.radar.many', '🔥 오늘 꽁밥 풍년');
  }
  // The radar (2026-11-05): one slim line, the day's mood and count, and the next free meal as a
  // button to its row. It was a 258 px box that repeated the hero's count and the first card.
  function radarHtml(now) {
    var today = todayUpcoming(now);
    var next = earliestToday(now);
    // Without a next meal there is no button under the line: the box keeps its own bottom padding
    // (2026-11-05: "오늘은 꽁밥 가뭄" sat on the box's bottom edge and looked cut off).
    var html = '<section class="gg-radar' + (next ? '' : ' is-quiet') + '" aria-label="' + esc(t('gg.radar.label', '오늘의 꽁밥 레이더')) + '">';
    html += '<p class="gg-radar-line"><span class="gg-radar-title">' + esc(radarCopy(today.length)) + '</span>' +
      '<span class="gg-radar-count">' + esc(t('gg.radar.count', '오늘 {n}개').replace('{n}', String(today.length))) + '</span></p>';
    if (next) {
      var s = toKst(next.startAt);
      var place = (next.location || {}).building || shortPlace(next);
      html += '<button type="button" class="gg-radar-cta" data-gg-scroll="' + esc(next.id) + '">' +
        '<span class="gg-radar-next">' + esc(t('gg.radar.next', '다음 꽁밥')) + '</span> ' +
        esc((s ? hm(s) : t('gg.timeTbd', '시간 미정')) + ' ' + F.dishLabel(next, t) + (place ? ' · ' + place : '')) +
        ' <span aria-hidden="true">→</span></button>';
    }
    return html + '</section>';
  }
  function metricHtml(now, menuSnap) {
    var freeN = todayUpcoming(now).length;
    menuSnap = menuSnap || (menuCtl && menuCtl.snapshot ? menuCtl.snapshot() : { status: state.menu.status, stale: true, restaurantCount: 0 });
    var menuPart;
    if (menuSnap.status === 'loading' || state.menu.status === 'loading') menuPart = t('gg.metric.menuLoading', '학식 확인 중');
    else if (menuSnap.status === 'error' || state.menu.status === 'error') menuPart = t('gg.metric.menuError', '학식 불러오기 실패');
    else if (menuSnap.stale) menuPart = menuSnap.weekend ? t('gg.metric.menuWeekend', '주말 학식 없음') : t('gg.metric.menuStale', '학식 업데이트 중');
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
    html += '<button type="button" class="food-hub-tab" role="tab" id="foodHubTabFree" data-hub-tab="free" aria-controls="foodHubFree" aria-selected="' + free + '" tabindex="' + (free ? 0 : -1) + '">🍱 ' + esc(t('gg.tab.free', '꽁밥')) + '  ' + todayN + '</button>';
    html += '<button type="button" class="food-hub-tab" role="tab" id="foodHubTabMenu" data-hub-tab="menu" aria-controls="foodHubMenu" aria-selected="' + !free + '" tabindex="' + (free ? -1 : 0) + '">🍚 ' + esc(t('gg.tab.menu', '학식')) + '</button>';
    return html + '</div>';
  }
  function emptyFreeHtml(now) {
    var menuSnap = menuCtl && menuCtl.snapshot ? menuCtl.snapshot() : { restaurantCount: 0, stale: true };
    var menuN = menuSnap.stale ? 0 : (menuSnap.restaurantCount || 0);
    var html = '<div class="gg-state">';
    html += '<strong>' + esc(t('gg.emptyTodayTitle', '🌵 오늘은 꽁밥 가뭄이에요')) + '</strong>';
    html += esc(t('gg.emptyTodayBody', '오늘 학식 {n}곳').replace('{n}', String(menuN)));
    html += '<br><button type="button" class="km-cta" data-hub-tab="menu">' + esc(t('gg.toMenu', '오늘 학식 보러가기 →')) + '</button></div>';
    if (!futurePublic(now).length) {
      html += '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '맞는 꽁밥이 없어요')) + '</strong>' + '</div>';
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
    return '<div class="gg-state"><strong>' + esc(t('gg.emptyTitle', '맞는 꽁밥이 없어요')) + '</strong>' + '</div>';
  }
  // What this list is (the public current and upcoming rows only; ended rows
  // leave it) and when the snapshot was published. It makes no freshness claim
  // beyond that time.
  function feedNoteHtml(now) {
    var g = state.free.data && toKst(state.free.data.generatedAt);
    if (!g) return '';
    var week = L && weekRows(now).length ? '<button type="button" class="gg-week-share" data-gg-share-week>' +
      esc(/^w:/.test(state.day) ? t('gg.live.shareThisWeek', '이 주 일정 공유') : t('gg.live.shareWeek', '이번 주 꽁밥 공유')) + '</button>' : '';
    var box = state.copy && state.copy.key === 'week' ? copyBoxHtml() : '';
    return '<div class="gg-feed-note"><p class="gg-updated">' + esc(t('gg.updated', '마지막 변경')) + ' ' + esc(dayLabel(g) + ' ' + hm(g)) + ' KST</p>' + week + box + '</div>';
  }
  // ---- 꽁밥 LIVE: the week to share, saved listings, the shared-link entry, the new-feature note ----
  function byStartAt(a, b) { return String(a.startAt || '').localeCompare(String(b.startAt || '')); }
  // The week a share covers: the week a shared link opened, else from today to Sunday.
  function shareRange(now) {
    return /^w:/.test(state.day) ? L.dayRange(state.day, now) : L.dayRange('week', now);
  }
  function weekRows(now) {
    if (!L || state.free.status !== 'ready') return [];
    var range = shareRange(now);
    return publicList().filter(function (ev) {
      var s = toKst(ev.startAt);
      return s && isUpcoming(ev, now) && ymd(s) >= range[0] && ymd(s) <= range[1];
    }).sort(byStartAt);
  }
  function rowWhat(ev) {
    return hasFood(ev) ? F.dishLabel(ev, t) : '🎁 ' + t('gg.giveaway.label', '경품');
  }
  function weekShare(now) {
    var rows = weekRows(now), range = shareRange(now);
    var lines = rows.slice(0, 12).map(function (ev) {
      var s = toKst(ev.startAt);
      return dayLabel(s) + ' ' + (isDeadlineOnly(ev) ? signUpByText(s) : hm(s)) + ' ' + rowWhat(ev) + ' · ' + ev.title;
    });
    if (rows.length > 12) lines.push(t('gg.live.more12', '외 {n}개').replace('{n}', String(rows.length - 12)));
    var title = t('gg.live.weekTitle', '밥도둑 꽁밥 · {date} 주').replace('{date}', shortDate(L.mondayOf(range[0])));
    return { title: title, text: title + '\n' + lines.join('\n'), url: L.weekLink(L.mondayOf(range[0])) };
  }
  function eventShare(ev) {
    var where = shortPlace(ev);
    var text = rowWhat(ev) + ' · ' + ev.title + '\n' + (isDeadlineOnly(ev) ? signUpByText(toKst(ev.startAt)) : whenText(ev.startAt, ev.endAt)) + (where ? ' · ' + where : '');
    return { title: ev.title, text: text, url: L.eventLink(ev.id) };
  }
  function rowById(id) {
    var list = (state.free.data && state.free.data.events) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id && isPublic(list[i])) return list[i];
    return null;
  }
  function archivedById(id) {
    var list = (state.archive.data && state.archive.data.events) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id && isPublic(list[i])) return list[i];
    return null;
  }
  // Each saved listing against the newest data: upcoming (with changes), ended (from the feed, the
  // archive, or, once both have loaded, the visitor's own copy), missing (no longer published and not
  // over: never called cancelled, the feed does not say so), or still being checked.
  function savedGroups(now) {
    var out = { upcoming: [], ended: [], missing: [], checking: [], gone: [] };
    savedStore.list().forEach(function (item) {
      var live = state.free.status === 'ready' ? rowById(item.id) : null;
      if (live && isUpcoming(live, now)) { out.upcoming.push({ item: item, ev: live, changes: L.changes(item, live) }); return; }
      var past = live || archivedById(item.id);
      if (past && L.dayPassed(past, F.nowKst())) { out.gone.push(item); return; }
      if (past) { out.ended.push({ item: item, ev: past }); return; }
      if (state.free.status === 'loading' || state.archive.status === 'loading') { out.checking.push({ item: item }); return; }
      var mine = { id: item.id, title: item.seen.title, startAt: item.seen.startAt, endAt: item.seen.endAt || null };
      var end = F.eventEnd(mine);
      if (L.dayPassed(mine, F.nowKst())) out.gone.push(item);
      else if (end && end < now) out.ended.push({ item: item, ev: mine, own: true });
      else out.missing.push({ item: item, ev: mine });
    });
    out.upcoming.sort(function (a, b) { return byStartAt(a.ev, b.ev); });
    out.ended.sort(function (a, b) { return byStartAt(b.ev, a.ev); });
    return out;
  }
  function savedRowHtml(row, kind, now) {
    var ev = row.ev || { title: row.item.seen.title, startAt: row.item.seen.startAt, endAt: row.item.seen.endAt };
    var title = ev.title || row.item.seen.title || '';
    var when = esc(whenText(ev.startAt, ev.endAt));
    var html = '<li class="gg-saved-row is-' + kind + '" data-saved-id="' + esc(row.item.id) + '">';
    if (kind === 'upcoming') {
      html += '<button type="button" class="gg-saved-open" data-gg-goto="' + esc(row.item.id) + '"><span class="gg-saved-when">' + when +
        '</span><span class="gg-saved-title">' + esc(title) + '</span></button>';
    } else {
      html += '<p class="gg-saved-open is-static"><span class="gg-saved-when">' + when + '</span><span class="gg-saved-title">' + esc(title) + '</span></p>';
    }
    var tags = [];
    if (kind === 'upcoming' && L.phaseOf(row.ev, now) === 'now') tags.push(['now', t('gg.live.now', '진행 중')]);
    if (kind === 'upcoming' && row.changes.length) tags.push(['changed', t('gg.live.changed', '변경됨')]);
    if (kind === 'ended') tags.push(['ended', t('gg.archive.ended', '종료')]);
    if (kind === 'missing') tags.push(['missing', t('gg.live.missing', '목록에서 빠짐')]);
    if (kind === 'checking') tags.push(['checking', t('gg.live.checking', '확인 중')]);
    html += '<span class="gg-saved-tags">' + tags.map(function (tag) {
      return '<span class="gg-saved-tag is-' + tag[0] + '">' + esc(tag[1]) + '</span>';
    }).join('') + '</span>';
    html += '<button type="button" class="gg-unsave" data-gg-unsave="' + esc(row.item.id) + '" aria-label="' +
      esc(t('gg.live.unsaveAria', '{title} 저장 지우기').replace('{title}', title)) + '"><span aria-hidden="true">×</span></button>';
    if (kind === 'missing') html += '<p class="gg-saved-note">' + esc(t('gg.live.missingNote', '취소됐을 수 있어요. 공지를 확인하세요.')) + '</p>';
    return html + '</li>';
  }
  function savedHtml(now) {
    if (!savedStore) return '';
    var g = savedGroups(now);
    // A listing whose day is over is not shown or counted (L.dayPassed); its saved row stays for the calendar.
    var all = savedStore.list().filter(function (item) { return g.gone.indexOf(item) < 0; });
    var recovered = savedStore.recovered();
    if (!all.length && !recovered) return '';
    var changedN = g.upcoming.filter(function (row) { return row.changes.length; }).length;
    var open = state.savedOpen;
    var html = '<section class="gg-saved" id="ggSaved" aria-labelledby="ggSavedTitle">';
    html += '<h2 class="gg-saved-head"><button type="button" class="gg-saved-toggle" id="ggSavedTitle" data-gg-saved aria-expanded="' + open + '" aria-controls="ggSavedBody">' +
      '<span aria-hidden="true">★</span> ' + esc(t('gg.live.savedTitle', '저장한 꽁밥')) + ' <span class="gg-saved-n">' + all.length + '</span>' +
      (changedN ? ' <span class="gg-changed-label">' + esc(t('gg.live.changedN', '변경 {n}').replace('{n}', String(changedN))) + '</span>' : '') +
      '<span aria-hidden="true" class="gg-more-caret">' + (open ? '▴' : '▾') + '</span></button></h2>';
    html += '<div class="gg-saved-body" id="ggSavedBody"' + (open ? '' : ' hidden') + '>';
    if (recovered) html += '<p class="gg-saved-note">' + esc(t('gg.live.recovered', '저장 기록을 읽을 수 없어 새로 시작했어요.')) + '</p>';
    var active = g.upcoming.map(function (r) { return savedRowHtml(r, 'upcoming', now); })
      .concat(g.checking.map(function (r) { return savedRowHtml(r, 'checking', now); }))
      .concat(g.missing.map(function (r) { return savedRowHtml(r, 'missing', now); }));
    if (active.length) html += '<ol class="gg-saved-list">' + active.join('') + '</ol>';
    else if (all.length) html += '<p class="gg-saved-note">' + esc(t('gg.live.noUpcoming', '다가오는 저장 꽁밥 없음')) + '</p>';
    if (g.ended.length) {
      html += '<h3 class="gg-saved-sub">' + esc(t('gg.live.pastTitle', '지난 꽁밥')) + '</h3>';
      html += '<ol class="gg-saved-list is-past">' + g.ended.map(function (r) { return savedRowHtml(r, 'ended', now); }).join('') + '</ol>';
    }
    // Signed in, the calendar is the subscription on 마이 밥도둑, offered on iPhone and iPad only.
    var ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
    html += pushToggleHtml() + (accountMode !== 'account' ? starCalendarToggleHtml() : ios ?
      '<p class="gg-saved-note">' + esc(t('gg.live.calOnMy', '마이 밥도둑에서 캘린더를 연결해 보세요')) + '</p>' : '');
    if (accountMode === 'account') {
      html += '<p class="gg-saved-foot"><a href="my.html">' + esc(t('gg.live.myLink', '마이 밥도둑')) + '</a></p>';
    } else if (accountMode === 'failed') {
      html += '<p class="gg-saved-note">' + esc(t('gg.live.accountFail', '계정 목록을 불러오지 못했어요')) + '</p>';
    }
    return html + '</div></section>';
  }
  // A shared link (?e=<id>, ?week=<Monday>) resolves once the data it needs has loaded.
  function processEntry(now) {
    var en = state.entry;
    if (en.done || !L) return;
    if (en.week) {
      state.day = 'w:' + en.week;
      en.notice = { kind: 'week', monday: en.week };
      en.week = '';
    }
    if (!en.id) { en.done = true; return; }
    if (state.free.status !== 'ready') { if (state.free.status === 'error') en.done = true; return; }
    var matches = function (ev) { return ev.id === en.id || ev.id.indexOf(en.id + '#') === 0; };
    var rows = ((state.free.data && state.free.data.events) || []).filter(isPublic).filter(matches).sort(byStartAt);
    var live = rows.filter(function (ev) { return isUpcoming(ev, now); })[0];
    if (live) {
      state.food = 'all'; state.day = 'all'; state.who = 'all'; state.area = 'all';   // shown, not saved
      state.activeSection = 'free';
      state.open[live.id] = true;
      en.focus = live.id;
      en.done = true;
      return;
    }
    if (state.archive.status === 'loading') return;
    var past = rows[0] || ((state.archive.data && state.archive.data.events) || []).filter(function (ev) { return isPublic(ev) && matches(ev); })[0];
    en.notice = past ? { kind: 'ended', ev: past } : { kind: 'missing' };
    state.activeSection = 'free';
    en.done = true;
  }
  function entryNoticeHtml() {
    var n = state.entry.notice;
    if (!n) return '';
    var text = n.kind === 'week' ? t('gg.live.entryWeek', '공유받은 {week} 꽁밥 일정').replace('{week}', weekLabel(n.monday))
      : n.kind === 'ended' ? t('gg.live.entryEnded', '공유받은 꽁밥은 끝났어요 · {when} {title}')
        .replace('{when}', whenText(n.ev.startAt, n.ev.endAt)).replace('{title}', n.ev.title || '')
      : t('gg.live.entryMissing', '공유받은 꽁밥을 찾지 못했어요');
    var html = '<div class="gg-entry" role="status"><p>' + esc(text) + '</p>';
    if (n.kind === 'week') html += '<button type="button" class="gg-btn" data-gg-reset>' + esc(t('gg.live.showAll', '전체 일정 보기')) + '</button>';
    return html + '<button type="button" class="gg-entry-close" data-gg-entry-close aria-label="' + esc(t('gg.live.close', '닫기')) + '"><span aria-hidden="true">×</span></button></div>';
  }
  function noticeDismissed() {
    try { return localStorage.getItem(NOTICE_KEY) === '1'; } catch (err) { return true; }
  }
  // One line, under the page title, closed for good with ×; it never covers the list.
  function newNoticeHtml() {
    if (!L || noticeDismissed()) return '';
    return '<div class="gg-new" role="note"><span class="gg-new-tag">NEW</span><p>' +
      esc(t('gg.live.newNote', '☆ 저장·공유·캘린더 추가가 생겼어요')) + '</p>' +
      '<button type="button" class="gg-new-close" data-gg-new-close aria-label="' + esc(t('gg.live.newClose', '새 기능 안내 닫기')) + '"><span aria-hidden="true">×</span></button></div>';
  }
  function filteredEmptyHtml() {
    var parts = [];
    if (state.food !== 'all') parts.push(t('gg.filter.' + state.food, state.food));
    if (state.day !== 'all') parts.push(/^w:/.test(state.day) ? weekLabel(state.day.slice(2)) : t('gg.live.day.' + state.day, state.day));
    if (state.who !== 'all') parts.push(t('gg.live.who.' + state.who, state.who));
    if (state.area !== 'all') parts.push(t('gg.live.area.' + state.area, state.area));
    return '<div class="gg-state" data-gg-empty="filtered"><strong>' + esc(t('gg.live.emptyFiltered', '고른 조건에 맞는 꽁밥이 없어요')) + '</strong>' +
      esc(t('gg.live.emptyWhy', '조건 · {list}').replace('{list}', parts.join(' · '))) +
      '<br><button type="button" class="gg-btn gg-reset" data-gg-reset>' + esc(t('gg.live.reset', '필터 초기화')) + '</button></div>';
  }
  // Past listings: public rows that have ended, from the archive file plus any live-feed row
  // whose end has already passed (it leaves the live list at once; the next export archives it).
  // The same client rules decide both lists, so a row is shown live or past, never both.
  function pastListings(now) {
    var cutoff = now.getTime() - ARCHIVE_WINDOW_DAYS * 86400000;
    var seen = {};
    var list = [];
    function add(ev) {
      if (!ev || typeof ev.id !== 'string' || seen[ev.id] || !isPublic(ev) || isUpcoming(ev, now)) return;
      var last = F.eventEnd(ev);
      if (!last || last.getTime() < cutoff) return;
      seen[ev.id] = true;
      list.push(ev);
    }
    ((state.archive.data && state.archive.data.events) || []).forEach(add);
    ((state.free.status === 'ready' && state.free.data && state.free.data.events) || []).forEach(add);
    return list.sort(function (a, b) {
      return String(b.endAt || b.startAt || '').localeCompare(String(a.endAt || a.startAt || '')) ||
        String(a.id).localeCompare(String(b.id));
    });
  }
  // A record, not an invitation: no registration, deadline or primary button, whatever the data holds.
  function pastHtml(ev) {
    var s = toKst(ev.startAt);
    var gift = hasGiveaway(ev);
    var meta = [placeLabel(ev), foodLabelOf(ev), giveawayText(ev)].filter(Boolean).join(' · ');
    var via = sourceLabel(ev);
    var source = publicSource(ev);
    var record = hasFood(ev) ? t('gg.archive.record', '지난 꽁밥 안내') : t('gg.archive.recordGiveaway', '지난 경품 안내');
    var html = '<li class="gg-past" data-past-id="' + esc(ev.id) + '">';
    html += '<p class="gg-past-top"><span class="gg-past-badge">' + esc(t('gg.archive.ended', '종료')) + '</span>' +
      (gift ? '<span class="gg-past-gift">' + GIFT + esc(t('gg.giveaway.label', '경품')) + '</span>' : '') +
      '<span class="gg-past-when">' + esc(s ? dayLabel(s) + ' ' + hm(s) : t('gg.timeTbd', '시간 미정')) + '</span></p>';
    html += '<h3 class="gg-past-title">' + esc(ev.title) + '</h3>';
    if (meta) html += '<p class="gg-past-meta">' + esc(meta) + '</p>';
    html += '<p class="gg-past-note">' + esc(record + (via ? ' · ' + via : '')) + '</p>';
    if (source) {
      html += '<a class="gg-past-link" href="' + esc(source.url) + '" target="_blank" rel="noopener">' +
        esc(source.type === 'instagram' ? t('gg.archive.sourceInstagram', '인스타그램 보기') : t('gg.archive.source', '공지 보기')) +
        ' <span aria-hidden="true">↗</span>' +
        '<span class="gg-sr">' + esc(t('gg.newTab', '(새 창)')) + '</span></a>';
    }
    return html + '</li>';
  }
  function archiveHtml(now) {
    var status = state.archive.status;
    if (status === 'off') return '';
    var html = '<section class="gg-archive" aria-labelledby="ggArchiveTitle">';
    html += '<h2 class="gg-archive-title" id="ggArchiveTitle">' + esc(t('gg.archive.title', '지난 꽁밥 기록')) + '</h2>';
    html += '<p class="gg-archive-lead">' + esc(t('gg.archive.lead', '최근 30일')) + '</p>';
    var list = status === 'loading' ? [] : pastListings(now);
    if (status === 'loading') html += '<p class="gg-archive-state">' + esc(t('gg.archive.loading', '불러오는 중')) + '</p>';
    else if (status === 'error') html += '<p class="gg-archive-state" data-archive-state="error">' + esc(t('gg.archive.error', '지난 기록을 불러오지 못했어요.')) + '</p>';
    else if (!list.length) html += '<p class="gg-archive-state" data-archive-state="empty">' + esc(t('gg.archive.empty', '최근 30일 기록 없음')) + '</p>';
    // Closed until asked for (2026-11-05): one button, then the whole list.
    if (list.length) {
      var expanded = state.archive.expanded;
      html += '<button type="button" class="gg-archive-more" data-gg-archive-more aria-controls="ggPastList" aria-expanded="' + expanded + '">' +
        esc(expanded ? t('gg.archive.less', '지난 기록 접기') : t('gg.archive.more', '지난 꽁밥 기록 {n}개 보기').replace('{n}', String(list.length))) + '</button>';
      html += '<ol class="gg-past-list" id="ggPastList"' + (expanded ? '' : ' hidden') + '>';
      if (expanded) list.forEach(function (ev) { html += pastHtml(ev); });
      html += '</ol>';
    }
    return html + '</section>';
  }
  function freePaneHtml(now) {
    var html = entryNoticeHtml() + savedHtml(now);
    if (state.free.status === 'ready') html += radarHtml(now);
    // The radar's own height, so it does not push the list when it lands.
    else if (state.free.status === 'loading') html += '<div class="gg-skeleton gg-radar-skeleton"></div>';
    // The live list and its sticky filters share one box, so the filters stop at the archive.
    html += '<div class="gg-live">';
    html += filtersHtml();
    html += '<div class="gg-feed">';
    if (state.free.status === 'loading') html += stateHtml('loading');
    else if (state.free.status === 'error' || state.free.status === 'blocked') html += stateHtml(state.free.status);
    else {
      html += feedNoteHtml(now);
      var events = visibleEvents(now);
      // The featured "다음 꽁밥" is the radar's next free meal: always a food row (one that also has a
      // giveaway may be it), never a giveaway-only row, which the radar does not count.
      var featuredId = (earliestToday(now) || {}).id;
      if (!events.length) {
        if (L && filtersActive()) html += filteredEmptyHtml();
        else if (!todayUpcoming(now).length) html += emptyFreeHtml(now);
        else html += stateHtml('empty');
      } else {
        var lastDay = '';
        events.forEach(function (ev) {
          var s = toKst(ev.startAt);
          var key = ymd(s);
          if (key !== lastDay) {
            if (lastDay) html += '</div>';
            lastDay = key;
            var rel = relDay(key, now);
            html += '<h2 class="gg-day">' + (rel ? '<span class="gg-day-rel' + (rel === t('gg.today', '오늘') ? ' is-today' : '') + '">' + esc(rel) + '</span>' : '') + '<span class="gg-day-date">' + esc(dayLabel(s)) + '</span></h2>';
            html += '<div class="gg-day-list">';
          }
          html += cardHtml(ev, now, ev.id === featuredId);
        });
        if (lastDay) html += '</div>';
      }
    }
    return html + '</div></div>' + newsHtml() + archiveHtml(now);
  }
  function newsHtml() {
    if (state.news.status === 'off') return '';
    var html = '<section class="gg-news" aria-labelledby="ggNewsTitle"><h2 id="ggNewsTitle">' +
      esc(t('gg.news.title', '먹거리 소식')) + '</h2>';
    // Nothing while loading or when there is no news (2026-11-05: an empty section is not news).
    if (state.news.status === 'loading' || (state.news.status === 'ready' && !state.news.items.length)) return '';
    if (state.news.status === 'error') return html + '<p class="gg-news-state">' + esc(t('gg.news.error', '소식을 불러오지 못했어요.')) + '</p></section>';
    html += '<ul class="gg-news-list">';
    state.news.items.forEach(function (item) {
      var day = toKst(item.noticeDate + 'T12:00:00+09:00');
      html += '<li class="gg-news-row" data-news-id="' + esc(item.id) + '"><time datetime="' + esc(item.noticeDate) + '">' +
        esc(dayLabel(day)) + '</time><div class="gg-news-facts"><h3>' + esc(item.title) + '</h3>';
      if (item.location) html += '<p class="gg-news-place">' + esc(item.location) + '</p>';
      if (item.summary) html += '<p>' + esc(item.summary) + '</p>';
      html += '<span class="gg-news-source">' + esc(sourceLabel(item)) + '</span></div></li>';
    });
    return html + '</ul></section>';
  }
  function acceptNews(data) {
    if (!data || !Array.isArray(data.items)) throw new Error('bad news');
    var seen = {};
    state.news.items = data.items.filter(function (item) {
      if (!item || item.contentType !== 'campus_food_news' || !/^news-[a-f0-9]{32}$/.test(item.id || '') ||
          !/^\d{4}-\d{2}-\d{2}$/.test(item.noticeDate || '') || typeof item.title !== 'string' || !item.title || seen[item.id]) return false;
      // Defense in depth: private source URLs/IDs are never rendered, including
      // malformed static payloads. The exporter is the authoritative validator.
      var text = [item.title, item.summary || '', item.location || ''].join(' ');
      if (/portal\.kaist\.ac\.kr|sso\.kaist\.ac\.kr|\/wz\/|pstNo|boardNo|external[_ ]?id|https?:\/\//i.test(text) ||
          /\b[a-z_][\w-]*\s*=\s*\S+/i.test(text)) return false;
      var date = toKst(item.noticeDate + 'T12:00:00+09:00');
      if (!date || ymd(date) !== item.noticeDate) return false;
      var today = nowKst();
      if (item.noticeDate > ymd(today) || item.noticeDate < ymd(addDays(today, -30))) return false;
      seen[item.id] = true;
      return true;
    });
    state.news.status = 'ready';
    render();
  }
  function loadNews() {
    if (mode === 'preview' || mode === 'blocked') { state.news.status = 'off'; return; }
    if (mode === 'fixture') { acceptNews(labFixtures().news(nowKst())); return; }
    fetch('data/ggongbab/news.json', { cache: 'no-store' }).then(function (res) {
      if (res.status === 404) return { items: [] };
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    }).then(acceptNews).catch(function () { state.news.status = 'error'; render(); });
  }
  function render() {
    var now = nowKst();
    cardSeq = 0;
    processEntry(now);
    var focus = focusSelector();
    var html = '<header class="gg-hero"><h1>' + esc(t('ggongbab.title', '오늘의 꽁밥')) + '</h1>';
    html += metricHtml(now);
    html += newNoticeHtml();
    html += '</header>';
    html += tabsHtml();
    html += '<div id="foodHubFree" class="food-hub-free" role="tabpanel" aria-labelledby="foodHubTabFree"' + (state.activeSection === 'free' ? '' : ' hidden') + '>';
    html += freePaneHtml(now);
    html += '</div>';
    html += '<div id="foodHubMenu" class="food-hub-menu" role="tabpanel" aria-labelledby="foodHubTabMenu"' + (state.activeSection === 'menu' ? '' : ' hidden') + '></div>';
    html += '<aside class="gg-choose" aria-labelledby="ggChooseTitle"><p class="gg-choose-title" id="ggChooseTitle">' + esc(t('gg.choose.title', '뭘 먹을지 아직 못 정했다면')) + '</p>';
    html += '<a class="gg-choose-link" href="choose.html">' + esc(t('gg.choose.cta', '메뉴 고르기 →')) + '</a></aside>';
    root.innerHTML = html;
    if (focus) {
      var again = root.querySelector(focus);
      if (again) again.focus({ preventScroll: true });
    }
    bindMenu(now);
    if (state.entry.focus) {
      var target = state.entry.focus;
      state.entry.focus = '';
      requestAnimationFrame(function () { focusCard(target); });
    }
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
        var metric = document.querySelector('.gg-counts');
        if (metric) metric.outerHTML = metricHtml(nowKst(), snap);
      },
      freeCountText: freeText
    };
    if (mode === 'fixture') {
      opts.getData = function () { return labFixtures().menu(staleMenuFixture, nowKst()); };
      opts.getDay = function (date) { return labFixtures().menuDay(date); };
    }
    menuCtl = window.BabdodukKaistMenu.attach(host, opts);
  }
  // Fixture mode's synthetic data: tests/fixtures/ggongbab-lab.js, loaded at the end of this file.
  function labFixtures() {
    if (!window.BabdodukLabFixtures) throw new Error('fixtures unavailable');
    return window.BabdodukLabFixtures;
  }
  function acceptFree(data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad payload');
    data = Object.assign({}, data, { events: F.occurrences(data.events) });   // one row per session day
    state.free.data = data;
    state.free.status = 'ready';
    render();
  }
  function loadFree() {
    if (mode === 'blocked') { state.free.status = 'blocked'; render(); return; }
    state.free.status = 'loading';
    render();
    if (mode === 'fixture') {
      try { acceptFree(labFixtures().freeFeed(nowKst())); } catch (err) { state.free.status = 'error'; render(); }
      return;
    }
    if (allowLiveFeed && window.BabdodukPublicFeed) {
      if (!feedCtl) feedCtl = window.BabdodukPublicFeed.create({
        config: window.BABDODUK_PUBLIC_FEED_CONFIG,
        loadSnapshot: function (signal) {
          return fetch(DATA_URL, { cache: 'no-store', signal: signal }).then(function (res) {
            if (!res.ok) throw new Error('unavailable'); return res.json();
          });
        },
        onData: acceptFree,
        onError: function () { state.free.status = 'error'; render(); }
      });
      feedCtl.retry();
      return;
    }
    fetch(DATA_URL, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('unavailable'); return res.json();
    }).then(acceptFree).catch(function () { state.free.status = 'error'; render(); });
  }
  function acceptArchive(data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad archive');
    data = Object.assign({}, data, { events: F.occurrences(data.events) });
    state.archive.data = data;
    state.archive.status = 'ready';
    render();
  }
  function loadArchive() {
    if (mode === 'preview' || mode === 'blocked') { state.archive.status = 'off'; return; }
    if (mode === 'fixture') { acceptArchive(labFixtures().archive(nowKst(), ARCHIVE_WINDOW_DAYS)); return; }
    fetch(ARCHIVE_URL, { cache: 'no-store' }).then(function (res) {
      if (res.status === 404) return { events: [] }; // not generated yet: nothing has been archived
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    }).then(acceptArchive).catch(function () {
      // Non-fatal: the live feed above keeps its own state.
      state.archive.status = 'error';
      render();
    });
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

  function focusCard(id) {
    var target = root.querySelector('.gg-card[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
    if (!target) return;
    var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' });
    target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }
  // One polite status line for save, copy and share results (outside the re-rendered feed).
  var toast = null, toastTimer = null;
  function announce(message) {
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'gg-toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove('is-on'); }, 2600);
  }
  function shareOut(key, payload) {
    state.copy = null;
    L.share(payload).then(function (result) {
      if (result === 'copied') announce(t('gg.live.copied', '링크를 복사했어요'));
      else if (result === 'manual') { state.copy = { key: key, text: payload.text + '\n' + payload.url }; render(); }
    });
  }
  function downloadIcs(ev) {
    if (L.downloadIcs(ev, { details: calendarDetails(ev), url: L.eventLink(ev.id) })) announce(t('gg.live.icsDone', '캘린더 파일을 받았어요'));
    else announce(t('gg.live.icsFail', '이 브라우저에서는 파일을 받을 수 없어요'));
  }
  // The star also opens the calendar's add screen (owner 2026-11-11), for visitors who said yes once.
  function starCalendarText() {
    return {
      title: t('starcal.ask.title', '별 누를 때 내 캘린더에도 넣을까요?'),
      body: t('starcal.ask.body', '넣으면 시작 30분 전에 알림이 와요.'),
      yes: t('starcal.ask.yes', '넣을게요'),
      no: t('starcal.ask.no', '괜찮아요')
    };
  }
  function starCalendarMessage(result) {
    if (result === 'ics') return t('starcal.done.ics', '추가를 눌러 주세요');
    if (result === 'google') return t('starcal.done.google', '새 창에서 저장을 눌러 주세요');
    if (result === 'manual') return t('starcal.done.manual', '카카오톡에선 바로 안 돼요 · 펼쳐서 캘린더에 추가를 눌러 주세요');
    return t('starcal.done.blocked', '캘린더를 열지 못했어요 · 펼쳐서 다시 눌러 주세요');
  }
  function refocusStar(id) {
    var esc2 = window.CSS && CSS.escape ? CSS.escape(id) : id;
    var star = root.querySelector('.gg-save[data-gg-save="' + esc2 + '"]') || root.querySelector('[data-gg-save="' + esc2 + '"]');
    if (star) star.focus({ preventScroll: true });
  }
  function pushAskText() {
    return {
      title: t('push.ask.title', '별 누른 꽁밥, 30분 전에 알려 드릴까요?'),
      body: t('push.ask.body', '다음 창에서 "허용"을 눌러 주세요.'),
      yes: t('push.ask.yes', '알림 받을게요'),
      no: t('push.ask.no', '괜찮아요')
    };
  }
  function pushDone(result) {
    if (result === 'on') { pushState = 'on'; announce(t('push.nowOn', '30분 전 알림을 켰어요')); }
    else if (result === 'denied') { pushState = 'denied'; announce(t('push.blocked', '알림이 막혀 있어요. 휴대폰 설정에서 허용해 주세요.')); }
    else announce(t('push.fail', '알림을 켜지 못했어요. 다시 시도해 주세요.'));
    render();
  }
  function afterStar(ev, savedMessage) {
    pushChanged();
    if (!L.canCalendar(ev, nowKst())) return announce(savedMessage);
    // In the site opened from the home screen, the first star offers the phone's own alert instead.
    if (P && P.standalone() && P.shouldAsk()) {
      announce(savedMessage);
      P.ask(pushAskText(), function (yes) {
        if (yes) {
          P.enable(savedIds(), langCode()).then(function (result) { pushDone(result); refocusStar(ev.id); });
          return;
        }
        if (yes === false) announce(t('push.no', '알림은 켜지 않을게요'));
        render();
        refocusStar(ev.id);
      });
      return;
    }
    // Signed in: the subscribed calendar on 마이 밥도둑 takes every star by itself (docs/CALENDAR_FEED.md), so the
    // star opens no calendar screen; a file download here can also cut off the account save (owner 2026-11-12).
    if (savedStore.remote) return announce(pushState === 'on' ? savedMessage + ' · ' + t('push.willAlert', '30분 전에 알림이 와요') : savedMessage);
    var details = { details: calendarDetails(ev), url: L.eventLink(ev.id) };
    var pref = L.starCalendar();
    if (pref === 'on') return announce(savedMessage + ' · ' + starCalendarMessage(L.addToCalendar(ev, details)));
    if (pushState === 'on') return announce(savedMessage + ' · ' + t('push.willAlert', '30분 전에 알림이 와요'));
    if (pref === 'off') return announce(savedMessage);
    announce(savedMessage);
    L.askStarCalendar(starCalendarText(), function (yes) {
      if (yes) announce(starCalendarMessage(L.addToCalendar(ev, details)));
      else if (yes === false) announce(t('starcal.done.no', '캘린더에는 넣지 않을게요'));
      render();
      refocusStar(ev.id);
    });
  }
  function pushToggleHtml() {
    if (!P) return '';
    if (pushState === 'on' || pushState === 'off') {
      var on = pushState === 'on';
      return '<p class="gg-starcal-line"><button type="button" class="gg-btn gg-starcal" data-gg-push aria-pressed="' + on + '">' +
        esc(t('push.toggle', '별 누른 꽁밥 30분 전 알림')) + ' <strong>' + esc(on ? t('push.on', '켜짐') : t('push.off', '꺼짐')) + '</strong></button></p>';
    }
    if (pushState === 'home') return '<p class="gg-saved-note">' + esc(t('push.home', '홈 화면에 추가한 밥도둑에서 알림을 켤 수 있어요.')) + '</p>';
    if (pushState === 'denied') return '<p class="gg-saved-note">' + esc(t('push.blocked', '알림이 막혀 있어요. 휴대폰 설정에서 허용해 주세요.')) + '</p>';
    return '';
  }
  function starCalendarToggleHtml() {
    if (!L) return '';
    var on = L.starCalendar() === 'on';
    return '<p class="gg-starcal-line"><button type="button" class="gg-btn gg-starcal" data-gg-starcal aria-pressed="' + on + '">' +
      esc(t('starcal.toggle', '별 누를 때 캘린더에도 넣기')) + ' <strong>' +
      esc(on ? t('starcal.on', '켜짐') : t('starcal.off', '꺼짐')) + '</strong></button></p>';
  }
  function liveClick(e) {
    var el;
    if ((el = e.target.closest('[data-gg-save]'))) {
      var id = el.getAttribute('data-gg-save'), ev = rowById(id);
      if (savedStore.has(id)) {
        if (savedStore.remove(id)) { announce(t('gg.live.unsavedMsg', '저장을 지웠어요')); pushChanged(); }
      } else if (ev && savedStore.add(ev)) {
        render();
        afterStar(ev, savedStore.remote ? t('gg.live.savedAccountMsg', '저장했어요') : t('gg.live.savedMsg', '저장했어요'));
        return true;
      } else {
        announce(t('gg.live.saveFail', '이 브라우저에서는 저장할 수 없어요'));
      }
      render();
      return true;
    }
    if (P && e.target.closest('[data-gg-push]')) {
      // Inside the click: turning on asks the phone's permission question right here.
      var turningOn = pushState !== 'on';
      (turningOn ? P.enable(savedIds(), langCode()) : P.disable()).then(function (result) {
        if (turningOn) pushDone(result);
        else {
          if (result === 'off') { pushState = 'off'; announce(t('push.nowOff', '30분 전 알림을 껐어요')); }
          else announce(t('push.fail', '알림을 켜지 못했어요. 다시 시도해 주세요.'));
          render();
        }
        var toggle = root.querySelector('[data-gg-push]');
        if (toggle) toggle.focus({ preventScroll: true });
      });
      return true;
    }
    if (e.target.closest('[data-gg-starcal]')) {
      var turnOn = L.starCalendar() !== 'on';
      if (L.setStarCalendar(turnOn)) announce(turnOn ? t('starcal.nowOn', '캘린더 넣기를 켰어요') : t('starcal.nowOff', '캘린더 넣기를 껐어요'));
      else announce(t('gg.live.saveFail', '이 브라우저에서는 저장할 수 없어요'));
      render();
      var sw = root.querySelector('[data-gg-starcal]');
      if (sw) sw.focus({ preventScroll: true });
      return true;
    }
    if ((el = e.target.closest('[data-gg-unsave]'))) {
      if (savedStore.remove(el.getAttribute('data-gg-unsave'))) { announce(t('gg.live.unsavedMsg', '저장을 지웠어요')); pushChanged(); }
      render();
      var head = root.querySelector('[data-gg-saved]');
      if (head) head.focus({ preventScroll: true });
      return true;
    }
    if ((el = e.target.closest('[data-gg-ack]'))) {
      var acked = rowById(el.getAttribute('data-gg-ack'));
      if (acked) savedStore.acknowledge(acked);
      render();
      return true;
    }
    if ((el = e.target.closest('[data-gg-share]'))) {
      var shared = rowById(el.getAttribute('data-gg-share'));
      if (shared) shareOut(shared.id, eventShare(shared));
      return true;
    }
    if (e.target.closest('[data-gg-share-week]')) { shareOut('week', weekShare(nowKst())); return true; }
    if ((el = e.target.closest('[data-gg-cal]'))) {
      var calId = el.getAttribute('data-gg-cal');
      if (state.calOpen[calId]) delete state.calOpen[calId]; else state.calOpen[calId] = true;
      render();
      return true;
    }
    if ((el = e.target.closest('[data-gg-ics]'))) {
      var calEv = rowById(el.getAttribute('data-gg-ics'));
      if (calEv && L.canCalendar(calEv, nowKst())) downloadIcs(calEv);
      return true;
    }
    if (e.target.closest('[data-gg-more]')) { state.moreFilters = !state.moreFilters; render(); return true; }
    if (e.target.closest('[data-gg-reset]')) {
      state.food = 'all'; state.day = 'all'; state.who = 'all'; state.area = 'all';
      if (state.entry.notice && state.entry.notice.kind === 'week') state.entry.notice = null;
      try { localStorage.setItem('babdoduk-ggongbab-filter', JSON.stringify({ when: 'all', food: 'all' })); } catch (err) {}
      render();
      var first = root.querySelector('.gg-chip[data-group="food"][data-value="all"]');
      if (first) first.focus({ preventScroll: true });
      announce(t('gg.live.resetDone', '필터를 초기화했어요'));
      return true;
    }
    if (e.target.closest('[data-gg-saved]')) { state.savedOpen = !state.savedOpen; render(); return true; }
    if ((el = e.target.closest('[data-gg-goto]'))) {
      var goId = el.getAttribute('data-gg-goto');
      var goEv = rowById(goId);
      if (goEv && visibleEvents(nowKst()).indexOf(goEv) < 0) { state.food = 'all'; state.day = 'all'; state.who = 'all'; state.area = 'all'; }
      state.open[goId] = true;
      render();
      focusCard(goId);
      return true;
    }
    if (e.target.closest('[data-gg-new-close]')) {
      try { localStorage.setItem(NOTICE_KEY, '1'); } catch (err) {}
      render();
      var title = root.querySelector('.gg-hero h1');
      if (title) { title.setAttribute('tabindex', '-1'); title.focus({ preventScroll: true }); }
      return true;
    }
    if (e.target.closest('[data-gg-entry-close]')) { state.entry.notice = null; render(); return true; }
    return false;
  }
  root.addEventListener('click', function (e) {
    if (L && liveClick(e)) return;
    var tabEl = e.target.closest('[data-hub-tab]');
    if (tabEl) {
      setTab(tabEl.getAttribute('data-hub-tab'));
      return;
    }
    var chipEl = e.target.closest('.gg-chip');
    if (chipEl && !chipEl.disabled) {
      var group = chipEl.getAttribute('data-group');
      var value = chipEl.getAttribute('data-value');
      if (group === 'day' || group === 'who' || group === 'area') {
        state[group] = value;                      // the optional filters are not saved
        render();
        return;
      }
      if (group === 'food') state.food = value;
      // `when` stays in the saved value, always 'all', so a page from before the change still reads it.
      try { localStorage.setItem('babdoduk-ggongbab-filter', JSON.stringify({ when: 'all', food: state.food })); } catch (err) {}
      render();
      return;
    }
    var openBtn = e.target.closest('[data-gg-open]');
    if (openBtn) {
      var id = openBtn.getAttribute('data-gg-open');
      if (state.open[id]) delete state.open[id]; else state.open[id] = true;
      var card = openBtn.closest('.gg-card'), detail = card && card.querySelector('.gg-detail');
      openBtn.setAttribute('aria-expanded', String(!!state.open[id]));
      if (card) card.classList.toggle('is-open', !!state.open[id]);
      if (detail) detail.hidden = !state.open[id];
      return;
    }
    if (e.target.closest('[data-gg-archive-more]')) {
      state.archive.expanded = !state.archive.expanded;
      render();
      return;
    }
    var scrollBtn = e.target.closest('[data-gg-scroll]');
    if (scrollBtn) {
      focusCard(scrollBtn.getAttribute('data-gg-scroll'));
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
  document.addEventListener('babdoduk-lang', pushChanged);
  // Expiry remains client-side even if the backend has not deleted a row yet.
  var expiryTimer;
  function resumeFeed() {
    if (document.hidden) return;
    if (feedCtl) feedCtl.start();
    clearInterval(expiryTimer);
    expiryTimer = setInterval(function () { if (state.free.status === 'ready') render(); }, 60000);
    if (state.free.status === 'ready') render();
  }
  function pauseFeed() {
    clearInterval(expiryTimer);
    if (feedCtl) feedCtl.stop();
  }
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) pauseFeed(); else resumeFeed();
  });
  window.addEventListener('pagehide', pauseFeed);
  window.addEventListener('pageshow', resumeFeed);

  try {
    var saved = JSON.parse(localStorage.getItem('babdoduk-ggongbab-filter') || 'null');
    // A saved day (from the day tiles, gone since 2026-11-05) is ignored; the food filter stays.
    if (saved && FOOD_FILTERS.indexOf(saved.food) >= 0) state.food = saved.food;   // anything else stays 'all'
  } catch (err) {}
  try {
    var tabSaved = localStorage.getItem(TAB_KEY);
    if (tabSaved === 'menu' || tabSaved === 'free') state.activeSection = tabSaved;
  } catch (err) {}
  if (location.hash === '#menu' || location.hash === '#free') state.activeSection = location.hash.slice(1);
  // 꽁밥 LIVE share links: ?e=<listing id> and ?week=<a date in the week, read as its Monday>; #saved opens the saved list.
  if (L) {
    var entryId = query.get('e') || '';
    if (/^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$/.test(entryId)) state.entry.id = entryId;
    var entryWeek = query.get('week') || '';
    if (L.isYmd(entryWeek)) state.entry.week = L.mondayOf(entryWeek);
    if (state.entry.id || state.entry.week) state.activeSection = 'free';
    if (location.hash === '#saved') state.savedOpen = true;
  }
  window.addEventListener('hashchange', function () {
    if (location.hash === '#menu' || location.hash === '#free') setTab(location.hash.slice(1));
  });
  function start() {
    pushRefresh();
    loadFree();
    loadArchive();
    loadNews();
    if (document.hidden) pauseFeed(); else resumeFeed();
  }
  // Fixture mode (the lab page only) reads its synthetic data from tests/fixtures/, which the local
  // server serves (python scripts/check_ggongbab_ui.py --serve) and no deployment carries.
  if (mode === 'fixture') {
    var fixtureScript = document.createElement('script');
    fixtureScript.src = 'tests/fixtures/ggongbab-lab.js';
    fixtureScript.onload = start;
    fixtureScript.onerror = function () {
      state.free.status = 'error';
      state.archive.status = 'off';
      state.news.status = 'off';
      render();
    };
    document.head.appendChild(fixtureScript);
  } else {
    start();
  }
})();
