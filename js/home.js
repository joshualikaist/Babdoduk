/* Home summary: the cafeteria line. Reads the same generated public data as the food hub, with its
   freshness rules, and links to it for detail. It never states more than the payload supports. Free
   food is the calendar's (js/home-calendar.js). The banner shelf, the magazine pick and the news
   group below the hero are gone (owner 2026-11-02). */
(function () {
  var M = window.BabdodukKaistMenu;
  var F = window.BabdodukFreeFood;
  var menuEl = document.getElementById('homeMenuStatus');
  if (!M || !F || !menuEl) return;

  var state = {
    menu: { status: 'loading', data: null }
  };

  function t(key, fallback) {
    var lang = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
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
    if (s.status === 'error') return setStatus(menuEl, 'error', t('home.menu.error', '학식 메뉴를 불러오지 못했어요'), '');
    var now = F.nowKst();
    var date = isoDateLabel(s.data.date);
    if (M.isStale(s.data, now)) {
      var weekend = M.isWeekend && M.isWeekend(now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0'));
      return setStatus(menuEl, 'stale', weekend ? t('home.menu.weekend', '주말엔 학식이 없어요') : t('home.menu.stale', '오늘 메뉴는 아직 올라오지 않았어요'),
        s.data.date ? t('home.menu.last', '{date} 메뉴').replace('{date}', date) : '');
    }
    var n = M.restaurantsWithMenus(s.data).length;
    var source = t('home.menu.source', '{date} · KAIST 공식 식단').replace('{date}', date);
    if (!n) return setStatus(menuEl, 'empty', t('home.menu.none', '오늘 메뉴가 아직 없어요'), source);
    setStatus(menuEl, 'ready', t('home.menu.today', '오늘 {n}곳').replace('{n}', String(n)), source);
  }

  function render() {
    renderMenu();
  }

  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    });
  }

  render();
  M.loadTodayMenu(getJson).then(function (data) {
    if (!data || !Array.isArray(data.restaurants)) throw new Error('bad');
    state.menu = { status: 'ready', data: data };
  }).catch(function () {
    state.menu = { status: 'error', data: null };
  }).then(render);
  document.addEventListener('babdoduk-lang', render);
})();
