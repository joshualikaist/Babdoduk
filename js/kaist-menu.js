/* KAIST cafeteria renderer. Mukbang keeps its compact panel; the food hub
   attaches a meal/restaurant grid. Official items are never re-ranked. */
(function (global) {
  var MEALS = ['breakfast', 'lunch', 'dinner'];
  var FAVORITES_KEY = 'babdoduk-menu-favorites';
  var MEAL_KEY = 'babdoduk-menu-meal';
  var KST_OFFSET = 9 * 60;

  function t(key, fallback) {
    var lang = global.babdodukGetLang ? global.babdodukGetLang() : 'ko';
    var pack = global.BABDODUK_STR && global.BABDODUK_STR[lang];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function toKst(iso) {
    var d = iso ? new Date(iso) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    return new Date(d.getTime() + (d.getTimezoneOffset() + KST_OFFSET) * 60000);
  }
  function ymd(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function defaultMeal(now) {
    var clock = now || toKst();
    var minutes = clock.getHours() * 60 + clock.getMinutes();
    if (minutes < 10 * 60 + 30) return 'breakfast';
    if (minutes < 15 * 60) return 'lunch';
    return 'dinner';
  }
  function mealLabel(key) {
    return t('km.' + key, { breakfast: '아침', lunch: '점심', dinner: '저녁' }[key] || key);
  }
  function dateHeading(isoDate) {
    if (!isoDate) return '';
    var parts = String(isoDate).split('-');
    if (parts.length < 3) return isoDate;
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    var lang = global.babdodukGetLang ? global.babdodukGetLang() : 'ko';
    var dows = lang === 'en' ? ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
      : ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
    if (lang === 'en') {
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return months[d.getMonth()] + ' ' + d.getDate() + ' · ' + dows[d.getDay()];
    }
    return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 · ' + dows[d.getDay()];
  }
  function mealItems(resto, meal) {
    var block = resto && resto[meal];
    return (block && Array.isArray(block.items)) ? block.items : [];
  }
  function hasAnyMeal(resto) {
    return MEALS.some(function (meal) { return mealItems(resto, meal).length > 0; });
  }
  function restaurantsWithMenus(data) {
    return ((data && data.restaurants) || []).filter(hasAnyMeal);
  }
  // Weekly browsing: a payload is right when it is for the SELECTED date. A future date is
  // not "stale" merely because it is not today; staleness is a today-only question.
  function isDataForSelectedDate(data, selectedDate) {
    return !!(data && data.date && selectedDate && data.date === selectedDate);
  }
  function isToday(selectedDate, today) {
    return !!selectedDate && selectedDate === (today || ymd(toKst()));
  }
  function isStale(data, today) {
    return !isDataForSelectedDate(data, ymd(today));
  }
  function pad2(n) { return String(n).padStart(2, '0'); }
  function utcDay(isoDate) {
    var p = String(isoDate || '').split('-');
    if (p.length < 3) return null;
    var time = Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return isNaN(time) ? null : time;
  }
  function utcYmd(time) {
    var d = new Date(time);
    return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  }
  // Monday to Sunday of the KST week containing `todayIso` (calendar arithmetic in UTC, so
  // month/year boundaries, leap days and the viewer's own timezone cannot shift it).
  function weekDates(todayIso) {
    var time = utcDay(todayIso);
    if (time == null) return [];
    var monday = time - ((new Date(time).getUTCDay() + 6) % 7) * 86400000;
    var out = [];
    for (var i = 0; i < 7; i++) out.push(utcYmd(monday + i * 86400000));
    return out;
  }
  function dayLabel(isoDate) {
    var time = utcDay(isoDate);
    var d = new Date(time);
    var lang = global.babdodukGetLang ? global.babdodukGetLang() : 'ko';
    var dows = lang === 'en' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['일', '월', '화', '수', '목', '금', '토'];
    var day = d.getUTCDate();
    return { dow: dows[d.getUTCDay()], num: day === 1 ? (d.getUTCMonth() + 1) + '/1' : String(day) };
  }
  function readFavorites() {
    try {
      var raw = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]');
      return Array.isArray(raw) ? raw.map(String) : [];
    } catch (err) { return []; }
  }
  function writeFavorites(ids) {
    try { localStorage.setItem(FAVORITES_KEY, JSON.stringify(ids)); } catch (err) {}
  }
  function readSavedMeal() {
    try {
      var saved = localStorage.getItem(MEAL_KEY);
      if (MEALS.indexOf(saved) >= 0) return saved;
    } catch (err) {}
    return '';
  }
  function writeMeal(meal) {
    try { localStorage.setItem(MEAL_KEY, meal); } catch (err) {}
  }
  // Re-rendering replaces the markup; keep keyboard users on the same control.
  function focusSelector(host) {
    var el = document.activeElement;
    if (!el || el === host || !host.contains(el)) return '';
    if (el.id) return '#' + el.id;
    var parts = [];
    Array.prototype.forEach.call(el.attributes, function (attr) {
      if (attr.name.indexOf('data-') === 0) parts.push('[' + attr.name + '="' + String(attr.value).replace(/["\\]/g, '') + '"]');
    });
    return parts.length ? el.tagName.toLowerCase() + parts.join('') : '';
  }
  function restoreFocus(host, selector) {
    if (!selector) return;
    var el = host.querySelector(selector);
    if (el && el.focus) el.focus({ preventScroll: true });
  }
  function sortRestaurants(list, favorites) {
    var fav = [];
    var rest = [];
    list.forEach(function (row) {
      if (favorites.indexOf(row.id) >= 0) fav.push(row);
      else rest.push(row);
    });
    fav.sort(function (a, b) { return favorites.indexOf(a.id) - favorites.indexOf(b.id); });
    return fav.concat(rest);
  }
  function fixtureMenu(stale, now) {
    var today = now || toKst();
    var date = stale ? ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)) : ymd(today);
    var longName = '아주 긴 메뉴 이름으로 확인하는 특제 돈가스 덮밥과 계절 나물 모둠';
    return {
      date: date,
      dateLabel: dateHeading(date),
      fetchedAt: new Date().toISOString(),
      source: 'fixture',
      restaurants: [
        { id: 'fclt', name: '카이마루 N11', building: 'N11',
          breakfast: { hours: '', items: ['쌀밥', '사골파국', '너비아니구이'], price: '3,500원', kcal: '623 kcal' },
          lunch: { hours: '', items: ['자율코너', '쌀밥', '시금치된장국', '닭살고추장볶음', '목이버섯굴소스볶음', '열무겉절이', '맛김치', '야채샐러드'], price: '5,500원', kcal: '1,292 kcal' },
          dinner: { hours: '', items: ['쌀밥', '된장찌개', '제육볶음'], price: '5,500원', kcal: '1,180 kcal' } },
        { id: 'west', name: '서맛골 W2', building: 'W2',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['비빔밥', '미역국', '김치'], price: '4,000원', kcal: '' },
          dinner: { hours: '', items: ['라면', '김밥'], price: '4,000원', kcal: '' } },
        { id: 'east1', name: '동맛골 1층', building: 'E2',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['백반', '콩나물국'], price: '', kcal: '980 kcal' },
          dinner: { hours: '', items: ['볶음밥', '계란국'], price: '', kcal: '1,050 kcal' } },
        { id: 'east2', name: '동맛골 2층', building: 'E2',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['돈가스', '우동', '샐러드'], price: '6,000원', kcal: '1,410 kcal' },
          dinner: { hours: '', items: ['카레라이스', '단무지'], price: '5,500원', kcal: '1,200 kcal' } },
        { id: 'icc', name: 'ICC 식당', building: 'W1',
          breakfast: { hours: '', items: ['토스트', '우유'], price: '3,000원', kcal: '' },
          lunch: { hours: '', items: [longName, '스프', '샐러드', '피클', '후식 과일', '미니 빵', '수프 리필', '계절 음료'], price: '7,000원', kcal: '1,520 kcal' },
          dinner: { hours: '', items: [] } },
        { id: 'hawam', name: '교수회관', building: 'N1',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['한정식', '국', '나물'], price: '8,000원', kcal: '1,100 kcal' },
          dinner: { hours: '', items: [] } }
      ]
    };
  }

  // Lab fixture for the other days of the week: weekdays have menus (a different number of
  // places each day), Saturday has lunch only, Sunday has nothing published.
  function fixtureDay(isoDate) {
    var time = utcDay(isoDate);
    if (time == null) return null;
    var dow = new Date(time).getUTCDay();
    if (dow === 0) return null;
    var base = fixtureMenu(false);
    var keep = dow === 6 ? 2 : Math.max(2, base.restaurants.length - (dow % 3));
    var restaurants = base.restaurants.slice(0, keep).map(function (row) {
      var copy = JSON.parse(JSON.stringify(row));
      if (dow === 6) { copy.breakfast = { items: [] }; copy.dinner = { items: [] }; }
      if (copy.lunch && copy.lunch.items && copy.lunch.items.length) copy.lunch.items[0] = copy.lunch.items[0] + ' · ' + isoDate.slice(5);
      return copy;
    });
    return { date: isoDate, dateLabel: dateHeading(isoDate), fetchedAt: base.fetchedAt, source: 'fixture', restaurants: restaurants };
  }

  function attach(host, options) {
    options = options || {};
    var today = ymd(toKst());
    var state = {
      status: 'loading',
      data: null,
      error: '',
      meal: readSavedMeal() || defaultMeal(toKst()),
      favorites: readFavorites(),
      expanded: {},
      showStale: false,
      host: host,
      // The cafeteria week. The selected date is page state only: every load starts at today.
      today: today,
      week: weekDates(today),
      selected: today,
      weekIndex: null,
      days: {}
    };
    function emit() {
      if (typeof options.onChange === 'function') options.onChange(snapshot());
    }
    // Always TODAY: the page's top metric and the free-food hints describe today, whichever
    // cafeteria date is being browsed.
    function snapshot() {
      var stale = !isDataForSelectedDate(state.data, ymd(toKst()));
      return {
        status: state.status,
        stale: stale,
        meal: state.meal,
        restaurantCount: (!stale && state.data) ? restaurantsWithMenus(state.data).length : 0,
        data: state.data,
        error: state.error,
        selectedDate: state.selected
      };
    }
    function selectedToday() { return isToday(state.selected, state.today); }
    function weekEntry(date) {
      var index = state.weekIndex;
      if (!index || !Array.isArray(index.days)) return null;
      return index.days.filter(function (row) { return row && row.date === date; })[0] || null;
    }
    function visibleRestaurants(data) {
      var list = (data && data.restaurants) || [];
      var withMeal = list.filter(function (row) { return mealItems(row, state.meal).length > 0; });
      return sortRestaurants(withMeal, state.favorites);
    }
    function cardHtml(resto) {
      var meal = resto[state.meal] || {};
      var items = mealItems(resto, state.meal);
      var expanded = !!state.expanded[resto.id];
      var shown = expanded ? items : items.slice(0, 5);
      var fav = state.favorites.indexOf(resto.id) >= 0;
      var html = '<article class="km-card" data-km-id="' + esc(resto.id) + '">';
      html += '<div class="km-card-head"><div><p class="km-resto">' + esc(resto.name || resto.id) + '</p>';
      if (resto.building) html += '<span class="km-building">' + esc(resto.building) + '</span>';
      html += '</div><button type="button" class="km-fav" data-km-fav="' + esc(resto.id) + '" aria-pressed="' + fav + '" aria-label="' + esc(fav ? t('km.unfav', '즐겨찾기 해제') : t('km.fav', '즐겨찾기')) + '">' + (fav ? '★' : '☆') + '</button></div>';
      html += '<ul class="km-items">';
      shown.forEach(function (item) { html += '<li>' + esc(item) + '</li>'; });
      html += '</ul>';
      if (items.length > 5) {
        html += '<button type="button" class="km-expand" data-km-expand="' + esc(resto.id) + '" aria-expanded="' + expanded + '">' +
          esc(expanded ? t('km.collapse', '메뉴 접기 ↑') : t('km.expand', '전체 메뉴 {n}개 보기 ↓').replace('{n}', String(items.length))) + '</button>';
      }
      if (meal.price || meal.kcal) {
        html += '<div class="km-meta">';
        if (meal.price) html += '<span class="km-price">' + esc(meal.price) + '</span>';
        if (meal.kcal) html += '<span class="km-kcal">' + esc(meal.kcal) + '</span>';
        html += '</div>';
      }
      return html + '</article>';
    }
    function emptyHtml(data, todayStale) {
      var title = todayStale ? t('km.staleEmpty', '최근 메뉴를 보려면 아래를 눌러 주세요.')
        : (selectedToday() ? t('km.emptyTitle', '오늘 이 시간대에 공개된 메뉴가 없어요.') : t('km.emptyMeal', '이 시간대에 공개된 메뉴가 없어요.'));
      var html = '<div class="gg-state"><strong>' + esc(title) + '</strong>';
      MEALS.forEach(function (meal) {
        if (meal === state.meal) return;
        var n = ((data && data.restaurants) || []).filter(function (row) { return mealItems(row, meal).length; }).length;
        if (n) html += '<button type="button" class="km-cta is-ghost" data-km-meal="' + meal + '">' + esc(t('km.mealLink', '{meal} 메뉴 보기 →').replace('{meal}', mealLabel(meal))) + '</button>';
      });
      html += '<button type="button" class="km-cta is-ghost" data-hub-tab="free">' + esc(t('km.toFree', '꽁밥 보러가기 →')) + '</button>';
      return html + '</div>';
    }
    function daysHtml() {
      var html = '<div class="km-days" role="group" aria-label="' + esc(t('km.daysAria', '날짜')) + '">';
      state.week.forEach(function (date, idx) {
        var on = date === state.selected;
        var isTodayDate = isToday(date, state.today);
        var label = dayLabel(date, idx);
        var aria = dateHeading(date) + (isTodayDate ? ' · ' + t('km.today', '오늘') : '');
        html += '<button type="button" class="km-day' + (isTodayDate ? ' is-today' : '') + '" data-km-date="' + esc(date) +
          '" aria-pressed="' + on + '"' + (isTodayDate ? ' aria-current="date"' : '') + ' aria-label="' + esc(aria) + '">' +
          '<span class="km-day-dow" aria-hidden="true">' + esc(label.dow) + '</span>' +
          '<span class="km-day-num" aria-hidden="true">' + esc(label.num) + '</span>' +
          (isTodayDate ? '<span class="km-day-today" aria-hidden="true">' + esc(t('km.today', '오늘')) + '</span>' : '') +
          '</button>';
      });
      return html + '</div>';
    }
    function mealsHtml() {
      var html = '<div class="km-meals" role="group" aria-label="' + esc(t('km.mealsAria', '식사 시간')) + '">';
      MEALS.forEach(function (meal) {
        html += '<button type="button" class="km-meal" data-km-meal="' + meal + '" aria-pressed="' + (state.meal === meal) + '">' + esc(mealLabel(meal)) + '</button>';
      });
      return html + '</div>';
    }
    function subHtml(dateText, count) {
      var html = '<div class="km-sub"><p class="km-date">' + esc(dateText) + '</p>';
      if (count != null) html += '<p class="km-count">' + esc(t('km.count', '{meal} 메뉴 {n}곳').replace('{meal}', mealLabel(state.meal)).replace('{n}', String(count))) + '</p>';
      return html + '</div>';
    }
    function menuHtml(data, todayStale) {
      var rows = visibleRestaurants(data);
      var html = mealsHtml();
      if (!rows.length) return html + emptyHtml(data, todayStale);
      html += '<div class="km-grid">';
      rows.forEach(function (row) { html += cardHtml(row); });
      return html + '</div>';
    }
    function todayHtml() {
      if (state.status === 'loading') {
        return subHtml(dateHeading(state.selected)) + '<div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
      }
      if (state.status === 'error') {
        return subHtml(dateHeading(state.selected)) +
          '<div class="gg-state"><strong>' + esc(t('km.errorTitle', '오늘 메뉴를 불러오지 못했어요.')) + '</strong>' +
          esc(options.freeCountText || '') +
          '<br><button type="button" class="km-cta" data-km-retry>' + esc(t('gg.retry', '다시 시도')) + '</button>' +
          '<button type="button" class="km-cta is-ghost" data-hub-tab="free">' + esc(t('km.toFree', '꽁밥 보러가기 →')) + '</button></div>';
      }
      if (isDataForSelectedDate(state.data, state.selected)) {
        return subHtml(dateHeading(state.selected), visibleRestaurants(state.data).length) + menuHtml(state.data, false);
      }
      // latest.json still holds an earlier day: today's menu is not published yet.
      var html = '<div class="km-warn" data-km-stale="1"><strong>' + esc(t('km.staleTitle', '오늘 메뉴 업데이트 중이에요.')) + '</strong><br>' +
        esc(t('km.staleSaved', '최근 저장된 메뉴:')) + ' ' + esc(dateHeading(state.data && state.data.date)) +
        '<br><button type="button" class="km-stale-toggle" data-km-stale-toggle>' +
        esc(state.showStale ? t('km.hideStale', '최근 메뉴 숨기기') : t('km.showStale', '최근 메뉴 보기')) + '</button></div>';
      if (!state.showStale) return subHtml(dateHeading(state.selected)) + html + mealsHtml() + emptyHtml(state.data, true);
      return subHtml(t('km.recentTitle', '최근 학식 메뉴') + ' · ' + dateHeading(state.data && state.data.date),
        visibleRestaurants(state.data).length) + html + menuHtml(state.data, false);
    }
    function otherDayHtml() {
      var entry = state.days[state.selected];
      var heading = dateHeading(state.selected);
      if (!entry || entry.status === 'loading') {
        return subHtml(heading) + mealsHtml() + '<div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
      }
      if (entry.status === 'available') {
        return subHtml(heading, visibleRestaurants(entry.data).length) + menuHtml(entry.data, false);
      }
      if (entry.status === 'failed') {
        return subHtml(heading) + mealsHtml() + '<div class="gg-state" data-km-day-state="failed"><strong>' +
          esc(t('km.dayError', '메뉴를 불러오지 못했어요.')) + '</strong><br><button type="button" class="km-cta" data-km-retry-day>' +
          esc(t('gg.retry', '다시 시도')) + '</button></div>';
      }
      return subHtml(heading) + mealsHtml() + '<div class="gg-state" data-km-day-state="none"><strong>' +
        esc(t('km.noMenuYet', '아직 올라온 메뉴가 없어요.')) + '</strong></div>';
    }
    function render() {
      if (!state.host) return;
      var focus = focusSelector(state.host);
      var html = '<div class="km-head"><h2>' + esc(t('km.title', '이번 주 학식')) + '</h2></div>' + daysHtml();
      html += selectedToday() ? todayHtml() : otherDayHtml();
      state.host.innerHTML = html;
      restoreFocus(state.host, focus);
    }
    function load() {
      state.status = 'loading';
      render();
      emit();
      if (typeof options.getData === 'function') {
        try {
          state.data = options.getData();
          if (!state.data || !Array.isArray(state.data.restaurants)) throw new Error('bad');
          state.status = 'ready';
          state.error = '';
        } catch (err) {
          state.status = 'error';
          state.data = null;
          state.error = 'bad payload';
        }
        render();
        emit();
        return;
      }
      var url = options.url || 'data/kaist-menu/latest.json';
      fetch(url, { cache: 'no-store' }).then(function (res) {
        if (!res.ok) throw new Error('missing');
        return res.json();
      }).then(function (data) {
        if (!data || !Array.isArray(data.restaurants)) throw new Error('bad');
        state.data = data;
        state.status = 'ready';
        state.error = '';
        render();
        emit();
      }).catch(function () {
        state.status = 'error';
        state.data = null;
        state.error = 'unavailable';
        render();
        emit();
      });
    }
    // week.json only says which dates have a menu. It is asked for with the first date change,
    // so the today view makes the same requests as before; a missing or older index is
    // ignored and the dated files are simply fetched on demand.
    var weekRequest = null;
    function ensureWeek() {
      if (!weekRequest) {
        weekRequest = fetch(options.weekUrl || 'data/kaist-menu/week.json', { cache: 'no-store' }).then(function (res) {
          if (!res.ok) throw new Error('missing');
          return res.json();
        }).then(function (index) {
          if (index && index.weekStart === state.week[0] && Array.isArray(index.days)) state.weekIndex = index;
        }).catch(function () {});
      }
      return weekRequest;
    }
    function loadDay(date) {
      if (typeof options.getDay === 'function') {
        var fixture = null;
        try { fixture = options.getDay(date); } catch (err) { fixture = null; }
        state.days[date] = isDataForSelectedDate(fixture, date) && restaurantsWithMenus(fixture).length
          ? { status: 'available', data: fixture } : { status: 'none' };
        render();
        return;
      }
      state.days[date] = { status: 'loading' };
      render();
      var base = options.dayBase || 'data/kaist-menu/';
      ensureWeek().then(function () {
        var known = weekEntry(date);
        if (known && known.available === false && known.status === 'NOT_PUBLISHED_YET') return 'none';
        return fetch(base + date + '.json', { cache: 'no-store' }).then(function (res) {
          if (res.status === 404) return null;
          if (!res.ok) throw new Error('unavailable');
          return res.json();
        }).then(function (data) {
          if (data === null) return known && known.status === 'FETCH_FAILED' ? 'failed' : 'none';
          return data;
        });
      }).then(function (result) {
        if (result === 'none' || result === 'failed') state.days[date] = { status: result };
        else if (isDataForSelectedDate(result, date) && Array.isArray(result.restaurants)) {
          state.days[date] = { status: 'available', data: result };      // kept for this page session
        } else state.days[date] = { status: 'failed' };
        render();
      }).catch(function () {
        state.days[date] = { status: 'failed' };
        render();
      });
    }
    // A loaded date is reused for the rest of the page session; only a date that has no
    // menu yet or failed is asked again.
    function selectDate(date) {
      if (state.week.indexOf(date) < 0) return;
      state.selected = date;
      var entry = state.days[date];
      if (!isToday(date, state.today) && (!entry || entry.status === 'failed' || entry.status === 'none')) {
        loadDay(date);
        return;
      }
      render();
    }
    function onClick(e) {
      var dayBtn = e.target.closest && e.target.closest('[data-km-date]');
      if (dayBtn) {
        selectDate(dayBtn.getAttribute('data-km-date'));
        return;
      }
      var mealBtn = e.target.closest && e.target.closest('[data-km-meal]');
      if (mealBtn) {
        var meal = mealBtn.getAttribute('data-km-meal');
        if (MEALS.indexOf(meal) >= 0) {
          state.meal = meal;
          writeMeal(meal);
          render();
          emit();
        }
        return;
      }
      var favBtn = e.target.closest && e.target.closest('[data-km-fav]');
      if (favBtn) {
        var id = favBtn.getAttribute('data-km-fav');
        var idx = state.favorites.indexOf(id);
        if (idx >= 0) state.favorites.splice(idx, 1);
        else state.favorites.push(id);
        writeFavorites(state.favorites);
        render();
        return;
      }
      var exp = e.target.closest && e.target.closest('[data-km-expand]');
      if (exp) {
        var rid = exp.getAttribute('data-km-expand');
        state.expanded[rid] = !state.expanded[rid];
        render();
        return;
      }
      if (e.target.closest && e.target.closest('[data-km-stale-toggle]')) {
        state.showStale = !state.showStale;
        render();
        return;
      }
      if (e.target.closest && e.target.closest('[data-km-retry-day]')) {
        loadDay(state.selected);
        return;
      }
      if (e.target.closest && e.target.closest('[data-km-retry]')) {
        load();
      }
    }
    // Left/Right, Home and End move between dates; Enter or Space selects (native buttons).
    function onKeydown(e) {
      var day = e.target.closest && e.target.closest('[data-km-date]');
      if (!day) return;
      var idx = state.week.indexOf(day.getAttribute('data-km-date'));
      var next = { ArrowLeft: idx - 1, ArrowRight: idx + 1, Home: 0, End: state.week.length - 1 }[e.key];
      if (next == null || next < 0 || next >= state.week.length) return;
      e.preventDefault();
      var target = state.host.querySelector('[data-km-date="' + state.week[next] + '"]');
      if (target) target.focus();
    }
    host.addEventListener('click', onClick);
    host.addEventListener('keydown', onKeydown);
    function mount(nextHost) {
      if (nextHost && nextHost !== state.host) {
        state.host.removeEventListener('click', onClick);
        state.host.removeEventListener('keydown', onKeydown);
        state.host = nextHost;
        state.host.addEventListener('click', onClick);
        state.host.addEventListener('keydown', onKeydown);
      } else if (nextHost) state.host = nextHost;
      render();
    }
    load();
    return {
      mount: mount,
      reload: load,
      snapshot: snapshot,
      selectDate: selectDate,
      setFreeCountText: function (text) { options.freeCountText = text; },
      setMeal: function (meal) {
        if (MEALS.indexOf(meal) >= 0) { state.meal = meal; writeMeal(meal); render(); emit(); }
      }
    };
  }

  global.BabdodukKaistMenu = {
    attach: attach,
    defaultMeal: defaultMeal,
    fixtureMenu: fixtureMenu,
    fixtureDay: fixtureDay,
    isStale: isStale,
    isDataForSelectedDate: isDataForSelectedDate,
    isToday: isToday,
    weekDates: weekDates,
    restaurantsWithMenus: restaurantsWithMenus
  };

  var summary = document.getElementById('kaistToday');
  if (!summary) return;
  // Cafeteria summary on the menu picker page: same KST clock, freshness rule and escaping as the hub.
  var mukState = { status: 'loading', data: null, resto: '', meal: defaultMeal(toKst()) };
  function mukGroup(label, attr, rows, current) {
    var html = '<div class="kaist-' + attr + 's" role="group" aria-label="' + esc(label) + '">';
    rows.forEach(function (row) {
      html += '<button type="button" class="kaist-' + attr + (row.id === current ? ' is-on' : '') + '" data-kaist-' + attr + '="' + esc(row.id) +
        '" aria-pressed="' + (row.id === current) + '">' + esc(row.label) + '</button>';
    });
    return html + '</div>';
  }
  function mukRender() {
    var focus = focusSelector(summary);
    var restos = restaurantsWithMenus(mukState.data);
    var stale = isStale(mukState.data, toKst());
    var title = stale && restos.length ? t('kaist.recentTitle', '최근에 올라온 KAIST 학식') : t('kaist.title', '오늘 KAIST 학식');
    var html = '<header class="kaist-head"><h2 id="kaistTitle">' + esc(title) + '</h2>';
    if (mukState.status === 'loading') {
      summary.innerHTML = html + '</header><p class="kaist-empty" role="status">' + esc(t('kaist.loading', '학식 메뉴를 불러오는 중이에요.')) + '</p>';
      return;
    }
    if (!restos.length) {
      var failed = mukState.status === 'error';
      html += '</header><p class="kaist-empty">' + esc(failed ? t('kaist.error', '학식 메뉴를 불러오지 못했어요.')
        : t('kaist.empty', '아직 올라온 학식 메뉴가 없어요.')) + '</p>';
    } else {
      var dateText = dateHeading(mukState.data.date) || mukState.data.dateLabel || '';
      html += '<p class="kaist-date' + (stale ? ' is-stale' : '') + '">' + esc(stale
        ? t('kaist.staleNote', '{date} 메뉴예요. 오늘 메뉴는 아직 올라오지 않았어요.').replace('{date}', dateText)
        : dateText) + '</p></header>';
      if (!restos.some(function (row) { return row.id === mukState.resto; })) mukState.resto = restos[0].id;
      var resto = restos.filter(function (row) { return row.id === mukState.resto; })[0];
      html += mukGroup(t('kaist.restosAria', '식당'), 'resto', restos.map(function (row) {
        return { id: row.id, label: row.name || row.id };
      }), mukState.resto);
      html += mukGroup(t('km.mealsAria', '식사 시간'), 'meal', MEALS.map(function (key) {
        return { id: key, label: mealLabel(key) };
      }), mukState.meal);
      var meal = resto[mukState.meal] || {};
      var items = mealItems(resto, mukState.meal);
      if (!items.length) {
        html += '<p class="kaist-empty">' + esc(t('kaist.nomenu', '이 시간대 메뉴가 없어요.')) + '</p>';
      } else {
        html += '<div class="kaist-card"><ul>';
        items.slice(0, 10).forEach(function (item) { html += '<li>' + esc(item) + '</li>'; });
        html += '</ul>';
        var meta = [meal.price, meal.kcal].filter(Boolean).join(' · ');
        if (meta) html += '<p class="kaist-meta">' + esc(meta) + '</p>';
        html += '</div>';
      }
    }
    html += '<p class="kaist-links"><a class="kaist-to-hub" href="ggongbab.html#menu">' + esc(t('kaist.toHub', '모든 식당 보기 →')) + '</a></p>';
    summary.innerHTML = html;
    restoreFocus(summary, focus);
  }
  summary.addEventListener('click', function (e) {
    var resto = e.target.closest && e.target.closest('[data-kaist-resto]');
    var meal = e.target.closest && e.target.closest('[data-kaist-meal]');
    if (resto) mukState.resto = resto.getAttribute('data-kaist-resto');
    if (meal && MEALS.indexOf(meal.getAttribute('data-kaist-meal')) >= 0) mukState.meal = meal.getAttribute('data-kaist-meal');
    if (resto || meal) mukRender();
  });
  document.addEventListener('babdoduk-lang', mukRender);
  mukRender();
  fetch('data/kaist-menu/latest.json', { cache: 'no-store' }).then(function (res) {
    if (!res.ok) throw new Error('missing');
    return res.json();
  }).then(function (data) {
    if (!data || !Array.isArray(data.restaurants)) throw new Error('bad');
    mukState.data = data;
    mukState.status = 'ready';
    mukRender();
  }).catch(function () {
    mukState.data = null;
    mukState.status = 'error';
    mukRender();
  });
})(window);
