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
  function isStale(data, today) {
    return !data || !data.date || data.date !== ymd(today);
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

  function attach(host, options) {
    options = options || {};
    var state = {
      status: 'loading',
      data: null,
      error: '',
      meal: readSavedMeal() || defaultMeal(toKst()),
      favorites: readFavorites(),
      expanded: {},
      showStale: false,
      host: host
    };
    function emit() {
      if (typeof options.onChange === 'function') options.onChange(snapshot());
    }
    function snapshot() {
      var today = toKst();
      var stale = isStale(state.data, today);
      return {
        status: state.status,
        stale: stale,
        meal: state.meal,
        restaurantCount: (!stale && state.data) ? restaurantsWithMenus(state.data).length : 0,
        data: state.data,
        error: state.error
      };
    }
    function visibleRestaurants() {
      var list = (state.data && state.data.restaurants) || [];
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
          esc(expanded ? t('km.collapse', '메뉴 접기 ↑') : t('km.expand', '전체 메뉴 ' + items.length + '개 보기 ↓').replace('{n}', String(items.length))) + '</button>';
      }
      if (meal.price || meal.kcal) {
        html += '<div class="km-meta">';
        if (meal.price) html += '<span class="km-price">' + esc(meal.price) + '</span>';
        if (meal.kcal) html += '<span class="km-kcal">' + esc(meal.kcal) + '</span>';
        html += '</div>';
      }
      return html + '</article>';
    }
    function emptyHtml(todayStale) {
      var html = '<div class="gg-state"><strong>' + esc(todayStale ? t('km.staleEmpty', '최근 메뉴를 보려면 아래를 눌러 주세요.') : t('km.emptyTitle', '오늘 이 시간대에 공개된 메뉴가 없어요.')) + '</strong>';
      MEALS.forEach(function (meal) {
        if (meal === state.meal) return;
        var n = ((state.data && state.data.restaurants) || []).filter(function (row) { return mealItems(row, meal).length; }).length;
        if (n) html += '<button type="button" class="km-cta is-ghost" data-km-meal="' + meal + '">' + esc(mealLabel(meal) + ' 메뉴 보기 →') + '</button>';
      });
      html += '<button type="button" class="km-cta is-ghost" data-hub-tab="free">' + esc(t('km.toFree', '꽁밥 보러가기 →')) + '</button>';
      return html + '</div>';
    }
    function render() {
      if (!state.host) return;
      var today = toKst();
      var html = '';
      if (state.status === 'loading') {
        html = '<div class="gg-skeleton"></div><div class="gg-skeleton"></div>';
      } else if (state.status === 'error') {
        html = '<div class="gg-state"><strong>' + esc(t('km.errorTitle', '오늘 메뉴를 불러오지 못했어요.')) + '</strong>' +
          esc(options.freeCountText || '') +
          '<br><button type="button" class="km-cta" data-km-retry>' + esc(t('gg.retry', '다시 시도')) + '</button>' +
          '<button type="button" class="km-cta is-ghost" data-hub-tab="free">' + esc(t('km.toFree', '꽁밥 보러가기 →')) + '</button></div>';
      } else {
        var stale = isStale(state.data, today);
        if (stale) {
          html += '<div class="km-warn" data-km-stale="1"><strong>' + esc(t('km.staleTitle', '오늘 메뉴 업데이트 중이에요.')) + '</strong><br>' +
            esc(t('km.staleSaved', '최근 저장된 메뉴:')) + ' ' + esc(dateHeading(state.data && state.data.date)) +
            '<br><button type="button" class="km-stale-toggle" data-km-stale-toggle>' +
            esc(state.showStale ? t('km.hideStale', '최근 메뉴 숨기기') : t('km.showStale', '최근 메뉴 보기')) + '</button></div>';
        }
        if (!stale || state.showStale) {
          var rows = visibleRestaurants();
          html += '<div class="km-head"><h2>' + esc(stale ? t('km.recentTitle', '최근 학식 메뉴') : t('km.title', '오늘의 학식')) + '</h2>';
          html += '<p class="km-date">' + esc(dateHeading(state.data && state.data.date) || (state.data && state.data.dateLabel) || '') + '</p>';
          html += '<p class="km-count">' + esc(mealLabel(state.meal) + ' 메뉴 ' + rows.length + '곳') + '</p></div>';
          html += '<div class="km-meals" role="group" aria-label="' + esc(t('km.mealsAria', '식사 시간')) + '">';
          MEALS.forEach(function (meal) {
            html += '<button type="button" class="km-meal" data-km-meal="' + meal + '" aria-pressed="' + (state.meal === meal) + '">' + esc(mealLabel(meal)) + '</button>';
          });
          html += '</div>';
          if (!rows.length) html += emptyHtml(stale);
          else {
            html += '<div class="km-grid">';
            rows.forEach(function (row) { html += cardHtml(row); });
            html += '</div>';
          }
        } else {
          html += '<div class="km-meals" role="group" aria-label="' + esc(t('km.mealsAria', '식사 시간')) + '">';
          MEALS.forEach(function (meal) {
            html += '<button type="button" class="km-meal" data-km-meal="' + meal + '" aria-pressed="' + (state.meal === meal) + '">' + esc(mealLabel(meal)) + '</button>';
          });
          html += '</div>';
          html += emptyHtml(true);
        }
      }
      state.host.innerHTML = html;
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
    function onClick(e) {
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
      if (e.target.closest && e.target.closest('[data-km-retry]')) {
        load();
      }
    }
    host.addEventListener('click', onClick);
    function mount(nextHost) {
      if (nextHost && nextHost !== state.host) {
        state.host.removeEventListener('click', onClick);
        state.host = nextHost;
        state.host.addEventListener('click', onClick);
      } else if (nextHost) state.host = nextHost;
      render();
    }
    load();
    return {
      mount: mount,
      reload: load,
      snapshot: snapshot,
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
    isStale: isStale,
    restaurantsWithMenus: restaurantsWithMenus
  };

  var mukbang = document.getElementById('kaistToday');
  if (!mukbang) return;
  var mukState = { data: null, resto: '', meal: 'lunch' };
  function mukMealNow() {
    var h = new Date().getHours();
    if (h < 10) return 'breakfast';
    if (h < 16) return 'lunch';
    return 'dinner';
  }
  function findResto() {
    var list = (mukState.data && mukState.data.restaurants) || [];
    return list.filter(function (row) { return row.id === mukState.resto; })[0] || list[0];
  }
  function mukRender() {
    if (!mukState.data) {
      mukbang.innerHTML = '<p class="kaist-empty">' + t('kaist.empty', '오늘 학식 정보를 아직 못 읽었어요.') + '</p>';
      return;
    }
    var restos = mukState.data.restaurants || [];
    if (!restos.length) {
      mukbang.innerHTML = '<p class="kaist-empty">' + t('kaist.empty', '오늘 학식 정보를 아직 못 읽었어요.') + '</p>';
      return;
    }
    if (!mukState.resto) mukState.resto = restos[0].id;
    var resto = findResto();
    var meal = (resto && resto[mukState.meal]) || {};
    var html = '<header class="kaist-head"><h2 id="kaistTitle">' + t('kaist.title', '오늘 KAIST에서 뭐 먹지?') + '</h2>';
    html += '<p class="kaist-date">' + (mukState.data.dateLabel || mukState.data.date || '') + '</p></header>';
    html += '<div class="kaist-restos" role="tablist">';
    restos.forEach(function (row) {
      html += '<button type="button" class="kaist-resto' + (row.id === mukState.resto ? ' is-on' : '') + '" data-kaist-resto="' + row.id + '">' + (row.name || row.id) + '</button>';
    });
    html += '</div><div class="kaist-meals">';
    MEALS.forEach(function (key) {
      html += '<button type="button" class="kaist-meal' + (mukState.meal === key ? ' is-on' : '') + '" data-kaist-meal="' + key + '">' + t('kaist.' + key, key) + '</button>';
    });
    html += '</div>';
    var items = meal.items || [];
    if (!items.length) {
      html += '<p class="kaist-empty">' + t('kaist.nomenu', '이 시간대 메뉴가 없어요.') + '</p>';
    } else {
      html += '<div class="kaist-card"><ul>';
      items.slice(0, 10).forEach(function (item) {
        html += '<li>' + String(item).replace(/[&<>]/g, function (ch) {
          return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[ch];
        }) + '</li>';
      });
      html += '</ul><p class="kaist-meta">';
      if (meal.price) html += meal.price + ' · ';
      if (meal.kcal) html += meal.kcal;
      html += '</p></div>';
    }
    html += '<a class="kaist-to-slot" href="#what">' + t('kaist.toSlot', '오늘 학식이 당기지 않는다면') + '</a>';
    mukbang.innerHTML = html;
  }
  mukbang.addEventListener('click', function (e) {
    var resto = e.target.closest && e.target.closest('[data-kaist-resto]');
    var meal = e.target.closest && e.target.closest('[data-kaist-meal]');
    if (resto) {
      mukState.resto = resto.getAttribute('data-kaist-resto');
      mukRender();
    }
    if (meal) {
      mukState.meal = meal.getAttribute('data-kaist-meal');
      mukRender();
    }
  });
  mukState.meal = mukMealNow();
  fetch('data/kaist-menu/latest.json', { cache: 'no-store' }).then(function (res) {
    if (!res.ok) throw new Error('missing');
    return res.json();
  }).then(function (data) {
    mukState.data = data;
    mukRender();
  }).catch(function () {
    mukState.data = null;
    mukRender();
  });
})(window);
