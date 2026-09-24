/* Banner shelf. Native horizontal scrolling does the work (swipe, trackpad,
   wheel, keyboard focus); the buttons only scroll by about one view, and
   nothing ever moves on its own. */
(function () {
  var track = document.getElementById('homeShelf');
  var nav = document.querySelector('[data-shelf-nav]');
  if (!track || !nav) return;
  var buttons = Array.prototype.slice.call(nav.querySelectorAll('[data-shelf-dir]'));
  function still() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  // aria-disabled rather than disabled, so a keyboard user's focus stays put at either end.
  function update() {
    var max = track.scrollWidth - track.clientWidth;
    nav.hidden = max <= 1;
    buttons.forEach(function (btn) {
      var back = btn.getAttribute('data-shelf-dir') === '-1';
      btn.setAttribute('aria-disabled', String(back ? track.scrollLeft <= 1 : track.scrollLeft >= max - 1));
    });
  }
  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.getAttribute('aria-disabled') === 'true') return;
      var step = Math.max(240, Math.round(track.clientWidth * 0.7));
      track.scrollBy({ left: Number(btn.getAttribute('data-shelf-dir')) * step, behavior: still() ? 'auto' : 'smooth' });
    });
  });
  track.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update);
  window.addEventListener('load', update);
  update();
})();

/* Home summary. Reads the same generated public data as the food hub and the
   magazine, with their freshness and eligibility rules, and links to them for
   detail. It never states more than the payload supports. */
(function () {
  var M = window.BabdodukKaistMenu;
  var F = window.BabdodukFreeFood;
  var menuEl = document.getElementById('homeMenuStatus');
  var freeEl = document.getElementById('homeFreeStatus');
  var featureEl = document.getElementById('homeFeature');
  var stampEl = document.getElementById('homeStamp');
  var todayDateEl = document.querySelector('[data-home-banner-date]');
  if (!M || !F || !menuEl || !freeEl) return;

  var state = {
    menu: { status: 'loading', data: null },
    free: { status: 'loading', data: null },
    magazine: null
  };
  var DESK = { tips: 'home.desk.tips', trend: 'home.desk.trend', health: 'home.desk.health', habit: 'home.desk.habit' };

  function t(key, fallback) {
    var lang = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function hm(d) { return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function dateLabel(d) {
    if (lang() === 'en') {
      return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()] + ', ' +
        ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()] + ' ' + d.getDate();
    }
    return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + ['일', '월', '화', '수', '목', '금', '토'][d.getDay()] + '요일';
  }
  function isoDateLabel(iso) {
    var parts = String(iso || '').split('-');
    if (parts.length < 3) return String(iso || '');
    return dateLabel(new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
  }
  function setStatus(el, kind, headline, meta) {
    el.setAttribute('data-state', kind);
    var head = el.querySelector('[data-home-headline]');
    head.removeAttribute('data-i18n');
    head.textContent = headline;
    el.querySelector('[data-home-meta]').textContent = meta || '';
  }

  function renderMenu() {
    var s = state.menu;
    if (s.status === 'loading') return setStatus(menuEl, 'loading', t('home.menu.loading', '학식 메뉴 확인 중'), '');
    if (s.status === 'error') return setStatus(menuEl, 'error', t('home.menu.error', '학식 메뉴를 불러오지 못했어요'), t('home.menu.retry', ''));
    var now = F.nowKst();
    var date = isoDateLabel(s.data.date);
    if (M.isStale(s.data, now)) {
      return setStatus(menuEl, 'stale', t('home.menu.stale', '오늘 메뉴는 아직 올라오지 않았어요'),
        s.data.date ? t('home.menu.last', '마지막으로 올라온 메뉴: {date}').replace('{date}', date) : '');
    }
    var n = M.restaurantsWithMenus(s.data).length;
    var source = t('home.menu.source', '{date} · KAIST 공식 식단').replace('{date}', date);
    if (!n) return setStatus(menuEl, 'empty', t('home.menu.none', '오늘 올라온 메뉴가 아직 없어요'), source);
    setStatus(menuEl, 'ready', t('home.menu.today', '오늘 {n}곳 메뉴가 올라왔어요').replace('{n}', String(n)), source);
  }

  function renderFree() {
    var s = state.free;
    if (s.status === 'loading') return setStatus(freeEl, 'loading', t('home.free.loading', '꽁밥 일정 확인 중'), '');
    if (s.status === 'error') return setStatus(freeEl, 'error', t('home.free.error', '꽁밥 일정을 불러오지 못했어요'), '');
    var now = F.nowKst();
    var events = s.data.events || [];
    var today = F.todayUpcoming(events, now);
    var headline;
    if (today.length) {
      headline = t('home.free.today', '오늘 {n}개 예정').replace('{n}', String(today.length));
      var soon = today.map(function (ev) { return F.toKst(ev.startAt); }).filter(function (d) { return d && d >= now; })[0];
      if (soon) headline += ' · ' + t('home.free.soonest', '가장 빠른 시작 {time}').replace('{time}', hm(soon));
    } else {
      var next = F.futurePublic(events, now)[0];
      headline = next ? t('home.free.next', '오늘은 없어요 · 다음 일정 {date}').replace('{date}', dateLabel(F.toKst(next.startAt)))
        : t('home.free.none', '예정된 꽁밥이 아직 없어요');
    }
    var published = F.toKst(s.data.generatedAt);
    var meta = published ? t('home.free.asOf', '마지막 발행 {time}').replace('{time}', dateLabel(published) + ' ' + hm(published)) : '';
    setStatus(freeEl, today.length ? 'ready' : 'empty', headline, meta);
  }

  function renderFeature() {
    var ed = state.magazine;
    var featured = ed && ed.featured;
    if (!featureEl || !featured || !featured.title) return;
    var meta = [t(DESK[featured.category] || DESK[featured.lane] || '', ''), featured.source,
      t('home.mag.edition', '{date}자').replace('{date}', isoDateLabel(ed.date))].filter(Boolean).join(' · ');
    featureEl.querySelector('[data-home-feature-meta]').textContent = meta;
    featureEl.querySelector('[data-home-feature-title]').textContent = featured.title;
    featureEl.querySelector('[data-home-feature-summary]').textContent = String(featured.summary || '').split('\n')[0];
    featureEl.hidden = false;
  }

  // The Today banner is stamped with the KST date only; it makes no claim about data.
  function renderTodayBanner() {
    if (!todayDateEl) return;
    var now = F.nowKst();
    var day = document.createElement('span');
    day.className = 'home-banner-date-day';
    day.textContent = String(now.getMonth() + 1).padStart(2, '0') + '.' + String(now.getDate()).padStart(2, '0');
    var week = document.createElement('span');
    week.className = 'home-banner-date-week';
    week.textContent = lang() === 'en'
      ? ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][now.getDay()]
      : ['일', '월', '화', '수', '목', '금', '토'][now.getDay()] + '요일';
    todayDateEl.replaceChildren(day, week);
  }

  function render() {
    if (stampEl) stampEl.textContent = t('home.stamp', '{date} 기준').replace('{date}', dateLabel(F.nowKst()));
    renderMenu();
    renderFree();
    renderFeature();
    renderTodayBanner();
  }

  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    });
  }

  render();
  getJson('data/kaist-menu/latest.json').then(function (data) {
    if (!data || !Array.isArray(data.restaurants)) throw new Error('bad');
    state.menu = { status: 'ready', data: data };
  }).catch(function () {
    state.menu = { status: 'error', data: null };
  }).then(render);
  // The validated static snapshot, which the 오늘의 꽁밥 page reads as well.
  // Name its publication time: loading a page does not make the data current.
  getJson('data/ggongbab/latest.json').then(function (data) {
    if (!data || !Array.isArray(data.events)) throw new Error('bad');
    state.free = { status: 'ready', data: data };
  }).catch(function () {
    state.free = { status: 'error', data: null };
  }).then(render);
  getJson('data/magazine/index.json').then(function (index) {
    return getJson('data/magazine/' + encodeURIComponent(index.latest) + '.json');
  }).then(function (edition) {
    state.magazine = edition;
  }).catch(function () {}).then(render);
  document.addEventListener('babdoduk-lang', render);
})();
