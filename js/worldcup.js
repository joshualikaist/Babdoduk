/* Babdoduk food world cup (worldcup.html): each game draws `size` dishes (32) from the pool in
   data/content/worldcup.json (the sync writes it into the page as window.BABDODUK_WORLDCUP;
   data/content/ is never deployed) and plays them two at a time, with names and flavours from the
   food catalog (data/foods/). A pick pops; from the quarterfinals on a new round takes the screen
   for a beat (the final with a crash of the two finalists); the winner gets confetti and a result
   image to save. Progress and past winners stay in this browser (localStorage
   `babdoduk-worldcup`); nothing is sent anywhere.
   Categories (owner 2026-10-14): the start screen offers the whole pool or one of seven categories
   (data/content/worldcup.json `categories`); a game draws its 32 dishes from the chosen one and
   keeps `category` in the saved game (an older save has none and counts as the whole pool).
   The start screen (owner 2026-10-14: "초입이 재미있어야"): dish photos float around a round card,
   "오늘의 32강, 뭐가 나올까?", big category tiles (and 🙈 아무거나, which spins through them), five
   dishes of the next draw, and a big start button that opens the start gacha (about 5 s, skippable,
   never on 이어하기). Nothing of the motion with reduced motion.
   The same start screen runs in the news page's world cup card (event.html, owner 2026-10-14: the
   live event, not a teaser): there is no match, result or splash in that page (`embedded`), the
   data is js/worldcup-entry-data.js (names and categories, photos by path), nothing of a saved
   game is read, and 32강 시작 opens worldcup.html?cat=<category>&go=1. worldcup.html
   starts that category at once (the start gacha, as if the button had been pressed there) and
   only for go=1 with a known category; the address is then cleaned so a reload never restarts. */
(function () {
  'use strict';
  var KEY = 'babdoduk-worldcup';
  var HISTORY = 10;
  // Flavour and texture tags, most telling first; a card shows at most two (score 4 or 5).
  var TAGS = ['spicy', 'crispy', 'soupy', 'sweet', 'chewy', 'rich', 'umami', 'sour', 'salty', 'soft'];
  var cup = window.BABDODUK_WORLDCUP || {};
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var embedded = !document.getElementById('wcMatch');   // the news page's card: the start screen alone
  var dishes = {};
  var CATEGORIES = ['all', 'korean', 'chinese', 'japanese', 'western', 'world', 'snack', 'dessert'];
  var CATEGORY_NAMES = { all: '전체', korean: '한식', chinese: '중식', japanese: '일식', western: '양식',
                         world: '아시아·세계', snack: '분식·간식', dessert: '디저트·카페' };
  var CATEGORY_EMOJI = { all: '🎲', korean: '🍚', chinese: '🥟', japanese: '🍣', western: '🍝', world: '🍜',
                         snack: '🍢', dessert: '🍰' };
  var set = [];         // the pool
  var category = 'all'; // the tile chosen on the start screen (a game in progress has its own)
  var size = 0;         // dishes per game (a power of two)
  var game = null;     // { entrants: [ids], winners: [ids], stack: [{ entrants, winners }], log, category }
  var winners = [];     // [{ id, finalist, date }], newest first
  var result = null;    // { id, finalist, category } of the game just finished
  var view = 'loading';
  var busy = false;
  var $ = function (id) { return document.getElementById(id); };
  var cards = [].slice.call(document.querySelectorAll('.wc-card'));
  var credits = [].slice.call(document.querySelectorAll('.wc-slot .wc-credit a'));

  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function t(key, fallback) {
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang()];
    if (pack && pack[key] != null) return pack[key];
    return fallback == null ? key : fallback;
  }
  function fill(text, values) {
    return String(text).replace(/\{(\w+)\}/g, function (match, name) {
      return values[name] != null ? values[name] : match;
    });
  }
  function todayKst() {
    var d = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function announce(text) {
    var status = $('wcStatus');
    status.textContent = '';
    setTimeout(function () { status.textContent = text; }, 30);
  }

  function name(id) { var d = dishes[id]; return d ? (lang() === 'en' ? d.nameEn : d.nameKo) : id; }
  function otherName(id) { var d = dishes[id]; return d ? (lang() === 'en' ? d.nameKo : d.nameEn) : ''; }
  function tags(id) {
    var d = dishes[id] || {}, scores = {};
    [d.flavor || {}, d.texture || {}].forEach(function (group) {
      Object.keys(group).forEach(function (k) { scores[k] = group[k]; });
    });
    return TAGS.filter(function (k) { return scores[k] >= 4; }).slice(0, 2)
      .map(function (k) { return t('wc.tag.' + k, k); });
  }
  // A dish's photo (data/content/worldcup.json `photos`) and its credit link; a missing or broken
  // file hides both rather than showing an empty frame.
  function showPhoto(img, link, id) {
    var photo = photoOf(id);
    var caption = link.parentNode;
    img.hidden = caption.hidden = !photo;
    if (!photo) { img.removeAttribute('src'); return; }
    img.onerror = function () { img.hidden = caption.hidden = true; };
    if (img.getAttribute('src') !== photo.image) img.src = photo.image;
    link.href = photo.source;
    link.textContent = fill(t('wc.photoCredit', '사진 {author} · {license}'), { author: photo.author, license: photo.license });
  }
  // A dish's photo: its entry in the pool, or (the news page's data) the shared path pattern.
  function photoOf(id) {
    var photo = (cup.photos || {})[id];
    if (!photo && cup.photoPath && dishes[id]) photo = { image: cup.photoPath.replace('{id}', id) };
    return photo;
  }
  function preload(ids) {
    ids.forEach(function (id) {
      var photo = id && photoOf(id);
      if (photo) { var img = new Image(); img.src = photo.image; }
    });
  }
  // ---- categories ----------------------------------------------------------------------------
  // The dishes of one category, or the whole pool for 'all'.
  function poolOf(cat) {
    if (cat === 'all') return set;
    var of = cup.categories || {};
    return set.filter(function (id) { return of[id] === cat; });
  }
  // A saved game's category: none (an older save) is the whole pool; an unknown one is unreadable.
  function savedCategory(g) {
    if (g.category == null) return 'all';
    return CATEGORIES.indexOf(g.category) >= 0 ? g.category : null;
  }
  function catName(cat) { return t('wc.cat.' + cat, CATEGORY_NAMES[cat] || cat); }
  function gameLabel(cat) { return fill(t('wc.catGame', '{cat} {n}강'), { cat: catName(cat), n: size }); }
  function roundName(size) {
    if (size === 2) return t('wc.round.final', '결승');
    if (size === 4) return t('wc.round.semi', '4강');
    return fill(t('wc.round.n', '{n}강'), { n: size });
  }

  // ---- saved state ---------------------------------------------------------------------------
  function signature() { return size + ':' + set.join(','); }
  function validGame(g) {
    if (!g || !Array.isArray(g.entrants) || !Array.isArray(g.winners) || !Array.isArray(g.stack)) return false;
    var size = g.entrants.length;
    if (size < 2 || (size & (size - 1)) || g.winners.length >= size / 2) return false;
    var cat = savedCategory(g);
    if (!cat) return false;
    var pool = poolOf(cat);
    return g.entrants.concat(g.winners).every(function (id) { return pool.indexOf(id) >= 0; });
  }
  function restore() {
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!saved || saved.v !== 1) return;
      winners = (Array.isArray(saved.winners) ? saved.winners : []).filter(function (w) {
        return w && dishes[w.id] && typeof w.date === 'string';
      }).slice(0, HISTORY);
      if (saved.set === signature() && validGame(saved.game)) {
        game = saved.game;
        game.category = savedCategory(game);        // an older save is the whole pool
        category = game.category;                    // the chips start on the game being resumed
      }
    } catch (e) { /* unreadable storage: start fresh */ }
  }
  function store() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ v: 1, set: signature(), game: game, winners: winners }));
    } catch (e) { /* private mode or full storage: the game still works for this visit */ }
  }

  // ---- views ---------------------------------------------------------------------------------
  function show(which) {
    view = which;
    ['Loading', 'Intro', 'Match', 'Result'].forEach(function (part) {
      var el = $('wc' + part);
      if (el) el.hidden = part.toLowerCase() !== which;
    });
    renderHistory();
  }
  function progress() {
    return { round: roundName(game.entrants.length), n: game.winners.length + 1, total: game.entrants.length / 2,
             cat: catName(game.category) };
  }
  function picksMade() {
    var made = 0, round = size;
    while (round > game.entrants.length) { made += round / 2; round /= 2; }
    return made + game.winners.length;
  }
  function pair() {
    var i = game.winners.length * 2;
    return [game.entrants[i], game.entrants[i + 1]];
  }
  // ---- the start screen ------------------------------------------------------------------------
  // Big category tiles (owner 2026-10-14: "재미"): an emoji, the name and the count, each a toggle
  // (aria-pressed) that pops, tilts and glows when chosen; 🙈 아무거나 is a plain button that spins
  // through them and lands on one. Choosing a category draws its next bracket at once (`pending`),
  // so the five photos under the tiles really are in the next game ("이 중에서 나와요!") and the start
  // gacha pours the same dishes, already loaded.
  var pending = null;   // { cat, ids }: the bracket that the next start from this screen plays
  var spin = null;      // the 아무거나 run: { target, timer, anim }
  function draw(cat) { return shuffle(poolOf(cat)).slice(0, size); }
  function canAnimate() { return typeof Element.prototype.animate === 'function'; }
  function moving() { return !reduced && canAnimate(); }
  function buildTiles() {
    var box = $('wcCats');
    box.textContent = '';
    CATEGORIES.concat('random').forEach(function (cat) {
      var tile = node('button', cat === 'random' ? 'wc-tile wc-tile--random' : 'wc-tile', box);
      tile.type = 'button';
      tile.setAttribute('data-cat', cat);
      var emoji = node('span', 'wc-tile-emoji', tile);
      emoji.setAttribute('aria-hidden', 'true');
      emoji.textContent = cat === 'random' ? '🙈' : CATEGORY_EMOJI[cat];
      node('span', 'wc-tile-name', tile);
      node('span', 'wc-tile-n', tile);
      tile.addEventListener('click', function () {
        if (cat === 'random') spinTiles(); else choose(cat, true);
      });
    });
  }
  function renderTiles() {
    [].forEach.call($('wcCats').querySelectorAll('.wc-tile'), function (tile) {
      var cat = tile.getAttribute('data-cat');
      tile.querySelector('.wc-tile-name').textContent = cat === 'random' ? t('wc.cat.random', '아무거나') : catName(cat);
      tile.querySelector('.wc-tile-n').textContent = cat === 'random' ? t('wc.cat.randomSub', '랜덤!')
        : fill(t('wc.catCount', '{n}개'), { n: poolOf(cat).length });
      if (cat !== 'random') tile.setAttribute('aria-pressed', cat === category ? 'true' : 'false');
    });
  }
  // `user`: a tap or a key chose it (the tile pops and the button breathes again); otherwise the
  // first draw on arrival. Either way the five photos shuffle in.
  function choose(cat, user) {
    stopSpin(false);
    category = cat;
    pending = { cat: cat, ids: draw(cat) };
    renderTiles();
    renderPreview(true);
    if (!user || !moving()) return;
    var emoji = $('wcCats').querySelector('[data-cat="' + cat + '"] .wc-tile-emoji');
    emoji.animate([{ transform: 'none' }, { transform: 'scale(1.5) rotate(-14deg)', offset: 0.35 },
                   { transform: 'scale(0.92) rotate(6deg)', offset: 0.7 }, { transform: 'none' }],
                  { duration: 520, easing: 'ease-out' });
    ambient(false);
  }
  // 이 중에서 나와요: five dishes of the pending bracket (not the first match, which stays a surprise).
  function renderPreview(animate) {
    var list = $('wcPreviewPhotos');
    list.textContent = '';
    (pending ? pending.ids.slice(2, 7) : []).forEach(function (id, i) {
      var photo = photoOf(id);
      if (!photo) return;
      var item = node('li', 'wc-preview-item', list), img = node('img', 'wc-preview-photo', item);
      img.alt = name(id);
      img.width = 160;
      img.height = 160;
      img.decoding = 'async';
      img.setAttribute('data-id', id);
      img.onerror = function () { item.hidden = true; };
      img.src = photo.image;
      if (animate && moving()) {
        item.animate([{ transform: 'translateY(-22px) rotate(-18deg) scale(0.4)', opacity: 0 }, { transform: 'none', opacity: 1 }],
                     { duration: 480, delay: 40 + i * 70, easing: EASE.bouncy, fill: 'backwards' });
      }
    });
    $('wcPreview').hidden = !list.children.length;
  }
  // 아무거나: the light runs through the tiles, a full lap and on to a category other than the one
  // chosen, slowing down like a slot machine (about 1.3 s); a second tap or 32강 시작 lands it at
  // once. With reduced motion it lands straight away.
  function spinTiles() {
    if (spin) { stopSpin(true); return; }
    var others = CATEGORIES.filter(function (c) { return c !== category; });
    var target = others[Math.floor(Math.random() * others.length)];
    if (!moving()) { landSpin(target); return; }
    var box = $('wcCats'), from = CATEGORIES.indexOf(category), count = CATEGORIES.length;
    var steps = count + (CATEGORIES.indexOf(target) - from + count) % count, i = 0, lit = null;
    var die = box.querySelector('[data-cat="random"] .wc-tile-emoji');
    spin = { target: target, timer: 0,
             anim: die.animate([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 420, iterations: Infinity }) };
    box.classList.add('is-spinning');
    (function step() {
      i++;
      if (lit) lit.classList.remove('is-spin');
      lit = box.querySelector('[data-cat="' + CATEGORIES[(from + i) % count] + '"]');
      lit.classList.add('is-spin');
      spin.timer = i >= steps ? setTimeout(function () { stopSpin(true); }, 240)
        : setTimeout(step, 45 + 230 * Math.pow(i / steps, 2.4));
    })();
  }
  function stopSpin(land) {
    if (!spin) return;
    var s = spin;
    spin = null;
    clearTimeout(s.timer);
    s.anim.cancel();
    $('wcCats').classList.remove('is-spinning');
    [].forEach.call($('wcCats').querySelectorAll('.is-spin'), function (tile) { tile.classList.remove('is-spin'); });
    if (land) landSpin(s.target);
  }
  function landSpin(cat) {
    choose(cat, true);
    announce(fill(t('wc.catLanded', '{cat} 당첨!'), { cat: catName(cat) }));
  }
  // "오늘의 32강, 뭐가 나올까?": the round (or its number) on a pink-to-blue highlighter.
  function renderTitle() {
    var title = $('wcIntroTitle'), text = fill(t('wc.intro.title', '오늘의 {n}강, 뭐가 나올까?'), { n: size });
    var mark = roundName(size), at = text.toLowerCase().indexOf(mark.toLowerCase());
    if (at < 0) { mark = String(size); at = text.indexOf(mark); }
    title.textContent = '';
    if (at < 0) { title.textContent = text; return; }
    title.appendChild(document.createTextNode(text.slice(0, at)));
    node('span', 'wc-hl', title).textContent = text.slice(at, at + mark.length);
    title.appendChild(document.createTextNode(text.slice(at + mark.length)));
  }
  function renderIntro() {
    renderTiles();
    renderTitle();
    $('wcStartLabel').textContent = fill(t('wc.start', '{n}강 시작'), { n: size });
    // A game in progress makes resuming the big button; 새로 시작 is a small link under it.
    var resumable = !!game;
    $('wcStart').hidden = resumable;
    $('wcResume').hidden = $('wcNew').hidden = !resumable;
    if (resumable) $('wcResumeLabel').textContent = fill(t('wc.resume', '이어하기 · {cat} {round} {n}/{total}'), progress());
    [].forEach.call($('wcPreviewPhotos').querySelectorAll('img'), function (img) { img.alt = name(img.getAttribute('data-id')); });
  }
  // Dish photos around the card: four on a phone, six wider, drawn from the whole pool per visit.
  function buildFloaters() {
    var box = $('wcFloaters'), wide = !embedded && window.matchMedia && window.matchMedia('(min-width: 700px)').matches;
    box.textContent = '';
    shuffle(set).slice(0, wide ? 6 : 4).forEach(function (id) {
      var photo = photoOf(id), img = node('img', 'wc-floater', box);
      img.alt = '';
      img.width = 160;
      img.height = 160;
      img.decoding = 'async';
      img.hidden = !photo;
      img.onerror = function () { img.hidden = true; };
      if (photo) img.src = photo.image;
    });
  }
  // On arrival the photos pop out and bob twice and the big button breathes three times; a new
  // category makes them hop once and the button breathe twice. Every run is over within 5 s (no
  // motion that keeps going on its own), and none with reduced motion.
  var ambientAnims = [];
  function stopAmbient() { ambientAnims.forEach(function (a) { a.cancel(); }); ambientAnims = []; }
  function ambient(arriving) {
    stopAmbient();
    if (!moving() || view !== 'intro') return;
    [].forEach.call($('wcFloaters').children, function (img, i) {
      if (arriving) {
        ambientAnims.push(img.animate([{ transform: 'translateY(26px) scale(0.4)', opacity: 0 }, { transform: 'none', opacity: 1 }],
                                      { duration: 560, delay: 120 + i * 90, easing: EASE.bouncy, fill: 'backwards' }));
      }
      ambientAnims.push(img.animate([{ transform: 'none' }, { transform: 'translateY(-12px) rotate(' + (i % 2 ? 4 : -4) + 'deg)' }, { transform: 'none' }],
                                    { duration: arriving ? 1700 : 640, delay: arriving ? 760 + i * 110 : i * 45,
                                      iterations: arriving ? 2 : 1, easing: 'ease-in-out' }));
    });
    var button = game ? $('wcResume') : $('wcStart'), breath = { duration: 1400, delay: arriving ? 600 : 120,
                                                                 iterations: arriving ? 3 : 2, easing: 'ease-in-out' };
    ambientAnims.push(button.animate([{ scale: '1' }, { scale: '1.05', offset: 0.45 }, { scale: '1' }], breath));
    try {
      ambientAnims.push(button.animate([{ opacity: 0.3 }, { opacity: 0.9, offset: 0.45 }, { opacity: 0.3 }],
                                       Object.assign({ pseudoElement: '::before' }, breath)));
    } catch (e) { /* no pseudo-element animation: the button breathes without its glow */ }
  }
  // `instant`: a round splash covers the screen, so the match jumps into view rather than scrolling.
  function renderMatch(focus, instant) {
    var p = progress(), ids = pair(), done = picksMade(), all = size - 1;
    $('wcGame').textContent = gameLabel(game.category);
    $('wcRound').textContent = p.round;
    $('wcCount').textContent = fill(t('wc.count', '{n} / {total}'), p);
    var bar = $('wcBar');
    bar.style.width = Math.round(done / all * 100) + '%';
    var track = $('wcProgress');
    track.setAttribute('aria-valuenow', String(done));
    track.setAttribute('aria-valuemax', String(all));
    track.setAttribute('aria-label', t('wc.progressAria', '전체 진행'));
    cards.forEach(function (card, side) {
      var id = ids[side];
      card.setAttribute('data-id', id);
      card.querySelector('.wc-card-name').textContent = name(id);
      card.querySelector('.wc-card-sub').textContent = otherName(id);
      var tagLine = card.querySelector('.wc-card-tags');
      tagLine.textContent = tags(id).join(' · ');
      tagLine.hidden = !tagLine.textContent;
      card.setAttribute('aria-label', fill(t('wc.pick', '{dish} 고르기'), { dish: name(id) }));
      showPhoto(card.querySelector('.wc-photo'), credits[side], id);
    });
    var next = game.winners.length * 2 + 2;
    preload([game.entrants[next], game.entrants[next + 1]]);
    $('wcUndo').disabled = !game.stack.length;
    if (focus) {
      // Keep the round title and both cards in view rather than scrolling to the focused card.
      cards[0].focus({ preventScroll: true });
      var box = $('wcMatch').getBoundingClientRect();
      if (box.top < 0 || box.top > window.innerHeight * 0.4) {
        var root = document.documentElement, was = root.style.scrollBehavior;
        if (instant) root.style.scrollBehavior = 'auto';        // css/site.css scrolls smoothly site-wide
        $('wcMatch').scrollIntoView({ block: 'start', behavior: reduced || instant ? 'auto' : 'smooth' });
        root.style.scrollBehavior = was;
      }
    }
    if (focus !== null) announce(fill(t('wc.announce', '{round} {n}번째 경기: {a} 대 {b}'),
      { round: p.round, n: p.n, a: name(ids[0]), b: name(ids[1]) }));
  }
  function renderResult(focus) {
    $('wcResultGame').textContent = gameLabel(result.category);
    $('wcWinner').textContent = name(result.id);
    $('wcWinnerSub').textContent = otherName(result.id);
    $('wcFinalist').textContent = fill(t('wc.finalist', '결승 상대: {dish}'), { dish: name(result.finalist) });
    showPhoto($('wcWinnerImg'), $('wcWinnerCredit'), result.id);
    $('wcWinnerFigure').hidden = $('wcWinnerImg').hidden;
    $('wcShareStatus').textContent = '';
    if (focus) {
      $('wcWinner').focus();
      announce(fill(t('wc.announceWinner', '우승 메뉴: {dish}'), { dish: name(result.id) }));
    }
  }
  function renderHistory() {
    if (embedded) return;
    var list = $('wcHistoryList');
    list.textContent = '';
    winners.forEach(function (w) {
      var item = document.createElement('li');
      var dish = document.createElement('span');
      dish.textContent = name(w.id);
      var when = document.createElement('time');
      when.setAttribute('datetime', w.date);
      when.textContent = w.date.slice(5).replace('-', '.');
      item.appendChild(dish);
      item.appendChild(when);
      list.appendChild(item);
    });
    $('wcHistory').hidden = !winners.length || view === 'loading' || view === 'match';
  }
  function render() {
    if (view === 'intro') renderIntro();
    if (view === 'match') renderMatch(null);
    if (view === 'result') renderResult(false);
    renderHistory();
  }

  // ---- play ----------------------------------------------------------------------------------
  function shuffle(list) {
    var a = list.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var swap = a[i]; a[i] = a[j]; a[j] = swap;
    }
    return a;
  }
  // `cat`: the category of the new game (the tile chosen, or the one being played again).
  // `animate`: 32강 시작, 새로 시작, 처음부터 and 다시 하기 open the start gacha; 이어하기 never does.
  function start(cat, animate) {
    cat = CATEGORIES.indexOf(cat) >= 0 && poolOf(cat).length >= size ? cat : 'all';
    // 처음부터 keeps the bracket being left as the new game's first undo step, so 되돌리기 brings it
    // back. One is kept: its own restart step is dropped, and restarting again before a pick keeps
    // the one already there.
    var before = null;
    if (game && game.stack.length) {
      var own = game.stack.filter(function (step) { return !step.game; });
      before = own.length ? { game: { entrants: game.entrants, winners: game.winners, stack: own, log: game.log || [],
                                      category: game.category } }
        : game.stack[0];
    }
    // From the start screen the bracket is the one already drawn there (its photos are on screen).
    var entrants = view === 'intro' && pending && pending.cat === cat ? pending.ids : draw(cat);
    pending = null;
    stopAmbient();
    category = cat;
    game = { entrants: entrants, winners: [], stack: before ? [before] : [], log: [], category: cat };
    result = null;
    store();                                            // the draw is kept before anything moves
    show('match');
    if (animate && canGacha()) {
      renderMatch(true, true);
      showGacha();
      return;
    }
    renderMatch(true);
  }
  function resume() {
    if (!game) { start(category, false); return; }
    show('match');
    renderMatch(true);
  }
  function finish(winner, finalist) {
    winners.unshift({ id: winner, finalist: finalist, date: todayKst() });
    winners = winners.slice(0, HISTORY);
    result = { id: winner, finalist: finalist, category: game.category };
    game = null;
    store();
    show('result');
    renderResult(true);
    celebrate();
  }
  function pick(side) {
    if (splash) { endSplash('skip'); return; }          // a screen reader's click on a card under the splash
    if (busy || view !== 'match') return;
    var ids = pair(), chosen = ids[side];
    game.stack.push({ entrants: game.entrants.slice(), winners: game.winners.slice(), log: (game.log || []).length });
    game.winners.push(chosen);
    if (game.log) game.log.push([chosen, ids[1 - side]]);
    if (game.winners.length * 2 === game.entrants.length) {
      if (game.winners.length === 1) { finish(chosen, ids[1 - side]); return; }
      game.entrants = game.winners;
      game.winners = [];
    }
    store();
    var newRound = game.winners.length === 0;          // this pick closed a round
    if (reduced) { renderMatch(true); return; }         // the match announcement names the round
    busy = true;
    cards[side].classList.add('is-picked');
    cards[1 - side].classList.add('is-dropped');
    burst(cards[side]);
    setTimeout(function () {
      cards[side].classList.remove('is-picked');
      cards[1 - side].classList.remove('is-dropped');
      busy = false;
      var round = game.entrants.length, splashing = newRound && view === 'match' && canSplash(round);
      renderMatch(true, splashing);
      if (splashing) showSplash(round);
    }, 480);
  }

  // ---- round splash ------------------------------------------------------------------------------
  // From the quarterfinals on, a new round takes the whole screen for a beat (owner 2026-10-14: a
  // TV game show, not a banner over the cards). 8강 and 4강: black, the round in big white letters,
  // 0.8 s. 결승: the same title, then the crash, 2 s in all: the two finalists' cards fly in from
  // the sides and collide (a hit stop, one white flash, a short shake, speed lines, a VS stamp),
  // recoil and settle into the real match. It is decoration over a match that is already stored,
  // rendered, focused and announced, in a top-layer popover (#wcSplash), so nothing paints over it
  // and no tap reaches a card. A tap or a key (Escape, Enter, Space ...) skips to the match and
  // never picks; a key held through it is swallowed until released. Nothing of it with reduced
  // motion or forced colours, and a failure, a hidden tab, a new width, scrolling or the language
  // switch only end it. Times are ms on the splash's clock; only transform and opacity move.
  var SPLASH = {
    8: { key: 'wc.splash.quarter', text: '8강 진출!', ms: 800 },
    4: { key: 'wc.splash.semi', text: '4강 진출!', ms: 800 },
    2: { key: 'wc.splash.final', text: '결승!', ms: 2000 }
  };
  var LINEAR = !!(window.CSS && CSS.supports && CSS.supports('animation-timing-function', 'linear(0, 1)'));
  var EASE = {    // springs as linear() where supported (peaks 1.045 and 1.006), cubic-bezier otherwise
    bouncy: LINEAR ? 'linear(0, 0.06, 0.199, 0.369, 0.539, 0.69, 0.813, 0.905, 0.971, 1.012, 1.035, 1.045, 1.045, 1.041, 1.034, 1.026, 1.018, 1.012, 1.007, 1.003, 1, 0.999, 0.998, 0.998, 1)' : 'cubic-bezier(0.34, 1.56, 0.64, 1)',
    soft: LINEAR ? 'linear(0, 0.046, 0.154, 0.286, 0.421, 0.547, 0.657, 0.748, 0.821, 0.877, 0.919, 0.95, 0.972, 0.987, 0.996, 1.002, 1.005, 1.006, 1.006, 1.006, 1.005, 1.004, 1.003, 1.003, 1)' : 'cubic-bezier(0.22, 1, 0.36, 1)',
    out: 'cubic-bezier(0, 0, 0.15, 1)', in: 'cubic-bezier(0.55, 0, 1, 0.45)', rush: 'cubic-bezier(0.45, 0, 0.9, 0.55)',
    io: 'cubic-bezier(0.35, 0, 0.35, 1)', back: 'cubic-bezier(0.2, 1.4, 0.4, 1)'
  };
  var splashEl = $('wcSplash');
  var forcedColors = window.matchMedia ? window.matchMedia('(forced-colors: active)') : null;
  var splash = null;      // the one on screen: { anims, width, run, safety }
  var splashRun = 0;
  var heldKey = null;     // a key pressed during a splash, swallowed until it is released
  var quietUntil = 0;     // and a tap just after a skip is not a pick either

  function canSplash(round) {
    return !!SPLASH[round] && !reduced && !(forcedColors && forcedColors.matches) && !document.hidden
      && typeof splashEl.showPopover === 'function' && typeof splashEl.animate === 'function';
  }
  function node(tag, cls, parent) {
    var el = document.createElement(tag);
    el.className = cls;
    if (parent) parent.appendChild(el);
    return el;
  }
  function pose(x, y, r, sx, sy) {   // translate, rotate, scale
    sx = sx == null ? 1 : sx;
    return 'translate(' + x + 'px, ' + y + 'px) rotate(' + (r || 0) + 'deg) scale(' + sx + ', ' + (sy == null ? sx : sy) + ')';
  }
  // One element's whole part as [ms, keyframe, easing onward] steps: a single animation, filled
  // both ways, so before its first step it already holds its first pose.
  function track(el, steps) {
    var from = steps[0][0], span = steps[steps.length - 1][0] - from;
    var frames = steps.map(function (step) {
      var frame = { offset: (step[0] - from) / span };
      for (var k in step[1]) frame[k] = step[1][k];
      if (step[2]) frame.easing = step[2];
      return frame;
    });
    var a = el.animate(frames, { delay: from, duration: span, fill: 'both' });
    splash.anims.push(a);
    return a;
  }
  // A step at a time on the splash clock, as an empty animation: a skip cancels it, finish() runs it.
  function cue(ms, fn) {
    var run = splash.run, a = splashEl.animate(null, { duration: 0, delay: ms });
    a.onfinish = function () { if (splash && splash.run === run) fn(); };
    splash.anims.push(a);
  }
  // The round in big letters, each popping in just after the one before, fitted to the screen.
  function splashTitle(stage, spec, w, h, final) {
    var center = node('div', 'wc-splash-center', stage);
    var glow = node('i', 'wc-splash-glow', center);
    var ring = node('i', 'wc-splash-ring', center);
    var title = node('p', 'wc-splash-title', center);
    var size = Math.min(w * (final ? 0.27 : 0.2), h * 0.24, final ? 210 : 170);
    title.style.fontSize = size + 'px';
    var chars = Array.from(t(spec.key, spec.text));
    chars.forEach(function (ch) {
      node('span', ch === ' ' ? 'wc-splash-ch wc-splash-gap' : 'wc-splash-ch', title).textContent = ch === ' ' ? '\u00a0' : ch;
    });
    var lineTop = node('i', 'wc-splash-line wc-splash-line--top', title);
    var lineBottom = node('i', 'wc-splash-line wc-splash-line--bottom', title);
    var width = title.getBoundingClientRect().width;
    if (width > w * 0.86) title.style.fontSize = (size * w * 0.86 / width) + 'px';
    var box = title.getBoundingClientRect(), d = Math.max(box.width, box.height) * 1.15;
    glow.style.cssText = ring.style.cssText = 'width:' + d + 'px;height:' + d + 'px';
    // The letters are gone before the black lifts: the round never sits over the food.
    var out = final ? 690 : 560, end = final ? 800 : 650;
    track(title, [[30, { transform: pose(0, 0, -6, 1.7), opacity: 0 }, 'cubic-bezier(0.3, 0, 0.6, 1)'],
                  [170, { transform: pose(0, 0, 1.5, 0.9), opacity: 1 }, 'ease-in-out'],
                  [270, { transform: pose(0, 0, -0.5, 1.045), opacity: 1 }, 'ease-in-out'],
                  [370, { transform: pose(0, 0, 0, 1), opacity: 1 }],
                  [out, { transform: pose(0, 0, 0, 1), opacity: 1 }, EASE.in],
                  [end, { transform: pose(0, 0, 0, final ? 1.9 : 1.14), opacity: 0 }]]);
    var letters = title.querySelectorAll('.wc-splash-ch'), step = Math.min(34, 190 / Math.max(1, letters.length - 1));
    [].forEach.call(letters, function (span, i) {          // all in by about 0.3 s, however long the word
      var at = 30 + i * step;
      track(span, [[at, { transform: 'translateY(-0.22em) scale(1.6)', opacity: 0 }, EASE.back],
                   [at + 210, { transform: 'translateY(0) scale(1)', opacity: 1 }]]);
    });
    [[lineTop, 'left'], [lineBottom, 'right']].forEach(function (line, i) {
      line[0].style.transformOrigin = line[1] + ' center';
      track(line[0], [[150 + i * 40, { transform: 'scaleX(0)', opacity: 1 }, EASE.out],
                      [420 + i * 40, { transform: 'scaleX(1)', opacity: 1 }],
                      [out, { transform: 'scaleX(1)', opacity: 1 }, EASE.in], [end, { transform: 'scaleX(1)', opacity: 0 }]]);
    });
    track(glow, [[40, { transform: 'scale(0.5)', opacity: 0 }, EASE.out], [320, { transform: 'scale(1)', opacity: 1 }],
                 [out, { transform: 'scale(1)', opacity: 1 }], [end, { transform: 'scale(1.2)', opacity: 0 }]]);
    track(ring, [[149, { transform: 'scale(0.4)', opacity: 0 }], [150, { transform: 'scale(0.4)', opacity: 0.7 }, EASE.out],
                 [480, { transform: 'scale(1.25)', opacity: 0 }]]);
  }
  // 결승: the finalists fly in, crash, recoil and settle onto the real cards beneath.
  function crash(stage, w, h) {
    var cx = w / 2, cy = h / 2, phone = w <= 560, IMPACT = 1100, STOP = 110;
    // The real cards stay hidden until their doubles land on them, and are measured at rest: a
    // pick's scale or a hover lift must not shrink or shift a double.
    cards.forEach(function (card) { card.style.transition = 'none'; card.style.transform = 'none'; card.style.opacity = '0'; });
    var rects = cards.map(function (card) { return card.getBoundingClientRect(); });
    var cardW = rects[0].width, cardHeight = rects[0].height;
    // Wide screens: side by side, a little bigger. A phone's pair already fills the width, so
    // there they grow about 1.5x and clash on a diagonal, the left one high and the right one
    // low, overlapping in the middle under the VS: the whole screen, nothing outside it.
    var diagonal = phone && h > w * 1.2, gap = diagonal ? 0 : phone ? 12 : 28, z, seats;
    if (diagonal) {
      var edge = 16;
      z = Math.max(1, Math.min(1.6, w * 0.7 / cardW, (h - 56) / (1.84 * cardHeight)));
      var dy = cardHeight * z * 0.42;                   // the two overlap by 16% of their height
      seats = [{ x: edge + cardW * z / 2, y: cy - dy }, { x: w - edge - cardW * z / 2, y: cy + dy }];
    } else {
      z = Math.max(1, Math.min(1.2, w * 0.9 / (2 * cardW + gap), h * 0.7 / cardHeight));
      seats = [{ x: cx - cardW * z / 2 - gap / 2, y: cy }, { x: cx + cardW * z / 2 + gap / 2, y: cy }];
    }
    // Into each other at the hit, then thrown back (less on the diagonal, which has no room).
    // The recoil never throws a card off the screen: at most the room beside it, less its tilt.
    var lean = diagonal ? 0.5 : 1, push = diagonal ? 18 : gap / 2 + 2;
    var room = seats[0].x - cardW * z * 0.525 - cardHeight * z * Math.sin(4 * lean * Math.PI / 180) / 2 - 4;
    var kick = Math.max(0, Math.min(diagonal ? 4 : phone ? 22 : 40, room));
    var lines = node('i', 'wc-splash-lines', stage), burstRays = node('i', 'wc-splash-burst', stage);
    var wave = node('i', 'wc-splash-wave', stage);
    var big = Math.hypot(w, h) * 1.1, rays = Math.max(cardHeight * 2.3, Math.min(w, h)), ring = Math.min(w, h) * 0.6;
    function square(el, d) { el.style.cssText = 'left:' + (cx - d / 2) + 'px;top:' + (cy - d / 2) + 'px;width:' + d + 'px;height:' + d + 'px'; }
    square(lines, big);
    square(burstRays, rays);
    square(wave, ring);
    // Hidden until the impact itself (each first step is at the impact, so nothing shows early).
    track(lines, [[IMPACT - 1, { transform: 'scale(1.25) rotate(0deg)', opacity: 0 }], [IMPACT, { transform: 'scale(1.25) rotate(0deg)', opacity: 0 }, EASE.out],
                  [IMPACT + 60, { transform: 'scale(1.05) rotate(2deg)', opacity: 1 }],
                  [IMPACT + 380, { transform: 'scale(1) rotate(4deg)', opacity: 0.7 }, EASE.io], [1640, { transform: 'scale(1) rotate(5deg)', opacity: 0 }]]);
    track(burstRays, [[IMPACT - 1, { transform: 'scale(0.3) rotate(-10deg)', opacity: 0 }], [IMPACT, { transform: 'scale(0.3) rotate(-10deg)', opacity: 1 }, EASE.out],
                      [IMPACT + 160, { transform: 'scale(1) rotate(0deg)', opacity: 1 }],
                      [IMPACT + 460, { transform: 'scale(1.25) rotate(5deg)', opacity: 0 }]]);
    track(wave, [[IMPACT - 1, { transform: 'scale(0.2)', opacity: 0 }], [IMPACT, { transform: 'scale(0.2)', opacity: 0.9 }, EASE.out],
                 [IMPACT + 420, { transform: 'scale(2.2)', opacity: 0 }]]);
    cue(IMPACT, function () {
      confetti([{ x: cx, y: cy, spread: 18, drift: 0, lift: 10 }], phone ? 36 : 56, 900, splashEl, SPARKS);
    });
    var flash = node('i', 'wc-splash-flash', splashEl);
    track(flash, [[IMPACT, { opacity: 0 }, 'ease-out'], [IMPACT + 18, { opacity: 0.85 }, 'ease-in'], [IMPACT + 90, { opacity: 0 }]]);
    var amp = phone ? 6 : 8;
    track(stage, [[IMPACT, { transform: 'translate(0px, 0px)' }], [IMPACT + 30, { transform: 'translate(' + -amp + 'px, ' + amp / 2 + 'px)' }],
                  [IMPACT + 65, { transform: 'translate(' + amp * 0.85 + 'px, ' + -amp * 0.6 + 'px)' }],
                  [IMPACT + 100, { transform: 'translate(' + -amp * 0.6 + 'px, ' + amp * 0.4 + 'px)' }],
                  [IMPACT + 140, { transform: 'translate(' + amp * 0.4 + 'px, ' + -amp * 0.25 + 'px)' }],
                  [IMPACT + 190, { transform: 'translate(' + -amp * 0.2 + 'px, ' + amp * 0.1 + 'px)' }],
                  [IMPACT + 250, { transform: 'translate(0px, 0px)' }]]);
    cards.forEach(function (card, side) {
      var r = rects[side], dir = side ? 1 : -1, seat = seats[side];
      var fighter = node('div', 'wc-fighter wc-fighter--' + (side ? 'right' : 'left'), stage);
      fighter.style.cssText = 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
      var glow = node('i', 'wc-fighter-glow', fighter), trail = node('i', 'wc-fighter-trail', fighter);
      [0.16, 0.34, 0.5, 0.66, 0.84].forEach(function (y, i) {
        var streak = node('i', 'wc-fighter-streak', trail);
        streak.style.cssText = 'top:' + y * 100 + '%;width:' + [70, 100, 55, 90, 65][i] + '%';
      });
      var face = node('div', 'wc-fighter-face', fighter);
      [].forEach.call(card.childNodes, function (child) { face.appendChild(child.cloneNode(true)); });
      var homeX = r.left + r.width / 2, homeY = r.top + r.height / 2, half = r.width * z / 2;
      // A pose on the stage, as a move from the card's own place; the last one is the card itself.
      function at(x, rot, sx, sy) { return { transform: pose(x - homeX, seat.y - homeY, rot, sx * z, (sy == null ? sx : sy) * z) }; }
      var off = half + r.height * z * 0.17 + 48;        // tilted, with its glow, still wholly off screen
      track(fighter, [[780, at(dir < 0 ? -off : w + off, dir * -9, 1.04, 0.97), EASE.rush],
                      [IMPACT, at(seat.x - dir * push, dir * -2 * lean, 0.88, 1.06)],
                      [IMPACT + STOP, at(seat.x - dir * push, dir * -2 * lean, 0.88, 1.06), EASE.out],
                      [IMPACT + STOP + 90, at(seat.x + dir * kick, dir * 4 * lean, lean < 1 ? 1.02 : 1.05, 0.97), EASE.bouncy],
                      [1480, at(seat.x, 0, 1, 1)],
                      [1560, at(seat.x, 0, 1, 1), EASE.soft],
                      [1960, { transform: pose(0, 0, 0, 1) }]]);
      track(trail, [[780, { transform: 'scaleX(0.4)', opacity: 0 }], [840, { transform: 'scaleX(1)', opacity: 1 }],
                    [IMPACT - 30, { transform: 'scaleX(1)', opacity: 1 }], [IMPACT + 20, { transform: 'scaleX(0.2)', opacity: 0 }]]);
      track(glow, [[780, { opacity: 1 }], [1560, { opacity: 1 }, EASE.io], [1800, { opacity: 0 }]]);
    });
    var vsBox = node('div', 'wc-splash-center', stage), vs = node('p', 'wc-splash-vs', vsBox);
    vs.textContent = t('wc.vs', 'VS');
    var vsSize = Math.min(w * (diagonal ? 0.32 : 0.27), h * 0.23, 190);
    vs.style.fontSize = vsSize + 'px';
    // On the diagonal the lower card's name sits at the seam, so the VS lands just above that
    // name (with room for its bounce), on the upper card's photo; side by side it sits on the
    // seam, below both names.
    var nameTop = cards[1].querySelector('.wc-card-name').getBoundingClientRect().top - rects[1].top;
    var vsY = diagonal ? seats[1].y - cardHeight * z / 2 + nameTop * z - 6 - vsSize * 0.66 - cy : 0;
    var real = document.querySelector('.wc-vs').getBoundingClientRect();
    var to = real.width ? pose(real.left + real.width / 2 - cx, real.top + real.height / 2 - cy, 0, Math.max(0.12, real.height / vsSize * 1.2))
      : pose(0, 0, 0, 0.3);
    track(vs, [[IMPACT + 30, { transform: pose(0, vsY, -14, 3.2), opacity: 0 }, EASE.in],
               [IMPACT + 150, { transform: pose(0, vsY, 4, 0.82), opacity: 1 }, 'ease-out'],
               [IMPACT + 230, { transform: pose(0, vsY, -2, 1.12), opacity: 1 }, 'ease-in-out'],
               [IMPACT + 320, { transform: pose(0, vsY, 0, 1), opacity: 1 }],
               [1560, { transform: pose(0, vsY, 0, 1), opacity: 1 }, EASE.io],
               [1880, { transform: to, opacity: 0 }]]);
  }
  function showSplash(round) {
    var spec = SPLASH[round];
    endSplash('quiet');
    var run = ++splashRun;
    splash = { anims: [], width: window.innerWidth, run: run, round: round };
    busy = true;
    try {
      if (splashEl.getAnimations) splashEl.getAnimations().forEach(function (a) { a.cancel(); });   // an earlier skip's fade
      splashEl.textContent = '';
      splashEl.setAttribute('data-round', String(round));
      splashEl.showPopover();
      var w = splashEl.clientWidth, h = splashEl.clientHeight;
      var bg = node('i', 'wc-splash-bg', splashEl), stage = node('div', 'wc-splash-stage', splashEl);
      var fade = round === 2 ? [1640, 1960] : [650, 800];
      // A cut to black (the new pair is never glimpsed first), and a short fade back to the match.
      track(bg, [[0, { opacity: 1 }], [fade[0], { opacity: 1 }, EASE.in], [fade[1], { opacity: 0 }]]);
      splashTitle(stage, spec, w, h, round === 2);
      if (round === 2) crash(stage, w, h);
      else {                                            // the title lands with a small jolt
        track(stage, [[170, { transform: 'translate(0px, 0px)' }], [200, { transform: 'translate(0px, 4px)' }],
                      [235, { transform: 'translate(0px, -2px)' }], [270, { transform: 'translate(0px, 1px)' }],
                      [300, { transform: 'translate(0px, 0px)' }]]);
      }
      // The clock: when it runs out (or a test finishes it) the splash ends; if it never does
      // (paused, throttled, broken), a timer ends it anyway.
      var clock = splashEl.animate(null, { duration: spec.ms });
      clock.onfinish = function () { if (splash && splash.run === run) endSplash('end'); };
      splash.anims.push(clock);
      splash.safety = setTimeout(function () { if (splash && splash.run === run) endSplash('end'); }, spec.ms + 1500);
    } catch (e) {
      endSplash('quiet');
    }
  }
  // 'end' (it played out) and 'skip' (a tap or a key) put focus on the first card; a skip fades
  // the frozen frame out quickly, still catching taps meanwhile. 'quiet' (a hidden tab, a new
  // width, scrolling, the language switch, a failure) leaves focus where it is.
  function endSplash(reason) {
    var s = splash;
    if (!s) return;
    splash = null;
    clearTimeout(s.safety);
    cards.forEach(function (card) { card.style.opacity = card.style.transform = card.style.transition = ''; });
    busy = false;
    if (reason !== 'quiet' && view === 'match') cards[0].focus({ preventScroll: true });
    function close() {
      if (splashRun !== s.run) return;                  // a newer splash owns the popover now
      s.anims.forEach(function (a) { a.onfinish = null; a.cancel(); });
      if (splashEl.matches(':popover-open')) splashEl.hidePopover();
      splashEl.textContent = '';
    }
    if (reason !== 'skip') { close(); return; }
    quietUntil = Date.now() + 350;
    // The frozen frame fades out; the real match under it (the gacha's fade-in) shows at once.
    s.anims.forEach(function (a) {
      a.onfinish = null;
      if (a.effect && a.effect.target && !splashEl.contains(a.effect.target)) a.cancel(); else a.pause();
    });
    try {
      var fade = splashEl.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: 'ease-out', fill: 'forwards' });
      s.anims.push(fade);
      fade.onfinish = close;
    } catch (e) { close(); return; }
    setTimeout(close, 400);
  }

  // ---- celebration ---------------------------------------------------------------------------
  // Confetti on a full-window canvas that ignores the pointer and removes itself; nothing with
  // reduced motion. A pick gets a small burst from the card, the winner two big ones.
  var COLORS = ['#ec4899', '#a855f7', '#6366f1', '#06b6d4', '#fde047', '#f9a8d4', '#c4b5fd'];   // the brand mix
  var SPARKS = ['#ffffff', '#ec4899', '#a855f7', '#6366f1', '#f9a8d4', '#ffffff', '#c4b5fd'];   // the splash's crash
  function confetti(origins, count, duration, host, colors) {
    if (reduced) return;
    var canvas = document.createElement('canvas');
    canvas.className = 'wc-confetti';
    canvas.setAttribute('aria-hidden', 'true');
    (host || document.body).appendChild(canvas);
    colors = colors || COLORS;
    var ratio = Math.min(window.devicePixelRatio || 1, 2), w = window.innerWidth, h = window.innerHeight;
    canvas.width = w * ratio;
    canvas.height = h * ratio;
    var ctx = canvas.getContext('2d');
    ctx.scale(ratio, ratio);
    var bits = [];
    origins.forEach(function (o) {
      for (var i = 0; i < count; i++) {
        bits.push({ x: o.x, y: o.y, vx: (Math.random() - 0.5) * o.spread + o.drift, vy: -(Math.random() * o.lift + o.lift / 2),
                    size: 5 + Math.random() * 6, rot: Math.random() * 6.28, spin: (Math.random() - 0.5) * 0.3,
                    color: colors[i % colors.length], shape: i % 3 });
      }
    });
    var started = null;
    function frame(now) {
      if (started === null) started = now;
      var age = now - started;
      ctx.clearRect(0, 0, w, h);
      bits.forEach(function (b) {
        b.vy += 0.32; b.vx *= 0.99; b.x += b.vx; b.y += b.vy; b.rot += b.spin;
        ctx.save();
        ctx.translate(b.x, b.y);
        ctx.rotate(b.rot);
        ctx.globalAlpha = Math.max(0, 1 - age / duration);
        ctx.fillStyle = b.color;
        if (b.shape === 1) { ctx.beginPath(); ctx.arc(0, 0, b.size / 2.4, 0, 6.283); ctx.fill(); }
        else ctx.fillRect(-b.size / 2, -b.size / 4, b.size, b.shape ? b.size / 2 : b.size / 3);
        ctx.restore();
      });
      if (age < duration) requestAnimationFrame(frame); else canvas.remove();
    }
    requestAnimationFrame(frame);
  }
  function burst(card) {
    var r = card.getBoundingClientRect();
    confetti([{ x: r.left + r.width / 2, y: r.top + r.height * 0.45, spread: 10, drift: 0, lift: 8 }], 28, 900);
  }
  function celebrate() {
    var w = window.innerWidth, h = window.innerHeight;
    confetti([{ x: w * 0.15, y: h * 0.7, spread: 9, drift: 4, lift: 13 },
              { x: w * 0.85, y: h * 0.7, spread: 9, drift: -4, lift: 13 }], 90, 2800);
    var box = $('wcResult');
    box.classList.remove('is-celebrating');
    void box.offsetWidth;
    box.classList.add('is-celebrating');
  }

  // ---- start gacha ---------------------------------------------------------------------------------
  // Owner 2026-10-14: pressing start opens a capsule machine for about 5 s, once per start (never on
  // 이어하기). 뽑는 중: the machine drops in and cranks three times; six of the drawn dishes pour out
  // as capsules that pop open on their photos while its screen counts to 32. 너의 최애는?: the
  // machine sinks, the first two dishes fly out, burst into photo cards and bump under a VS. Then
  // they fly onto the real match beneath, which is already stored, rendered, focused and announced.
  // It plays in the splash's popover on the splash's clock, with its skip and interrupts (a tap or a
  // key skips and never picks): one line of text at a time, no flash, no vibration, and nothing of
  // it with reduced motion, forced colours or no popover support. Only transform and opacity move.
  var GACHA = { crank: 260, cranks: 3, pour: 6, pourGap: 110, count: 1200, end: 4880 };
  var SHELLS = ['#ec4899', '#06b6d4', '#a855f7', '#fde047', '#6366f1', '#f9a8d4', '#ec4899', '#06b6d4'];
  var MACHINE = '<div class="wc-gacha-dome">' + new Array(8).join('<i class="wc-gacha-ball"></i>') + '</div>' +
    '<div class="wc-gacha-body"><span class="wc-gacha-screen"><span class="wc-gacha-count"></span></span>' +
    '<span class="wc-gacha-crank"></span><span class="wc-gacha-eye wc-gacha-eye--l"></span>' +
    '<span class="wc-gacha-eye wc-gacha-eye--r"></span><span class="wc-gacha-mouth"></span></div>';
  function canGacha() {
    return !reduced && !(forcedColors && forcedColors.matches) && !document.hidden
      && typeof splashEl.showPopover === 'function' && typeof splashEl.animate === 'function';
  }
  // A capsule: a dish photo in a white ring under half a coloured shell (span > span > img + i).
  function capsule(parent, id, color, px) {
    var cap = node('span', 'wc-cap', parent), inner = node('span', 'wc-cap-y', cap), img = node('img', 'wc-cap-photo', inner);
    var photo = photoOf(id);
    img.alt = '';
    img.decoding = 'async';
    if (photo) img.src = photo.image;
    node('i', 'wc-cap-shell', inner).style.setProperty('--c', color);
    cap.style.setProperty('--cap', px + 'px');
    return cap;
  }
  function showGacha() {
    endSplash('quiet');
    var run = ++splashRun, ids = game.entrants, G = GACHA;
    splash = { anims: [], width: window.innerWidth, run: run, round: 'start' };
    busy = true;
    try {
      if (splashEl.getAnimations) splashEl.getAnimations().forEach(function (a) { a.cancel(); });
      splashEl.textContent = '';
      splashEl.setAttribute('data-round', 'start');
      splashEl.showPopover();
      var W = splashEl.clientWidth, H = splashEl.clientHeight, cx = W / 2, cy = H / 2, phone = W <= 560;
      var bg = node('i', 'wc-splash-bg', splashEl), glow = node('i', 'wc-gacha-glow', splashEl);
      var stage = node('div', 'wc-splash-stage', splashEl);
      var line = node('p', 'wc-gacha-line', stage);
      line.textContent = fill(t('wc.gacha.drawing', '{game} 뽑는 중…'), { game: gameLabel(game.category) });
      var machine = node('div', 'wc-gacha', stage);
      machine.innerHTML = MACHINE;
      var k = Math.max(0.6, Math.min(phone ? 0.92 : 1.2, (H - 230) / 330, (W - 24) / 260));
      machine.style.setProperty('--k', String(k));
      var strip = [];
      for (var n = 0; n <= size; n++) strip.push((n < 10 ? '0' : '') + n);
      machine.querySelector('.wc-gacha-count').textContent = strip.join('\n');
      var caps = node('div', 'wc-gacha-caps', stage), duel = node('div', 'wc-gacha-caps', stage);
      var ask = node('p', 'wc-gacha-ask', stage);
      node('span', '', ask).textContent = t('wc.gacha.ask', '너의 최애는?');
      var badge = node('div', 'wc-gacha-vs', stage);
      node('b', '', badge).textContent = t('wc.vs', 'VS');
      var skip = node('p', 'wc-gacha-skip', splashEl);
      node('span', '', skip).textContent = t('wc.gacha.skip', '건너뛰기');
      node('span', 'wc-gacha-skip-icon', skip).textContent = '⏭';

      // One read pass before any animation: the machine's mouth and floor, and the real match.
      var mouth = machine.querySelector('.wc-gacha-mouth').getBoundingClientRect(), body = machine.getBoundingClientRect();
      var mx = mouth.left + mouth.width / 2, my = mouth.top + mouth.height / 2, floor = body.bottom + 26 * k;
      var photos = cards.map(function (card) { return card.querySelector('.wc-photo').getBoundingClientRect(); });
      var realVs = document.querySelector('.wc-vs'), vsBox = realVs.getBoundingClientRect();
      var ratio = photos[0].width ? photos[0].height / photos[0].width : (phone ? 1 : 0.75);
      var fw = Math.min(photos[0].width || (phone ? 150 : 260), W * 0.42, H * 0.34 / ratio), fh = fw * ratio;
      var seat = fw / 2 + (phone ? 10 : 28), contact = fw / 2 - 3;
      var T0 = 450, tP = T0 + G.cranks * G.crank, tR = tP + 110, tD = tR + G.count, tE = tD + 960, tF = tE + 620;

      // The night stage and its glow, until the cards are on their way to the match.
      track(bg, [[0, { opacity: 0 }, EASE.out], [220, { opacity: 1 }], [tF, { opacity: 1 }, EASE.io], [tF + 300, { opacity: 0 }]]);
      track(glow, [[0, { opacity: 0 }], [300, { opacity: 1 }], [tF, { opacity: 1 }], [tF + 250, { opacity: 0 }]]);
      track(line, [[200, { transform: 'translateY(8px)', opacity: 0 }, EASE.out], [400, { transform: 'translateY(0px)', opacity: 1 }],
                   [tD, { transform: 'translateY(0px)', opacity: 1 }], [tD + 120, { transform: 'translateY(0px)', opacity: 0 }]]);
      track(skip, [[500, { opacity: 0 }], [800, { opacity: 1 }], [tF, { opacity: 1 }], [tF + 200, { opacity: 0 }]]);

      // 등장 (drops in with a squash), 퐁 (squashes as it pours), then it sinks out of the way.
      var sunk = { transform: pose(0, H * 0.24, 0, 0.8), opacity: 0.2 };
      track(machine, [[0, { transform: pose(0, -48, 0, 0.92), opacity: 0 }, 'cubic-bezier(0.5, 0, 1, 0.6)'],
                      [264, { transform: pose(0, 0), opacity: 1 }], [336, { transform: pose(0, 0, 0, 1.08, 0.9), opacity: 1 }, EASE.out],
                      [408, { transform: pose(0, 0, 0, 0.97, 1.04), opacity: 1 }], [480, { transform: pose(0, 0), opacity: 1 }],
                      [tP, { transform: pose(0, 0), opacity: 1 }, 'ease-in'], [tP + 110, { transform: pose(0, 0, 0, 1.08, 0.88), opacity: 1 }],
                      [tP + 144, { transform: pose(0, 0, 0, 0.94, 1.1), opacity: 1 }, EASE.bouncy], [tP + 480, { transform: pose(0, 0), opacity: 1 }],
                      [tD + 100, { transform: pose(0, 0), opacity: 1 }, EASE.io], [tD + 420, sunk], [tF, sunk],
                      [tF + 180, { transform: sunk.transform, opacity: 0 }]]);
      // 가샤: each turn of the crank jiggles the balls, shakes the body and makes the machine squint.
      var crank = [], shake = [], eyes = [], balls = [[], [], [], [], [], [], []];
      for (var c = 0; c < G.cranks; c++) {
        var at = T0 + c * G.crank, amp = [0.6, 0.8, 1][Math.min(c, 2)];
        crank.push([at, { transform: 'rotate(' + c * 180 + 'deg)' }, EASE.io], [at + 200, { transform: 'rotate(' + (c + 1) * 180 + 'deg)' }]);
        [0, 3, -3, 2, -1, 0].forEach(function (x, i) { shake.push([at + i * 48, { transform: 'translateX(' + x * amp + 'px)' }]); });
        eyes.push([at, { transform: 'scaleY(1)' }], [at + 88, { transform: 'scaleY(0.25)' }], [at + 220, { transform: 'scaleY(1)' }]);
        balls.forEach(function (steps, i) {
          var d = (i % 2 ? 1 : -1) * amp, b = at + i * 10;
          steps.push([b, { transform: 'none' }, 'ease-in-out'], [b + 60, { transform: pose(7 * d, -6 * amp, 14 * d) }, 'ease-in-out'],
                     [b + 120, { transform: pose(-5 * d, 3 * amp, -10 * d) }, 'ease-in-out'],
                     [b + 180, { transform: pose(3 * d, -2 * amp, 5 * d) }, 'ease-in-out'], [b + 240, { transform: 'none' }]);
        });
      }
      track(machine.querySelector('.wc-gacha-crank'), crank);
      track(machine.querySelector('.wc-gacha-body'), shake);
      [].forEach.call(machine.querySelectorAll('.wc-gacha-eye'), function (eye) { track(eye, eyes); });
      [].forEach.call(machine.querySelectorAll('.wc-gacha-ball'), function (ball, i) { track(ball, balls[i]); });
      track(machine.querySelector('.wc-gacha-mouth'), [[tR, { transform: 'scaleY(1)' }], [tR + 76, { transform: 'scaleY(1.35)' }],
                                                      [tR + 684, { transform: 'scaleY(1.35)' }], [tR + 760, { transform: 'scaleY(1)' }]]);
      track(machine.querySelector('.wc-gacha-count'), [[tR, { transform: 'translateY(0px)' }, 'steps(' + size + ', end)'],
                                                      [tR + G.count, { transform: 'translateY(' + -size * 38 + 'px)' }]]);
      track(machine.querySelector('.wc-gacha-screen'), [[tD, { transform: 'scale(1)' }, EASE.out], [tD + 96, { transform: 'scale(1.25)' }],
                                                       [tD + 320, { transform: 'scale(1)' }]]);
      // 퐁: dishes 3 to 8 of the draw pour from the mouth, arc out to the floor on alternating sides
      // and pop their shells at the top of the arc; then they sink with the machine.
      var xs = [-0.86, 0.38, -0.62, 0.86, -0.38, 0.62], px = Math.round(64 * k), half = Math.min(W, 560) / 2 - px / 2 - 4;
      for (var p = 0; p < G.pour; p++) {
        var cap = capsule(caps, ids[p + 2], SHELLS[p], px), from = tR + p * G.pourGap, x = xs[p], dx = cx + x * half - mx;
        var peak = -(120 + (p % 3) * 25) * k, land = floor - my - px / 2, turn = (x < 0 ? -1 : 1) * (300 + p * 30);
        cap.style.left = mx + 'px';
        cap.style.top = my + 'px';
        track(cap, [[from, { transform: 'translate(0px, 0px)', opacity: 0 }], [from + 42, { transform: 'translate(' + dx * 0.08 + 'px, 0px)', opacity: 1 }],
                    [from + 520, { transform: 'translate(' + dx + 'px, 0px)', opacity: 1 }], [tD + 100, { transform: 'translate(' + dx + 'px, 0px)', opacity: 1 }, EASE.io],
                    [tD + 420, { transform: 'translate(' + dx + 'px, ' + H * 0.2 + 'px)', opacity: 0.18 }],
                    [tF, { transform: 'translate(' + dx + 'px, ' + H * 0.2 + 'px)', opacity: 0.18 }],
                    [tF + 180, { transform: 'translate(' + dx + 'px, ' + H * 0.2 + 'px)', opacity: 0 }]]);
        track(cap.firstChild, [[from, { transform: pose(0, 0, 0, 0.5) }, 'cubic-bezier(0.2, 0.6, 0.35, 1)'],
                               [from + 306, { transform: pose(0, peak, turn / 2) }, 'cubic-bezier(0.55, 0, 0.85, 0.35)'],
                               [from + 530, { transform: pose(0, land, turn) }], [from + 571, { transform: pose(0, land, turn, 1.18, 0.82) }],
                               [from + 626, { transform: pose(0, land - 14 * k, turn, 0.96, 1.04) }], [from + 680, { transform: pose(0, land, turn) }]]);
        track(cap.firstChild.lastChild, [[from + 234, { transform: 'none', opacity: 1 }, EASE.out],
                                         [from + 494, { transform: pose(x < 0 ? -18 : 18, -26, x < 0 ? -40 : 40), opacity: 0 }]]);
      }
      // 너의 최애는?: the question stamps in, the first two dishes fly from the mouth to their seats,
      // burst, and photo cards of the first match take their place.
      track(ask, [[tD + 200, { transform: 'scale(1.6)', opacity: 0 }, EASE.back], [tD + 460, { transform: 'scale(1)', opacity: 1 }],
                  [tE, { transform: 'scale(1)', opacity: 1 }, EASE.io], [tE + 200, { transform: 'translateY(-12px) scale(0.8)', opacity: 1 }],
                  [tF, { transform: 'translateY(-12px) scale(0.8)', opacity: 1 }], [tF + 180, { transform: 'translateY(-12px) scale(0.8)', opacity: 0 }]]);
      var dpx = Math.round(72 * k);
      [0, 1].forEach(function (side) {
        var sign = side ? 1 : -1, go = tD + 80 + side * 40, cap = capsule(duel, ids[side], SHELLS[side + 2], dpx);
        var tx = cx + sign * seat - mx, ty = cy - my;
        cap.style.left = mx + 'px';
        cap.style.top = my + 'px';
        track(cap, [[go, { transform: 'translate(0px, 0px) scale(1)', opacity: 0 }], [go + 42, { transform: 'translate(' + tx * 0.1 + 'px, 0px) scale(1)', opacity: 1 }],
                    [go + 420, { transform: 'translate(' + tx + 'px, 0px) scale(1)', opacity: 1 }], [tD + 560, { transform: 'translate(' + tx + 'px, 0px) scale(1)', opacity: 1 }],
                    [tD + 700, { transform: 'translate(' + tx + 'px, 0px) scale(1.3)', opacity: 0 }]]);
        track(cap.firstChild, [[go, { transform: pose(0, 0, 0, 0.6) }, 'cubic-bezier(0.2, 0.6, 0.35, 1)'],
                               [go + 252, { transform: pose(0, Math.min(0, ty) - 60, sign * 200, 1.1) }, 'cubic-bezier(0.55, 0, 0.85, 0.35)'],
                               [go + 420, { transform: pose(0, ty, sign * 360) }]]);
        var card = node('figure', 'wc-duelist', stage), photo = photoOf(ids[side]), img = node('img', '', card);
        img.alt = '';
        if (photo) img.src = photo.image;
        card.style.cssText = 'left:' + cx + 'px;top:' + cy + 'px;width:' + fw + 'px;height:' + fh + 'px;margin:' + -fh / 2 + 'px 0 0 ' + -fw / 2 + 'px';
        var r = photos[side], rest = pose(sign * seat, 0, sign * 3);
        var to = r.width ? pose(r.left + r.width / 2 - cx, r.top + r.height / 2 - cy, 0, r.width / fw, r.height / fh) : rest;
        // Pop in, wind up, bump into each other (a short stop at contact), bounce back, settle, fly.
        track(card, [[tD + 560, { transform: pose(sign * seat, 0, sign * 6, 0.3), opacity: 0 }, EASE.bouncy],
                     [tD + 940, { transform: pose(sign * seat, 0, sign * 6), opacity: 1 }],
                     [tE, { transform: pose(sign * seat, 0, sign * 6), opacity: 1 }, EASE.out],
                     [tE + 130, { transform: pose(sign * (seat + 14), 0, sign * 9, 0.94, 1.04), opacity: 1 }, EASE.in],
                     [tE + 260, { transform: pose(sign * contact, 0, 0, 0.9, 1.08), opacity: 1 }],
                     [tE + 330, { transform: pose(sign * contact, 0, 0, 0.9, 1.08), opacity: 1 }, EASE.out],
                     [tE + 420, { transform: pose(sign * (fw / 2 + 20), 0, -sign * 3, 1.03, 0.98), opacity: 1 }, EASE.bouncy],
                     [tE + 600, { transform: rest, opacity: 1 }], [tF, { transform: rest, opacity: 1 }, EASE.soft],
                     [tF + 370, { transform: to, opacity: 1 }], [tF + 450, { transform: to, opacity: 0 }]]);
      });
      // VS: stamps at the bump, then flies onto the real VS.
      var vsTo = vsBox.width ? pose(vsBox.left + vsBox.width / 2 - cx, vsBox.top + vsBox.height / 2 - cy, 0, Math.max(0.3, vsBox.height / 76))
        : pose(0, 0, 0, 0.3);
      track(badge, [[tE + 258, { transform: 'scale(0)', opacity: 0 }], [tE + 260, { transform: 'scale(0)', opacity: 1 }, EASE.out],
                    [tE + 392, { transform: 'scale(1.15)', opacity: 1 }], [tE + 480, { transform: 'scale(1)', opacity: 1 }],
                    [tF + 80, { transform: 'scale(1)', opacity: 1 }, EASE.io], [tF + 400, { transform: vsTo, opacity: 0 }]]);
      track(stage, [[tE + 260, { transform: 'translate(0px, 0px)' }], [tE + 290, { transform: 'translate(4px, 0px)' }],
                    [tE + 325, { transform: 'translate(-3px, 0px)' }], [tE + 360, { transform: 'translate(2px, 0px)' }],
                    [tE + 400, { transform: 'translate(0px, 0px)' }]]);
      cue(tE + 260, function () {
        confetti([{ x: cx, y: cy, spread: 12, drift: 0, lift: 8 }], phone ? 18 : 26, 700, splashEl, SPARKS);
      });
      // The real match fades in under the landing cards, and its VS pops.
      cards.concat([].slice.call(document.querySelectorAll('.wc-slot .wc-credit'))).forEach(function (el) {
        track(el, [[tF + 330, { opacity: 0 }, EASE.out], [tF + 450, { opacity: 1 }]]);
      });
      track(realVs, [[tF + 450, { scale: '0', opacity: 0 }, EASE.bouncy], [tF + 690, { scale: '1', opacity: 1 }]]);

      var clock = splashEl.animate(null, { duration: G.end });
      clock.onfinish = function () { if (splash && splash.run === run) endSplash('end'); };
      splash.anims.push(clock);
      splash.safety = setTimeout(function () { if (splash && splash.run === run) endSplash('end'); }, G.end + 1500);
    } catch (e) {
      endSplash('quiet');
    }
  }

  // ---- result image ----------------------------------------------------------------------------
  // A 1080x1350 card (the winner, its photo and the photo credit, the site) to keep or post.
  function fitText(ctx, text, x, y, max, px, weight) {
    var font = function (n) { return weight + ' ' + n + "px 'Noto Sans KR', 'Apple SD Gothic Neo', sans-serif"; };
    ctx.font = font(px);
    while (px > 28 && ctx.measureText(text).width > max) { px -= 4; ctx.font = font(px); }
    ctx.fillText(text, x, y);
  }
  function saveImage() {
    var status = $('wcShareStatus'), photo = (cup.photos || {})[result.id];
    var canvas = document.createElement('canvas');
    canvas.width = 1080;
    canvas.height = 1350;
    var ctx = canvas.getContext('2d');
    function draw(img) {
      ctx.fillStyle = '#fffdf8';
      ctx.fillRect(0, 0, 1080, 1350);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#be185d';
      fitText(ctx, gameLabel(result.category) + ' · ' + t('wc.cardKicker', '나의 최애 메뉴'), 540, 120, 900, 40, 800);
      ctx.fillStyle = '#1e1d1a';
      fitText(ctx, name(result.id), 540, 250, 960, 104, 900);
      ctx.fillStyle = '#6d665e';
      fitText(ctx, otherName(result.id), 540, 320, 960, 40, 500);
      if (img) {
        ctx.save();
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(60, 380, 960, 720, 36); else ctx.rect(60, 380, 960, 720);
        ctx.clip();
        ctx.drawImage(img, 60, 380, 960, 720);
        ctx.restore();
        ctx.fillStyle = '#6d665e';
        fitText(ctx, fill(t('wc.photoCredit', '사진 {author} · {license}'), { author: photo.author, license: photo.license }),
                540, 1150, 960, 26, 500);
      }
      ctx.fillStyle = '#1e1d1a';
      fitText(ctx, t('wc.cardBrand', '밥도둑 먹방 월드컵'), 540, 1240, 960, 44, 800);
      ctx.fillStyle = '#6d665e';
      fitText(ctx, location.host, 540, 1295, 960, 30, 500);
      canvas.toBlob(function (blob) {
        if (!blob) { status.textContent = t('wc.shareFailed', '공유하지 못했어요.'); return; }
        var file = typeof File === 'function' ? new File([blob], 'babdoduk-worldcup.jpg', { type: 'image/jpeg' }) : null;
        // Phones get the share sheet (straight to a story or a chat); a computer saves the file.
        var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
        if (touch && file && navigator.canShare && navigator.canShare({ files: [file] })) {
          navigator.share({ files: [file], title: document.title }).catch(function () {});
          return;
        }
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'babdoduk-worldcup.jpg';
        document.body.appendChild(link);
        link.click();
        setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
        status.textContent = t('wc.saved', '저장했어요');
      }, 'image/jpeg', 0.9);
    }
    var fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    fonts.then(function () {
      if (!photo) { draw(null); return; }
      var img = new Image();
      img.onload = function () { draw(img); };
      img.onerror = function () { draw(null); };
      img.src = photo.image;
    });
  }
  function undo() {
    if (!game || !game.stack.length || busy) return;
    var previous = game.stack.pop();
    if (previous.game) {
      if (validGame(previous.game)) {                            // takes back 처음부터
        game = previous.game;
        game.category = savedCategory(game);
        category = game.category;
      }
    } else {
      game.entrants = previous.entrants;
      game.winners = previous.winners;
      if (game.log) game.log.length = previous.log || 0;
    }
    store();
    renderMatch(true);
  }
  function share() {
    var text = fill(t('wc.shareText', '나의 먹방 월드컵({cat}) 우승 메뉴는 {dish}!'),
      { cat: catName(result.category), dish: name(result.id) });
    var url = location.origin + location.pathname;
    var status = $('wcShareStatus');
    if (navigator.share) {
      navigator.share({ title: document.title, text: text, url: url }).catch(function () {});
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text + ' ' + url).then(function () {
        status.textContent = t('wc.copied', '결과와 링크를 복사했어요');
      }, function () {
        status.textContent = t('wc.shareFailed', '공유하지 못했어요.');
      });
      return;
    }
    status.textContent = t('wc.shareFailed', '공유하지 못했어요.');
  }
  function clearHistory() {
    winners = [];
    store();
    renderHistory();
  }

  // ---- data ----------------------------------------------------------------------------------
  function getJson(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error('unavailable');
      return response.json();
    });
  }
  // The address that starts a game at once: worldcup.html?cat=<category>&go=1 (the news page's start).
  // Only go=1 starts anything; an unknown or missing category is the whole pool. The address is
  // cleaned afterwards, so a reload shows the start screen (or the game in progress) rather than
  // dealing another game.
  function requested() {
    if (embedded || !window.URLSearchParams) return null;
    var query = new URLSearchParams(location.search);
    if (query.get('go') !== '1') return null;
    var cat = query.get('cat');
    return CATEGORIES.indexOf(cat) >= 0 && poolOf(cat).length >= size ? cat : 'all';
  }
  function cleanAddress() {
    try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) { /* keep the address */ }
  }
  function ready() {
    buildTiles();
    if (!embedded) restore();                  // the news page's card starts fresh, whatever is saved
    buildFloaters();
    show('intro');
    var asked = requested();
    if (asked) cleanAddress();
    choose(asked || category, false);          // the first draw: its photos shuffle in
    renderIntro();
    if (asked) {                               // as if 32강 시작 had been pressed here
      start(asked, true);
      return;
    }
    ambient(true);
    if (embedded) {
      $('wcIntro').parentNode.setAttribute('data-ready', '');
    }
    // The display font, fetched now so the gacha and the first splash do not start in the fallback.
    if (!reduced && document.fonts && document.fonts.load) {
      document.fonts.load('1em Jua', t('wc.gacha.ask', '너의 최애는?') + t('wc.splash.quarter', '8강 진출!')).catch(function () {});
    }
  }
  function failed() {
    if (embedded) {                            // the card falls back to its link
      [].forEach.call(document.querySelectorAll('[data-wc-embed]'), function (box) { box.setAttribute('data-failed', ''); });
      return;
    }
    show('loading');
    $('wcLoadingText').hidden = true;
    $('wcError').hidden = false;
  }

  cards.forEach(function (card, side) {
    card.addEventListener('click', function (e) {
      if (e.detail && Date.now() < quietUntil) return;   // a tap right after skipping a splash
      pick(side);
    });
  });
  // Every start but 이어하기 opens the gacha (never pass the click event as `animate`). 32강 시작 in
  // the middle of 아무거나 lands it first; 처음부터 waits for a pick's feedback to end.
  // In the news page's card 32강 시작 opens the game page with the chosen category, which starts it.
  function begin() {
    stopSpin(true);
    if (embedded) { location.href = 'worldcup.html?cat=' + encodeURIComponent(category) + '&go=1'; return; }
    start(category, true);
  }
  $('wcStart').addEventListener('click', begin);
  $('wcNew').addEventListener('click', begin);
  $('wcResume').addEventListener('click', function () { stopSpin(false); resume(); });
  if (!embedded) {
    $('wcUndo').addEventListener('click', undo);
    $('wcRestart').addEventListener('click', function () { if (!busy) start(game ? game.category : category, true); });
    $('wcAgain').addEventListener('click', function () { start(result ? result.category : category, true); });
    $('wcShare').addEventListener('click', share);
    $('wcSaveImage').addEventListener('click', saveImage);
    $('wcHistoryClear').addEventListener('click', clearHistory);
  }
  document.addEventListener('babdoduk-lang', render);
  document.addEventListener('babdoduk-lang', function () { endSplash('quiet'); });

  // Skipping a splash. A tap anywhere (on the up event, so it is never a pick; the down event
  // keeps focus on the card); any key but a bare modifier, browser shortcuts still work. A key
  // held from the pick or through the skip neither skips again nor picks: its repeats and its
  // release are swallowed.
  if (splashEl) {
    splashEl.addEventListener('click', function () { endSplash('skip'); });
    splashEl.addEventListener('mousedown', function (e) { e.preventDefault(); });
    splashEl.addEventListener('wheel', function () { endSplash('quiet'); }, { passive: true });
  }
  document.addEventListener('keydown', function (e) {
    if (!splash) {
      if (heldKey && e.key === heldKey && e.repeat) { e.preventDefault(); e.stopPropagation(); }
      else if (!e.repeat) heldKey = null;
      return;
    }
    if (/^(Shift|Control|Alt|Meta|CapsLock)$/.test(e.key)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) { endSplash('quiet'); return; }
    e.preventDefault();
    e.stopPropagation();
    heldKey = e.key;
    if (!e.repeat) endSplash('skip');
  }, true);
  document.addEventListener('keyup', function (e) {
    if (!heldKey || e.key !== heldKey) return;
    e.preventDefault();                                 // Space would click the focused card on release
    e.stopPropagation();
    heldKey = null;
  }, true);
  window.addEventListener('blur', function () { heldKey = null; });
  document.addEventListener('visibilitychange', function () { if (document.hidden) endSplash('quiet'); });
  window.addEventListener('resize', function () { if (splash && window.innerWidth !== splash.width) endSplash('quiet'); });
  if (window.matchMedia) {
    var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var onMotion = function (e) {
      reduced = e.matches;
      if (reduced) { endSplash('skip'); stopAmbient(); stopSpin(true); }
    };
    if (motion.addEventListener) motion.addEventListener('change', onMotion);
    else if (motion.addListener) motion.addListener(onMotion);
  }

  function bracket() {
    set = (cup.dishes || []).filter(function (id) { return dishes[id]; });
    size = cup.size || set.length;
    if (size < 4 || (size & (size - 1)) || set.length < size) throw new Error('bracket');
  }
  // The names come from the food catalog; the news page's card carries them in its data instead.
  var loaded = embedded ? new Promise(function (resolve) {
    var rows = cup.dishes || {};                 // { id: [Korean name, English name, category] }
    cup.dishes = Object.keys(rows);
    cup.categories = {};
    cup.dishes.forEach(function (id) {
      dishes[id] = { id: id, nameKo: rows[id][0], nameEn: rows[id][1] };
      cup.categories[id] = rows[id][2];
    });
    bracket();
    resolve();
  }) : getJson('data/foods/catalog.json').then(function (catalog) {
    return Promise.all((catalog.packs || []).map(function (pack) { return getJson(pack.src); })).then(function (packs) {
      packs.forEach(function (pack) { (pack.items || []).forEach(function (dish) { dishes[dish.id] = dish; }); });
      bracket();
    });
  });
  loaded.then(ready, failed);
})();
