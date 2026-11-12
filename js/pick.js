/* 오늘 뭐 먹지 (choose.html). Owner 2026-11-05: the slot roulette and its three steps are gone ("이 룰렛은
   폐기해줘", "사람들이 선택하는거 귀찮으니까 룰렛 돌리는거 아니야"); in their place the world cup's capsule
   machine ("월드컵 때 썼던 … 그거", js/worldcup.js showGacha), one button and no choices.

   메뉴 뽑기: the machine cranks three times while its screen runs through food, squashes, and drops one
   capsule that flies up and pops open on the pick; the card under the button names it. The pick is a
   KAIST cafeteria meal still being served today, a campus restaurant menu transcribed from photos, or a
   popular delivery dish (MIN_POPULARITY). While a cafeteria meal is being served, about four draws in ten are one. A
   press during a draw lands it at once; reduced motion, forced colours or no Web Animations show the
   pick straight away. Only transform and opacity move. (Opening a delivery app waits for the owner,
   2026-11-04: "이거는 나중에 구현".)

   Public helpers (tests/test_pick.py): window.BabdodukPick.{CATEGORIES, categorize, servingMeals,
   cleanItems, kindOf, draw}. */
(function () {
  var MEALS = ['breakfast', 'lunch', 'dinner'];
  // When a cafeteria lists no hours: the usual KAIST windows.
  var MEAL_END = { breakfast: '09:30', lunch: '13:30', dinner: '19:00' };
  // Owner 2026-11-10: cafeteria meals and campus restaurants together take 7 draws in 10, delivery 3.
  // While a cafeteria meal is being served, it takes 2 of the 10 draws and the campus restaurants 5
  // (owner 2026-11-10: 학식 2, 교내 식당 5, 배달 3); with no meal served, the campus restaurants take all 7.
  var LOCAL_SHARE = 0.7;
  var CAFETERIA_SHARE = 0.2;
  // Only dishes the catalog rates 4 or 5 for popularity: the delivery-app staples (치킨, 짜장면, 떡볶이,
  // 마라탕 …). Owner 2026-11-05: "배달음식이 너무나도 한국 정서와 조금 다른 것 같다"; at 3 and below the
  // pool was 354 dishes such as 루면 or 비앙비앙면 and drew four times in five. scripts/page_content.py
  // pick_photo_blocks carries the photo credits of the same dishes.
  var MIN_POPULARITY = 4;
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

  // The kind of a delivery dish, or null (not delivered, a dessert or a drink, or no kind fits).
  function kindOf(f) {
    if (!f || (f.diningMode || []).indexOf('delivery') < 0 || f.category === 'dessert' || f.category === 'drink') return null;
    for (var i = 0; i < CATEGORIES.length; i++) {
      if (CATEGORIES[i].test(f)) return CATEGORIES[i];
    }
    return null;
  }
  // Delivery dishes by kind; a kind with fewer than three dishes is left out.
  function categorize(foods) {
    var out = {};
    CATEGORIES.forEach(function (c) { out[c.id] = []; });
    (foods || []).forEach(function (f) {
      var kind = kindOf(f);
      if (kind) out[kind.id].push(f);
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

  // Everyone's taste (owner 2026-11-05, 방법 A; supabase/migrations/010_pick_stats.sql, docs/PICK_STATS.md):
  // a dish's weight is its popularity times taste(likes, rerolls). With no votes it is 1; it rises
  // towards 2 as people press 👍 이거 먹을래요 and falls towards 0 as they draw again past the dish.
  // The +2/+4 is a prior of two likes and two rerolls, so a few votes move it only a little.
  function taste(likes, rerolls) {
    likes = Math.max(0, Number(likes) || 0);
    rerolls = Math.max(0, Number(rerolls) || 0);
    return 2 * (likes + 2) / (likes + rerolls + 4);
  }
  // A daily cafeteria meal, a photographed campus restaurant menu, or a delivery dish.
  // On campus (cafeteria or campus restaurant) LOCAL_SHARE of the time, else delivery; when one side
  // has nothing to draw, the other side takes every draw. Delivery weights and taste stay unchanged.
  function draw(meals, dishes, rand, votes, campus) {
    rand = rand || Math.random;
    meals = meals || [];
    dishes = dishes || [];
    votes = votes || {};
    campus = campus || [];
    if ((meals.length || campus.length) && (!dishes.length || rand() < LOCAL_SHARE)) {
      if (meals.length && (!campus.length || rand() < CAFETERIA_SHARE / LOCAL_SHARE)) {
        return { meal: meals[Math.floor(rand() * meals.length)] };
      }
      // Select a store first so larger menus do not drown out smaller restaurants.
      var stores = Array.from(new Set(campus.map(function (item) { return item.store; })));
      var store = stores[Math.floor(rand() * stores.length)];
      var choices = campus.filter(function (item) { return item.store === store; });
      return { campus: choices[Math.floor(rand() * choices.length)] };
    }
    if (!dishes.length) return null;
    var weights = dishes.map(function (f) {
      var v = votes[f.id] || {};
      return Math.max(1, Number(f.popularity) || 3) * taste(v.likes, v.rerolls);
    });
    var total = weights.reduce(function (a, b) { return a + b; }, 0), r = rand() * total;
    for (var i = 0; i < dishes.length; i++) { r -= weights[i]; if (r < 0) return { dish: dishes[i] }; }
    return { dish: dishes[dishes.length - 1] };
  }

  window.BabdodukPick = { CATEGORIES: CATEGORIES, categorize: categorize, servingMeals: servingMeals,
    cleanItems: cleanItems, kindOf: kindOf, draw: draw, taste: taste, MIN_POPULARITY: MIN_POPULARITY };

  var app = document.getElementById('pickApp');
  if (!app) return;
  var Foods = window.BabdodukFoods, Menu = window.BabdodukKaistMenu;
  var els = {
    stage: document.getElementById('pickStage'),
    machine: document.getElementById('pickMachine'),
    go: document.getElementById('pickGo'),
    goLabel: document.getElementById('pickGoLabel'),
    result: document.getElementById('pickResult'),
    status: document.getElementById('pickStatus'),
    sound: document.getElementById('pickSound'),
  };
  var state = { cafeteria: null, dishes: null, campus: [], run: null, drawn: 0, last: null, votes: {} };

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
  function safeHref(url) {
    if (!url) return '';
    try {
      var u = new URL(url, location.href);
      return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : '';
    } catch (e) { return ''; }
  }
  var reducedQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var forcedQuery = window.matchMedia ? window.matchMedia('(forced-colors: active)') : null;
  function canAnimate() {
    return !(reducedQuery && reducedQuery.matches) && !(forcedQuery && forcedQuery.matches) && !document.hidden &&
      typeof els.stage.animate === 'function';
  }
  function kstNow() {
    var d = new Date(Date.now() + 9 * 3600 * 1000);
    return { iso: d.toISOString().slice(0, 10), minutes: d.getUTCHours() * 60 + d.getUTCMinutes() };
  }
  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); });
  }
  function dishName(f) { return lang() === 'en' ? (f.nameEn || f.nameKo) : f.nameKo; }
  function mealName(meal) { return t('pick.meal.' + meal, { breakfast: '아침', lunch: '점심', dinner: '저녁' }[meal]); }

  // ---- sound: a click per turn of the crank and a ding when the capsule opens, off until turned on ----
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
      fx: function (name, delay) {
        if (!on) return;
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        ctx = ctx || new AC();
        var at = ctx.currentTime + (delay || 0) / 1000;
        if (name === 'tick') tone(1650, at, 0.04, 0.05);
        else { tone(880, at, 0.18, 0.09); tone(1320, at + 0.09, 0.32, 0.08); }
      },
    };
  })();
  function paintSound() {
    els.sound.setAttribute('aria-pressed', String(sound.on()));
    els.sound.querySelector('[data-pick-sound-icon]').textContent = sound.on() ? '🔊' : '🔈';
  }

  // ---- data ------------------------------------------------------------------------------------------
  var menuReady = (Menu && Menu.loadTodayMenu ? Menu.loadTodayMenu(getJson) : getJson('data/kaist-menu/latest.json'))
    .then(function (data) { state.cafeteria = data; }, function () {});
  var campusReady = getJson('data/foods/campus-kiosk.json').then(function (data) {
    state.campus = data && Array.isArray(data.items) ? data.items.filter(function (item) {
      return item && item.drawable === true && typeof item.store === 'string' && item.store &&
        typeof item.name === 'string' && item.name;
    }) : [];
  }, function () { state.campus = []; });
  // The world cup's photos with their credits (js/pick-photos.js, written from data/content/worldcup.json):
  // only photographed dishes are drawn, each capsule opening on its photo. Without them every delivery
  // dish stays in, on its kind's emoji.
  var PHOTOS = window.BABDODUK_PICK_PHOTOS || { links: [], photos: {} };
  function photoOf(id) {
    var p = PHOTOS.photos[id];
    return p ? { author: p[0], license: p[1], source: p[2], licenseUrl: PHOTOS.links[p[3]] || '',
                 thumb: 'images/worldcup/thumb/' + id } : null;
  }
  var foodsReady = (Foods && Foods.load ? Foods.load() : Promise.reject(new Error('no catalog'))).then(function (foods) {
    var all = foods.filter(function (f) { return kindOf(f) && Number(f.popularity) >= MIN_POPULARITY; });
    var shot = all.filter(function (f) { return photoOf(f.id); });
    state.dishes = shot.length >= 20 ? shot : all;
  }, function () { state.dishes = []; });

  // ---- everyone's taste: read the counts, send one signal at a time ----------------------------------
  // Only with the browser-public project values (js/ggongbab-public-config.js, lab); without them, or
  // when the server fails, the page draws by popularity alone and shows no 👍 button.
  var statsApi = (function () {
    var c = window.BABDODUK_PUBLIC_FEED_CONFIG;
    try {
      var url = new URL(c.SUPABASE_URL), key = c.SUPABASE_PUBLISHABLE_KEY;
      if (url.protocol !== 'https:' || url.pathname !== '/' || url.search || url.hash || url.username) return null;
      if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) return null;
      return { base: url.origin + '/rest/v1/', key: key };
    } catch (e) { return null; }
  })();
  function api(path, body) {
    var headers = { apikey: statsApi.key, Authorization: 'Bearer ' + statsApi.key, Accept: 'application/json' };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(statsApi.base + path, { method: body ? 'POST' : 'GET', headers: headers,
                                         body: body ? JSON.stringify(body) : undefined, cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('unavailable');
        return r.status === 204 ? null : r.json();
      });
  }
  if (statsApi) {
    api('pick_dish_stats?select=dish_id,likes,rerolls').then(function (rows) {
      (rows || []).forEach(function (row) {
        if (row && typeof row.dish_id === 'string') state.votes[row.dish_id] = { likes: Number(row.likes) || 0, rerolls: Number(row.rerolls) || 0 };
      });
    }, function () {});
  }
  // 'draw', 'like' or 'reroll' for a delivery dish; nothing else is ever sent.
  function record(signal, dish) {
    if (!statsApi || !dish) return;
    api('rpc/pick_record', { p_dish: dish.id, p_signal: signal }).catch(function () {});
  }

  function servingNow() {
    var now = kstNow();
    if (!state.cafeteria || state.cafeteria.date !== now.iso) return [];
    return servingMeals(state.cafeteria, now.minutes);
  }

  // ---- the machine -----------------------------------------------------------------------------------
  var EASE = { out: 'cubic-bezier(0, 0, 0.15, 1)', io: 'cubic-bezier(0.35, 0, 0.35, 1)',
               bouncy: 'cubic-bezier(0.34, 1.56, 0.64, 1)', arc: 'cubic-bezier(0.2, 0.6, 0.35, 1)' };
  var SHELLS = ['#ec4899', '#06b6d4', '#a855f7', '#fde047', '#6366f1'];
  var SCREEN = ['🍗', '🍕', '🍔', '🍱', '🍜', '🍣', '🥟', '🍝', '🍢', '🍚'];
  var CRANK = 260, CRANKS = 3;
  function node(tag, cls, parent) {
    var el = document.createElement(tag);
    el.className = cls;
    if (parent) parent.appendChild(el);
    return el;
  }
  function pose(x, y, r, sx, sy) {
    sx = sx == null ? 1 : sx;
    return 'translate(' + x + 'px, ' + y + 'px) rotate(' + (r || 0) + 'deg) scale(' + sx + ', ' + (sy == null ? sx : sy) + ')';
  }
  // One element's part as [ms, keyframe, easing onward] steps: a single animation, filled both ways.
  function track(run, el, steps) {
    var from = steps[0][0], span = steps[steps.length - 1][0] - from;
    var frames = steps.map(function (step) {
      var frame = { offset: (step[0] - from) / span };
      for (var k in step[1]) frame[k] = step[1][k];
      if (step[2]) frame.easing = step[2];
      return frame;
    });
    var a = el.animate(frames, { delay: from, duration: span, fill: 'both' });
    run.anims.push(a);
    return a;
  }
  function q(sel) { return els.machine.querySelector(sel); }
  function pickEmoji(pick) { return pick.meal ? '🍱' : pick.campus ? '🍽️' : pick.kind.emoji; }

  // The capsule of a pick: its face (the photo or an emoji) under half a coloured shell.
  function capsule(pick) {
    var cap = node('div', 'pk-cap', els.stage), y = node('div', 'pk-cap-y', cap), face = node('div', 'pk-cap-face', y);
    var photo = pick.dish && photoOf(pick.dish.id);
    if (photo) {
      var img = node('img', '', face);
      img.alt = '';
      img.decoding = 'async';
      img.width = 128;
      img.height = 128;
      img.sizes = '128px';
      img.srcset = photo.thumb + '-160.webp 160w, ' + photo.thumb + '-320.webp 320w';
      img.src = photo.thumb + '-320.webp';
    } else {
      face.textContent = pickEmoji(pick);
    }
    node('i', 'pk-cap-shell', y).style.setProperty('--c', SHELLS[state.drawn % SHELLS.length]);
    return cap;
  }

  function clearStage() {
    if (state.run) state.run.anims.forEach(function (a) { a.cancel(); });
    state.run = null;
    [].forEach.call(els.stage.querySelectorAll('.pk-cap'), function (c) { c.remove(); });
    els.stage.classList.remove('is-done');
  }

  function play(pick) {
    clearStage();
    state.drawn++;
    var cap = capsule(pick);
    var finalEmoji = pickEmoji(pick);
    var strip = SCREEN.filter(function (e) { return e !== finalEmoji; }).slice(0, 7).concat([finalEmoji]);
    q('.pk-strip').textContent = strip.join('\n');
    if (!canAnimate()) { finish(pick); return; }

    var run = { anims: [], pick: pick, done: false };
    state.run = run;
    els.go.setAttribute('aria-busy', 'true');
    els.goLabel.textContent = t('pick.drawing', '뽑는 중…');
    var tP = CRANKS * CRANK, from = tP + 80, tOpen = from + 640, tEnd = tOpen + 300;
    // 가샤: each turn of the crank jiggles the balls, shakes the body and makes the machine squint.
    var crank = [], shake = [], eyes = [], balls = [[], [], [], [], [], [], []];
    for (var c = 0; c < CRANKS; c++) {
      var at = c * CRANK, amp = [0.6, 0.8, 1][c];
      crank.push([at, { transform: 'rotate(' + c * 180 + 'deg)' }, EASE.io], [at + 200, { transform: 'rotate(' + (c + 1) * 180 + 'deg)' }]);
      [0, 3, -3, 2, -1, 0].forEach(function (x, i) { shake.push([at + i * 48, { transform: 'translateX(' + x * amp + 'px)' }]); });
      eyes.push([at, { transform: 'scaleY(1)' }], [at + 88, { transform: 'scaleY(0.25)' }], [at + 220, { transform: 'scaleY(1)' }]);
      balls.forEach(function (steps, i) {
        var d = (i % 2 ? 1 : -1) * amp, b = at + i * 10;
        steps.push([b, { transform: 'none' }, 'ease-in-out'], [b + 60, { transform: pose(7 * d, -6 * amp, 14 * d) }, 'ease-in-out'],
                   [b + 120, { transform: pose(-5 * d, 3 * amp, -10 * d) }, 'ease-in-out'],
                   [b + 180, { transform: pose(3 * d, -2 * amp, 5 * d) }, 'ease-in-out'], [b + 240, { transform: 'none' }]);
      });
      sound.fx('tick', at + 100);
    }
    track(run, q('.pk-crank'), crank);
    track(run, q('.pk-body'), shake);
    [].forEach.call(els.machine.querySelectorAll('.pk-eye'), function (eye) { track(run, eye, eyes); });
    [].forEach.call(els.machine.querySelectorAll('.pk-ball'), function (ball, i) { track(run, ball, balls[i]); });
    track(run, q('.pk-strip'), [[0, { transform: 'translateY(0px)' }, 'steps(' + (strip.length - 1) + ', end)'],
                                [tP, { transform: 'translateY(' + -(strip.length - 1) * 38 + 'px)' }]]);
    track(run, q('.pk-screen'), [[tP, { transform: 'scale(1)' }, EASE.out], [tP + 96, { transform: 'scale(1.25)' }],
                                 [tP + 320, { transform: 'scale(1)' }]]);
    // 퐁: the machine squashes as the mouth opens, then steps back when the capsule opens.
    track(run, els.machine, [[tP, { transform: pose(0, 0), opacity: 1 }, 'ease-in'], [tP + 110, { transform: pose(0, 0, 0, 1.08, 0.88), opacity: 1 }],
                             [tP + 144, { transform: pose(0, 0, 0, 0.94, 1.1), opacity: 1 }, EASE.bouncy], [tP + 480, { transform: pose(0, 0), opacity: 1 }],
                             [tOpen, { transform: pose(0, 0), opacity: 1 }, EASE.io], [tEnd, { transform: pose(0, 0), opacity: 0.32 }]]);
    track(run, q('.pk-mouth'), [[tP, { transform: 'scaleY(1)' }], [tP + 76, { transform: 'scaleY(1.35)' }],
                                [tP + 560, { transform: 'scaleY(1.35)' }], [tP + 640, { transform: 'scaleY(1)' }]]);
    // The capsule: out of the mouth, up in an arc to its place above the machine, a bounce, then its
    // shell flies off. Measured once; it moves from the mouth to its own CSS place.
    var mouth = q('.pk-mouth').getBoundingClientRect(), home = cap.getBoundingClientRect();
    var dx = mouth.left + mouth.width / 2 - (home.left + home.width / 2);
    var dy = mouth.top + mouth.height / 2 - (home.top + home.height / 2);
    var small = 0.36, turn = state.drawn % 2 ? 360 : -360;
    track(run, cap, [[from, { opacity: 0 }], [from + 40, { opacity: 1 }], [tEnd, { opacity: 1 }]]);
    track(run, cap.firstChild, [[from, { transform: pose(dx, dy, 0, small) }, EASE.arc],
                                [from + 300, { transform: pose(dx * 0.4, Math.min(dy, 0) - 40, turn / 2, 0.7) }, 'cubic-bezier(0.55, 0, 0.85, 0.35)'],
                                [from + 520, { transform: pose(0, 0, turn, 1) }], [from + 560, { transform: pose(0, 0, turn, 1.1, 0.9) }],
                                [from + 600, { transform: pose(0, -8, turn, 0.97, 1.03) }], [tOpen, { transform: pose(0, 0, turn, 1) }]]);
    track(run, cap.firstChild.lastChild, [[tOpen, { transform: 'none', opacity: 1 }, EASE.out],
                                          [tEnd, { transform: pose(turn > 0 ? 20 : -20, -34, turn > 0 ? 40 : -40), opacity: 0 }]]);
    sound.fx('ding', tOpen);
    var last = run.anims[run.anims.length - 1];
    last.finished.then(function () { if (state.run === run) finish(pick); }, function () {});
  }
  // A press during a draw lands it at once.
  function landNow() {
    var run = state.run;
    if (!run) return;
    run.anims.forEach(function (a) { try { a.finish(); } catch (e) {} });
    finish(run.pick);
  }
  function finish(pick) {
    if (state.run) state.run.anims.forEach(function (a) { a.cancel(); });
    state.run = null;
    els.stage.classList.add('is-done');
    q('.pk-strip').textContent = pickEmoji(pick);      // the screen keeps the pick's food
    els.go.removeAttribute('aria-busy');
    els.goLabel.textContent = t('pick.again', '다시 뽑기');
    state.last = pick;
    showResult(pick);
  }

  // ---- the card ---------------------------------------------------------------------------------------
  // `relabel`: the language changed; the card is rewritten in place, focus and scroll stay.
  function showResult(pick, relabel) {
    var html, name;
    if (pick.meal) {
      var s = pick.meal, info = s.info, rows = [];
      name = s.resto.name;
      if (info.hours) rows.push('<li><span>' + esc(t('pick.hours', '시간')) + '</span> ' + esc(info.hours) + '</li>');
      if (info.price) rows.push('<li><span>' + esc(t('pick.price', '가격')) + '</span> ' + esc(info.price) + '</li>');
      if (s.resto.building) rows.push('<li><span>' + esc(t('pick.building', '건물')) + '</span> ' + esc(s.resto.building) + '</li>');
      html = '<p class="pick-result-kicker">🍱 ' + esc(t('pick.kind.cafeteria', '학식')) + ' · ' + esc(mealName(s.meal)) + '</p>' +
        '<h2 class="pick-result-title" tabindex="-1">' + esc(name) + '</h2>' +
        '<ul class="pick-menu">' + cleanItems(info.items).slice(0, 8).map(function (item) { return '<li>' + esc(item) + '</li>'; }).join('') + '</ul>' +
        (rows.length ? '<ul class="pick-facts">' + rows.join('') + '</ul>' : '') +
        '<div class="pick-actions"><a class="pick-btn" href="ggongbab.html#menu">' + esc(t('pick.toMenu', '학식 전체 보기')) + ' →</a></div>';
    } else if (pick.campus) {
      var campus = pick.campus;
      name = campus.name;
      var price = Number.isInteger(campus.priceWon) && campus.priceWon >= 0
        ? '<li><span>' + esc(t('pick.price', '가격')) + '</span> ₩' + campus.priceWon.toLocaleString('en-US') + '</li>' : '';
      var status = campus.photoStatus === '품절' || campus.photoStatus === '일시품절'
        ? t('pick.photoSoldOut', '품절 표시가 있었어요')
        : campus.photoStatus === '화면별 상이' ? t('pick.photoMixed', '품절일 수 있어요') : '';
      var seasonal = typeof campus.category === 'string' && /여름|겨울|계절/.test(campus.category)
        ? t('pick.seasonal', '계절 메뉴') : '';
      html = '<p class="pick-result-kicker">🍽️ ' + esc(t('pick.kind.campus', '교내 식당')) + '</p>' +
        '<h2 class="pick-result-title" tabindex="-1">' + esc(name) + '</h2>' +
        '<ul class="pick-facts"><li><span>' + esc(t('pick.restaurant', '식당')) + '</span> ' + esc(campus.store) + '</li>' + price + '</ul>' +
        (status ? '<p class="pick-note">' + esc(status) + '</p>' : '') +
        (seasonal ? '<p class="pick-note">' + esc(seasonal) + '</p>' : '') +
        '<p class="pick-note">' + esc(t('pick.campusNote', '가격·판매 여부는 매장에서 확인해 주세요.')) + '</p>';
    } else {
      var dish = pick.dish, photo = photoOf(dish.id), credit = '';
      name = dishName(dish);
      if (photo && photo.author && photo.license) {
        var source = safeHref(photo.source), licence = safeHref(photo.licenseUrl);
        credit = '<p class="pick-credit">' + esc(t('pick.photo', '사진')) + ' · ' +
          (source ? '<a href="' + esc(source) + '" target="_blank" rel="noopener noreferrer">' + esc(photo.author) + '</a>' : esc(photo.author)) + ' · ' +
          (licence ? '<a href="' + esc(licence) + '" target="_blank" rel="noopener noreferrer">' + esc(photo.license) + '</a>' : esc(photo.license)) + '</p>';
      }
      var votes = state.votes[dish.id] || {}, like = '';
      if (statsApi) {
        like = '<div class="pick-actions">' + (pick.liked
          ? '<button type="button" class="pick-like" data-pick-like disabled>' + esc(t('pick.liked', '👍 좋아요!')) + '</button>'
          : '<button type="button" class="pick-like" data-pick-like>' + esc(t('pick.like', '👍 이거 먹을래요')) + '</button>') + '</div>';
        if (votes.likes >= 3) like += '<p class="pick-votes">' + esc(fill(t('pick.votes', '👍 {n}명이 이걸 골랐어요'), { n: votes.likes })) + '</p>';
      }
      html = '<p class="pick-result-kicker">🛵 ' + esc(t('pick.kind.delivery', '배달')) + ' · ' + pick.kind.emoji + ' ' +
        esc(t('pick.cat.' + pick.kind.id, pick.kind.id)) + '</p>' +
        '<h2 class="pick-result-title" tabindex="-1">' + esc(name) + '</h2>' + like +
        '<p class="pick-note">' + esc(t('pick.shopNote', '가게와 가격은 배달앱에서 골라요.')) + '</p>' + credit;
    }
    els.result.innerHTML = html;
    els.result.hidden = false;
    if (relabel) return;
    els.status.textContent = fill(t('pick.landed', '오늘은 {name}!'), { name: name });
    var title = els.result.querySelector('.pick-result-title');
    title.focus({ preventScroll: true });
    var box = els.result.getBoundingClientRect();
    if (box.bottom > window.innerHeight) els.result.scrollIntoView({ block: 'nearest', behavior: canAnimate() ? 'smooth' : 'auto' });
  }

  function go() {
    if (state.run) { landNow(); return; }
    // Drawing again past a dish with no 👍 counts against it, once.
    if (state.last && state.last.dish && !state.last.liked && !state.last.passed) {
      state.last.passed = true;
      record('reroll', state.last.dish);
    }
    els.go.setAttribute('aria-busy', 'true');
    els.goLabel.textContent = t('pick.loading', '메뉴 불러오는 중');
    Promise.all([menuReady, foodsReady, campusReady]).then(function () {
      var pick = draw(servingNow(), state.dishes, null, state.votes, state.campus);
      if (pick && pick.dish) pick.kind = kindOf(pick.dish);
      if (!pick) {
        els.go.removeAttribute('aria-busy');
        els.goLabel.textContent = t('pick.go', '메뉴 뽑기');
        els.result.innerHTML = '<p class="pick-note">' + esc(t('pick.error', '메뉴를 불러오지 못했어요.')) + '</p>';
        els.result.hidden = false;
        els.status.textContent = t('pick.error', '메뉴를 불러오지 못했어요.');
        return;
      }
      if (pick.dish) record('draw', pick.dish);
      play(pick);
    });
  }

  els.go.addEventListener('click', go);
  els.result.addEventListener('click', function (e) {
    var button = e.target.closest('[data-pick-like]');
    var pick = state.last;
    if (!button || button.disabled || !pick || !pick.dish || pick.liked) return;
    pick.liked = true;
    record('like', pick.dish);
    button.disabled = true;
    button.textContent = t('pick.liked', '👍 좋아요!');
    els.status.textContent = button.textContent;
  });
  els.sound.addEventListener('click', function () { sound.toggle(); paintSound(); });
  // The button says what it does now (its label has no data-i18n: it changes with the draw); a language
  // change also rewrites the card in the new language.
  function labelGo() {
    els.goLabel.textContent = state.run ? t('pick.drawing', '뽑는 중…') : state.last ? t('pick.again', '다시 뽑기') : t('pick.go', '메뉴 뽑기');
  }
  document.addEventListener('babdoduk-lang', function () {
    labelGo();
    if (state.last && !state.run) showResult(state.last, true);
  });
  labelGo();
  paintSound();
})();
