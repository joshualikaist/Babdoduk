/* 오늘 뭐 먹지 (choose.html, owner 2026-11-04: "메뉴 고르기 할때 그거를 우리 월드컵때 했던 뽑기 룰렛 같은거",
   "배달의 민족 앱 or 카이스트 학식에서 학생들이 고르도록 유도").

   First "어디서 먹을까?": 🍱 학식 (today's KAIST cafeteria meals that are not over yet), 🛵 배달 (kinds of
   delivery food, from the dish catalog's delivery dishes) or 🙈 아무거나 (the roulette picks one of the
   two first). Then the world cup's roulette: a light runs through the tiles, slowing down like a slot
   machine, and lands with a ding; a second tap lands it at once, reduced motion lands it straight away.
   A cafeteria tile opens its menu; a kind of delivery food spins the slot reel (js/eat-slot.js) to one
   dish of that kind. Any tile can also be picked by hand. (Opening a delivery app waits for the owner,
   2026-11-04: "이거는 나중에 구현".)

   Public helpers (tests, tests/test_pick.py): window.BabdodukPick.{CATEGORIES, categorize, servingMeals}. */
(function () {
  var MEALS = ['breakfast', 'lunch', 'dinner'];
  // When a cafeteria lists no hours: the usual KAIST windows.
  var MEAL_END = { breakfast: '09:30', lunch: '13:30', dinner: '19:00' };
  // Kinds of delivery food, as the delivery apps group them. A dish takes the first kind it fits, so the
  // specific kinds come before the broad ones (한식 last).
  var CATEGORIES = [
    { id: 'chicken', emoji: '🍗', test: function (f) {
      return (/치킨|닭강정|후라이드|양념통닭/.test(f.nameKo) && f.dishType !== 'sandwich' && f.dishType !== 'wrap' &&
        !/버거|반미|라이스|덮밥|샐러드/.test(f.nameKo)) || (f.mainProtein === 'chicken' && f.dishType === 'fried');
    } },
    { id: 'pizza', emoji: '🍕', test: function (f) { return f.dishType === 'pizza'; } },
    { id: 'burger', emoji: '🍔', test: function (f) { return /버거/.test(f.nameKo); } },
    { id: 'jokbal', emoji: '🐷', test: function (f) { return /족발|보쌈/.test(f.nameKo); } },
    { id: 'chinese', emoji: '🥟', test: function (f) { return f.cuisineGroup === 'chinese' || /짜장|짬뽕|탕수육|마라/.test(f.nameKo); } },
    { id: 'bunsik', emoji: '🍢', test: function (f) {
      return f.cuisineGroup === 'snack' || f.dishType === 'street' || /떡볶이|김밥|라면|순대|어묵/.test(f.nameKo);
    } },
    { id: 'japanese', emoji: '🍣', test: function (f) { return f.cuisineGroup === 'japanese'; } },
    { id: 'asian', emoji: '🍜', test: function (f) { return ['southeast-asian', 'indian', 'middle-eastern'].indexOf(f.cuisineGroup) >= 0; } },
    { id: 'western', emoji: '🍝', test: function (f) {
      return ['italian', 'american', 'mexican', 'fusion', 'western', 'french'].indexOf(f.cuisineGroup) >= 0;
    } },
    { id: 'korean', emoji: '🍚', test: function (f) { return f.cuisineGroup === 'korean'; } },
  ];

  // Delivery dishes by kind; a kind with fewer than three dishes is left out.
  function categorize(foods) {
    var out = {};
    CATEGORIES.forEach(function (c) { out[c.id] = []; });
    (foods || []).forEach(function (f) {
      if (!f || (f.diningMode || []).indexOf('delivery') < 0 || f.category === 'dessert' || f.category === 'drink') return;
      for (var i = 0; i < CATEGORIES.length; i++) {
        if (CATEGORIES[i].test(f)) { out[CATEGORIES[i].id].push(f); return; }
      }
    });
    Object.keys(out).forEach(function (id) { if (out[id].length < 3) delete out[id]; });
    return out;
  }

  function minutes(hhmm) {
    var m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || '').trim());
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }
  // The cafeteria meals of `data` (a kaist-menu day) still being served at `now` (minutes after KST
  // midnight): ones whose listed end, or the usual one, is still ahead. Only the Daejeon main campus
  // (a building code such as N11 or E5): 문지, 화암 and Seoul are other campuses.
  var MAIN_CAMPUS = /^[EWNS]\d/;
  function servingMeals(data, nowMinutes) {
    var out = [];
    ((data && data.restaurants) || []).forEach(function (resto) {
      if (!MAIN_CAMPUS.test(String(resto.building || ''))) return;
      MEALS.forEach(function (meal) {
        var m = resto[meal];
        if (!m || !Array.isArray(m.items) || !m.items.length) return;
        var hours = String(m.hours || '');
        var end = minutes((hours.split(/[~\-–]/)[1] || '').trim());
        if (end == null) end = minutes(MEAL_END[meal]);
        if (end > nowMinutes) out.push({ resto: resto, meal: meal, info: m });
      });
    });
    return out;
  }

  // A menu line as a person reads it: allergen numbers "(5,6,10)" and the calorie line go.
  function cleanItems(items) {
    return (items || []).map(function (item) { return String(item).replace(/\s*\([\d,*\s]+\)\s*$/, '').trim(); })
      .filter(function (item) { return item && !/^\[?\s*칼로리/.test(item) && !/kcal\]?$/i.test(item); });
  }

  window.BabdodukPick = { CATEGORIES: CATEGORIES, categorize: categorize, servingMeals: servingMeals, cleanItems: cleanItems };

  var app = document.getElementById('pickApp');
  if (!app) return;
  var Foods = window.BabdodukFoods, Slot = window.BabdodukSlot, Menu = window.BabdodukKaistMenu;
  var els = {
    modes: document.getElementById('pickModes'),
    board: document.getElementById('pickBoard'),
    tiles: document.getElementById('pickTiles'),
    boardTitle: document.getElementById('pickBoardTitle'),
    result: document.getElementById('pickResult'),
    status: document.getElementById('pickStatus'),
    sound: document.getElementById('pickSound'),
  };
  var state = { mode: '', tiles: [], spin: null, cafeteria: null, menuState: 'loading', kinds: null, foodsState: 'loading',
                slot: null, landed: null, dish: null };

  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function t(key, fallback) {
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang()];
    return pack && pack[key] != null ? pack[key] : fallback;
  }
  function fill(s, v) { return String(s).replace(/\{(\w+)\}/g, function (a, k) { return v[k] != null ? v[k] : a; }); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function moving() { return !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
  function kstNow() {
    var d = new Date(Date.now() + 9 * 3600 * 1000);
    return { iso: d.toISOString().slice(0, 10), minutes: d.getUTCHours() * 60 + d.getUTCMinutes() };
  }
  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); });
  }
  function dishName(f) { return lang() === 'en' ? (f.nameEn || f.nameKo) : f.nameKo; }

  // ---- sound: a tick per step and a ding on landing, off until a person turns it on ----------------
  var sound = (function () {
    var ctx = null, on = false;
    try { on = localStorage.getItem('babdoduk-pick-sound') === 'on'; } catch (e) {}
    function tone(freq, at, len, gain) {
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'triangle';
      o.frequency.value = freq;
      g.gain.setValueAtTime(gain, at);
      g.gain.exponentialRampToValueAtTime(0.0001, at + len);
      o.connect(g).connect(ctx.destination);
      o.start(at);
      o.stop(at + len + 0.02);
    }
    return {
      on: function () { return on; },
      toggle: function () {
        on = !on;
        try { localStorage.setItem('babdoduk-pick-sound', on ? 'on' : 'off'); } catch (e) {}
        return on;
      },
      fx: function (name) {
        if (!on) return;
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        ctx = ctx || new AC();
        var now = ctx.currentTime;
        if (name === 'tick') tone(1650, now, 0.04, 0.05);
        else { tone(880, now, 0.18, 0.09); tone(1320, now + 0.09, 0.32, 0.08); }
      },
    };
  })();
  function paintSound() {
    els.sound.setAttribute('aria-pressed', String(sound.on()));
    els.sound.querySelector('[data-pick-sound-icon]').textContent = sound.on() ? '🔊' : '🔈';
  }

  // ---- data ------------------------------------------------------------------------------------------
  var menuReady = (Menu && Menu.loadTodayMenu ? Menu.loadTodayMenu(getJson) : getJson('data/kaist-menu/latest.json'))
    .then(function (data) {
      state.cafeteria = data;
      state.menuState = 'ready';
    }, function () { state.menuState = 'error'; });
  var foodsReady = (Foods && Foods.load ? Foods.load() : Promise.reject(new Error('no catalog')))
    .then(function (foods) {
      state.kinds = categorize(foods);
      state.foodsState = 'ready';
    }, function () { state.foodsState = 'error'; });

  function cafeteriaTiles() {
    var now = kstNow();
    if (!state.cafeteria || state.cafeteria.date !== now.iso) return [];
    return servingMeals(state.cafeteria, now.minutes).map(function (s) {
      return { id: s.resto.id + ':' + s.meal, emoji: '🍱', label: s.resto.name,
               sub: t('pick.meal.' + s.meal, { breakfast: '아침', lunch: '점심', dinner: '저녁' }[s.meal]), serving: s };
    });
  }
  function deliveryTiles() {
    return CATEGORIES.filter(function (c) { return state.kinds && state.kinds[c.id]; }).map(function (c) {
      return { id: c.id, emoji: c.emoji, label: t('pick.cat.' + c.id, c.id), sub: '', kind: c.id };
    });
  }
  function modeTiles() {
    return [{ id: 'cafeteria', emoji: '🍱', label: t('pick.mode.cafeteria', '학식'), sub: '' },
            { id: 'delivery', emoji: '🛵', label: t('pick.mode.delivery', '배달'), sub: '' }];
  }

  // ---- the board -----------------------------------------------------------------------------------------
  function renderBoard(title, tiles) {
    state.tiles = tiles;
    els.board.hidden = false;
    els.boardTitle.textContent = title;
    els.tiles.innerHTML = tiles.map(function (tile) {
      return '<li><button type="button" class="pick-tile" data-tile="' + esc(tile.id) + '">' +
        '<span class="pick-tile-emoji" aria-hidden="true">' + tile.emoji + '</span>' +
        '<span class="pick-tile-label">' + esc(tile.label) + '</span>' +
        (tile.sub ? '<span class="pick-tile-sub">' + esc(tile.sub) + '</span>' : '') + '</button></li>';
    }).join('');
  }
  // The world cup's 아무거나 (js/worldcup.js spinTiles): a full lap and on to the target, slowing down.
  function spin(onLand) {
    stopSpin(false);
    var count = state.tiles.length;
    if (!count) return;
    var target = Math.floor(Math.random() * count);
    if (!moving()) { land(target, onLand); return; }
    var steps = count * (count < 4 ? 3 : 1) + target, i = 0, lit = null;
    state.spin = { target: target, timer: 0, onLand: onLand };
    els.tiles.classList.add('is-spinning');
    (function step() {
      if (!state.spin) return;
      if (lit) lit.classList.remove('is-spin');
      lit = els.tiles.querySelectorAll('.pick-tile')[i % count];
      lit.classList.add('is-spin');
      sound.fx('tick');
      i++;
      state.spin.timer = i > steps ? setTimeout(function () { stopSpin(true); }, 240)
        : setTimeout(step, 45 + 230 * Math.pow(i / steps, 2.4));
    })();
  }
  function stopSpin(landIt) {
    if (!state.spin) return;
    var s = state.spin;
    state.spin = null;
    clearTimeout(s.timer);
    els.tiles.classList.remove('is-spinning');
    [].forEach.call(els.tiles.querySelectorAll('.is-spin'), function (tile) { tile.classList.remove('is-spin'); });
    if (landIt) land(s.target, s.onLand);
  }
  function land(index, onLand) {
    var tile = state.tiles[index];
    var button = els.tiles.querySelectorAll('.pick-tile')[index];
    [].forEach.call(els.tiles.querySelectorAll('.is-landed'), function (b) { b.classList.remove('is-landed'); });
    if (button) {
      button.classList.add('is-landed');
      if (moving()) button.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.08)' }, { transform: 'scale(1)' }],
        { duration: 420, easing: 'cubic-bezier(.34,1.56,.64,1)' });
    }
    sound.fx('ding');
    els.status.textContent = fill(t('pick.landed', '{name} 당첨!'), { name: tile.label + (tile.sub ? ' ' + tile.sub : '') });
    onLand(tile);
  }

  // ---- modes ---------------------------------------------------------------------------------------------
  function choose(mode) {
    stopSpin(false);
    state.mode = mode;
    [].forEach.call(els.modes.querySelectorAll('[data-mode]'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-mode') === mode));
    });
    els.result.hidden = true;
    if (mode === 'any') {
      renderBoard(t('pick.board.any', '학식일까, 배달일까?'), modeTiles());
      spin(function (tile) { setTimeout(function () { start(tile.id, true); }, moving() ? 650 : 0); });
      return;
    }
    start(mode, false);
  }
  function start(mode, fromAny) {
    var ready = mode === 'cafeteria' ? menuReady : foodsReady;
    els.boardTitle.textContent = t('pick.loading', '메뉴 불러오는 중');
    ready.then(function () {
      if (state.mode !== mode && !(fromAny && state.mode === 'any')) return;
      var tiles = mode === 'cafeteria' ? cafeteriaTiles() : deliveryTiles();
      if (!tiles.length) {
        if (mode === 'cafeteria') return empty(t('pick.noMenu', '지금 먹을 수 있는 학식이 없어요. 배달은 어때요?'), 'delivery');
        return empty(t('pick.error', '메뉴를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.'), '');
      }
      renderBoard(mode === 'cafeteria' ? t('pick.board.cafeteria', '오늘 학식, 어디로 갈까?')
        : t('pick.board.delivery', '오늘은 뭘 시켜 먹을까?'), tiles);
      spin(mode === 'cafeteria' ? showMeal : showKind);
    });
  }
  function empty(text, next) {
    els.board.hidden = false;
    els.boardTitle.textContent = text;
    els.tiles.innerHTML = next ? '<li><button type="button" class="pick-tile" data-switch="' + next + '"><span class="pick-tile-emoji" aria-hidden="true">🛵</span>' +
      '<span class="pick-tile-label">' + esc(t('pick.mode.delivery', '배달')) + '</span></button></li>' : '';
    state.tiles = [];
    els.status.textContent = text;
  }

  // ---- results -------------------------------------------------------------------------------------------
  function actions(html) {
    return '<div class="pick-actions">' + html +
      '<button type="button" class="pick-btn" data-pick="again">' + esc(t('pick.again', '다시 돌리기')) + '</button>' +
      '<button type="button" class="pick-btn pick-btn--quiet" data-pick="restart">' + esc(t('pick.restart', '처음부터')) + '</button></div>';
  }
  function showMeal(tile) {
    var s = tile.serving, info = s.info;
    var rows = [];
    if (info.hours) rows.push('<li><span>' + esc(t('pick.hours', '시간')) + '</span> ' + esc(info.hours) + '</li>');
    if (info.price) rows.push('<li><span>' + esc(t('pick.price', '가격')) + '</span> ' + esc(info.price) + '</li>');
    if (info.kcal) rows.push('<li><span>' + esc(t('pick.kcal', '열량')) + '</span> ' + esc(info.kcal) + '</li>');
    if (s.resto.building) rows.push('<li><span>' + esc(t('pick.building', '건물')) + '</span> ' + esc(s.resto.building) + '</li>');
    els.result.innerHTML = '<p class="pick-result-kicker">🍱 ' + esc(tile.sub) + '</p>' +
      '<h2 class="pick-result-title" tabindex="-1">' + esc(s.resto.name) + '</h2>' +
      '<ul class="pick-menu">' + cleanItems(info.items).slice(0, 8).map(function (item) { return '<li>' + esc(item) + '</li>'; }).join('') + '</ul>' +
      (rows.length ? '<ul class="pick-facts">' + rows.join('') + '</ul>' : '') +
      actions('<a class="pick-btn pick-btn--main" href="ggongbab.html#menu">' + esc(t('pick.toMenu', '학식 전체 보기')) + ' →</a>');
    reveal();
  }
  function showKind(tile) {
    var foods = state.kinds[tile.kind].slice();
    var weights = foods.map(function (f) { return Math.max(1, Number(f.popularity) || 3); });
    var total = weights.reduce(function (a, b) { return a + b; }, 0), r = Math.random() * total, dish = foods[0];
    for (var i = 0; i < foods.length; i++) { r -= weights[i]; if (r <= 0) { dish = foods[i]; break; } }
    state.dish = dish;
    els.result.innerHTML = '<p class="pick-result-kicker">' + tile.emoji + ' ' + esc(tile.label) + '</p>' +
      '<div class="pick-reel" id="pickReel"></div>' +
      '<h2 class="pick-result-title" tabindex="-1" hidden></h2>' +
      '<div class="pick-after" hidden></div>';
    els.result.hidden = false;
    if (state.slot) state.slot.destroy();
    state.slot = Slot ? Slot.create({ host: document.getElementById('pickReel'), foods: foods.slice(0, 24), reducedMotion: !moving(),
      aria: t('pick.reelAria', '메뉴를 뽑는 슬롯'), onSettle: function () { dishLanded(tile); } }) : null;
    if (state.slot) state.slot.spin(dish, foods.slice(0, 24));
    else dishLanded(tile);
  }
  function dishLanded(tile) {
    var dish = state.dish;
    var title = els.result.querySelector('.pick-result-title');
    title.textContent = dishName(dish);
    title.hidden = false;
    var after = els.result.querySelector('.pick-after');
    after.innerHTML = '<p class="pick-note">' + esc(t('pick.shopNote', '가게와 가격은 배달앱에서 골라요.')) + '</p>' +
      actions('<button type="button" class="pick-btn pick-btn--main" data-pick="kind">' + esc(t('pick.otherDish', '같은 종류로 다시')) + '</button>');
    after.hidden = false;
    els.status.textContent = fill(t('pick.dishLanded', '오늘은 {name}!'), { name: dishName(dish) });
    sound.fx('ding');
    title.focus({ preventScroll: true });
  }
  function reveal() {
    els.result.hidden = false;
    var title = els.result.querySelector('.pick-result-title');
    title.focus({ preventScroll: true });
    els.result.scrollIntoView({ block: 'nearest', behavior: moving() ? 'smooth' : 'auto' });
  }
  // ---- events --------------------------------------------------------------------------------------------
  app.addEventListener('click', function (e) {
    var mode = e.target.closest('[data-mode]');
    if (mode) return choose(mode.getAttribute('data-mode'));
    var sw = e.target.closest('[data-switch]');
    if (sw) return choose(sw.getAttribute('data-switch'));
    var tileButton = e.target.closest('.pick-tile[data-tile]');
    if (tileButton) {
      if (state.spin) return stopSpin(true);               // a second tap lands it at once
      var index = state.tiles.findIndex(function (x) { return x.id === tileButton.getAttribute('data-tile'); });
      if (index < 0) return;
      if (state.mode === 'any' && (state.tiles[index].id === 'cafeteria' || state.tiles[index].id === 'delivery')) {
        land(index, function (tile) { start(tile.id, true); });
        return;
      }
      land(index, state.mode === 'cafeteria' || (state.mode === 'any' && state.tiles[index].serving) ? showMeal : showKind);
      return;
    }
    var act = e.target.closest('[data-pick]');
    if (!act) return;
    var what = act.getAttribute('data-pick');
    if (what === 'again') choose(state.mode);
    else if (what === 'restart') {
      stopSpin(false);
      state.mode = '';
      els.board.hidden = true;
      els.result.hidden = true;
      [].forEach.call(els.modes.querySelectorAll('[data-mode]'), function (b) { b.setAttribute('aria-pressed', 'false'); });
      els.modes.querySelector('[data-mode]').focus();
    } else if (what === 'kind') {
      var landed = els.tiles.querySelector('.is-landed');
      var tile = landed && state.tiles.find(function (x) { return x.id === landed.getAttribute('data-tile'); });
      if (tile && tile.kind) showKind(tile);
    }
  });
  els.sound.addEventListener('click', function () { sound.toggle(); paintSound(); });
  paintSound();
})();
