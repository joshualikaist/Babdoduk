/* Babdoduk food world cup (worldcup.html): each game draws `size` dishes (32) from the pool in
   data/content/worldcup.json (the sync writes it into the page as window.BABDODUK_WORLDCUP;
   data/content/ is never deployed) and plays them two at a time, with names and flavours from the
   food catalog (data/foods/). A pick pops; from the quarterfinals on a new round takes the screen
   for a beat (the final with a crash of the two finalists); the winner gets confetti and an
   Instagram story card (1080x1920) to save or share, with a link that challenges a friend
   (worldcup.html?from=<dish>&cat=<category>, docs/WORLDCUP_SHARE.md). Progress and past winners
   stay in this browser (localStorage `babdoduk-worldcup`); nothing is sent anywhere.
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
   only for go=1 with a known category; the address is then cleaned so a reload never restarts.
   The launch gate (owner 2026-10-14, js/worldcup-gate.js): before the world cup opens (`locked`) the
   start screen is a teaser only: the start button is a locked pill with a countdown, 이어하기 and
   go=1 do nothing and start() refuses. After the end it plays on, with a small note.
   Before the launch nothing of the draw is revealed (owner 2026-10-14: "최대한 공개 안하게끔"): the
   tiles and the preview sit in a mystery box that is blurred (css/worldcup-entry.css), inert and hidden
   from assistive tech, the floating and preview photos are blurred placeholders with no `src` (no
   photo is requested), and no tile is chosen. At the launch moment the real photos load.
   Sound (owner 2026-10-14): an original music loop and effects, synthesized in this file (no audio
   file), behind a 🔇/🔊 toggle that is off until pressed (see "---- sound"). worldcup.html only. */
(function () {
  'use strict';
  var KEY = 'babdoduk-worldcup';
  var HISTORY = 10;
  // Flavour and texture tags, most telling first; a card shows at most two (score 4 or 5).
  var TAGS = ['spicy', 'crispy', 'soupy', 'sweet', 'chewy', 'rich', 'umami', 'sour', 'salty', 'soft'];
  var cup = window.BABDODUK_WORLDCUP || {};
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var embedded = !document.getElementById('wcMatch');   // the news page's card: the start screen alone
  var gate = window.BabdodukWorldcup;                    // js/worldcup-gate.js; without it the game is open
  function locked() { return !!gate && gate.phase() === 'soon'; }
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
        if (cat === 'random') spinTiles();
        else { sound.fx('pop'); choose(cat, true); }
      });
    });
  }
  function renderTiles() {
    [].forEach.call($('wcCats').querySelectorAll('.wc-tile'), function (tile) {
      var cat = tile.getAttribute('data-cat');
      tile.querySelector('.wc-tile-name').textContent = cat === 'random' ? t('wc.cat.random', '아무거나') : catName(cat);
      tile.querySelector('.wc-tile-n').textContent = cat === 'random' ? t('wc.cat.randomSub', '랜덤!')
        : fill(t('wc.catCount', '{n}개'), { n: poolOf(cat).length });
      if (cat === 'random') return;
      if (locked()) tile.removeAttribute('aria-pressed');          // a mystery box: nothing is chosen yet
      else tile.setAttribute('aria-pressed', cat === category ? 'true' : 'false');
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
      img.alt = '';
      img.width = 160;
      img.height = 160;
      img.decoding = 'async';
      if (!locked()) {                                             // before the launch: a blurred placeholder, no name, no photo, no request
        img.alt = name(id);
        img.setAttribute('data-id', id);
        img.onerror = function () { item.hidden = true; };
        img.src = photo.image;
      }
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
      sound.fx('tick');
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
    sound.fx('ding');
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
    // Before the launch only the locked pill shows (the gate fills it in), whatever is saved.
    var resumable = !!game && !locked();
    $('wcStart').hidden = resumable || locked();
    $('wcResume').hidden = $('wcNew').hidden = !resumable;
    if (gate) gate.refresh();
    // The tiles and the preview are a mystery box before the launch: nothing in it can be focused or read out.
    var box = $('wcMysteryBody');
    if (box) {
      if (locked()) { box.setAttribute('inert', ''); box.setAttribute('aria-hidden', 'true'); }
      else { box.removeAttribute('inert'); box.removeAttribute('aria-hidden'); }
    }
    renderFriend();
    if (resumable) $('wcResumeLabel').textContent = fill(t('wc.resume', '이어하기 · {cat} {round} {n}/{total}'), progress());
    [].forEach.call($('wcPreviewPhotos').querySelectorAll('img[data-id]'), function (img) { img.alt = name(img.getAttribute('data-id')); });
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
      if (photo && !locked()) img.src = photo.image;               // before the launch a blurred placeholder, no request
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
    var button = game && !locked() ? $('wcResume') : $('wcStart'), breath = { duration: 1400, delay: arriving ? 600 : 120,
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
    prepareStory();                            // the story card is made now, so a tap can hand it over at once
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
    if (locked()) return;                      // not before the launch, by any path
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
    if (locked()) return;
    if (!game) { start(category, false); return; }
    show('match');
    renderMatch(true);
  }
  function finish(winner, finalist) {
    winners.unshift({ id: winner, finalist: finalist, date: todayKst() });
    winners = winners.slice(0, HISTORY);
    result = { id: winner, finalist: finalist, category: game.category, semis: semifinalists(winner, finalist) };
    game = null;
    store();
    show('result');
    renderResult(true);
    celebrate();
    sound.fx('fanfare', 150);
  }
  // The two dishes that lost in the semifinals, from the bracket's log (its last three matches are
  // the semifinals and the final); none when the log is incomplete (a game saved before it existed).
  function semifinalists(winner, finalist) {
    var log = game.log || [], n = log.length;
    if (n < 3) return [];
    var semis = [log[n - 3], log[n - 2]], won = semis.map(function (m) { return m && m[0]; });
    if (won.indexOf(winner) < 0 || won.indexOf(finalist) < 0) return [];
    return semis.map(function (m) { return m[1]; }).filter(function (id) { return !!dishes[id]; });
  }
  function pick(side) {
    if (splash) { endSplash('skip'); return; }          // a screen reader's click on a card under the splash
    if (busy || view !== 'match') return;
    var ids = pair(), chosen = ids[side];
    sound.fx('blip', 0, game.winners.length / Math.max(1, game.entrants.length / 2 - 1));   // higher through the round
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
      sound.raise();
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
      // Its sound, on the same clock: the title whooshes in and lands; the finalists rush and crash.
      sound.scene(clock, round === 2 ? [['whoosh', 0], ['hit', 170], ['whoosh', 760, true], ['boom', 1100]]
        : [['whoosh', 0], ['hit', 170]]);
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
    sound.endScene(reason);                           // a skip silences what is left of its sound
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

  // ---- sound -------------------------------------------------------------------------------------
  // Owner 2026-10-14 ("배경음악 ... 킬 수 있도록"): an upbeat loop and a few effects, all original and
  // synthesized here with the Web Audio API: no audio file, no borrowed melody. soundKit() is the
  // instrument (it touches nothing of the page, so it can also render offline); `sound` plays it.
  //
  // The loop: F major, 124 BPM, 16 bars (31 s). A (bars 1-8, F Dm Bb C twice): four-on-the-floor,
  // offbeat hats, a syncopated bass, soft pads, bubbly arpeggio and the lead's hook, a snare fill
  // into B. B (bars 9-16, Bb C Am Dm Bb C F C): the chorus an octave up, with claps, open hats, an
  // octave-bouncing bass and offbeat chord stabs. Notes are scheduled a little ahead on the audio
  // clock from a short timer (a look-ahead clock), and everything goes through a compressor and a
  // limiter, so the mix stays modest and never clips.
  function soundKit(ctx) {
    var STEP = 60 / 124 / 4;                        // a 16th note
    var CHORDS = 'F Dm Bb C F Dm Bb C Bb C Am Dm Bb C F C'.split(' ');
    var VOICE = { F: [60, 65, 69], Dm: [62, 65, 69], Bb: [62, 65, 70], C: [60, 64, 67], Am: [60, 64, 69] };
    var ROOT = { F: 41, Dm: 38, Bb: 34, C: 36, Am: 33 };
    // The lead, one character per 16th: '1' to 'f' climb the F major scale from F4 to F6, '-' holds
    // the note before, '.' rests. A's hook, then B's chorus.
    var LEAD = 'a.a.c.a-..8.9.a.' + '9-8-6-..5.6.8.9.' + '8.8.b.8-..6.8.9.' + '7-5-7-9---..c.a.' +
               'a.a.c.a-..8.9.a.' + 'c-a-9-8-..9.a.d.' + 'd-c-a-8-..a.8.6.' + '7-9-c---9-7-5---' +
               'd.d.d.c-d-..b.c.' + 'c.c.c.a-9-..7.9.' + 'a.a.a.9-a-..c.e.' + 'd---c-a-d-..a.c.' +
               'd.d.d.c-d-..b.c.' + 'c.c.c.a-9-..c.d.' + 'f.e.c.a-c-..a.c.' + '9-7-5-7-9-------';
    var DEGREE = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24];
    var KICK = ['x...x...x...x...', 'x...x...x...x.x.'], HAT = ['..c...c...c...c.', 'c.o.c.o.c.o.c.oc'];
    var BASS = ['r..r..r.r..r..r.', 'r.o.r.o.r.o.r.o.'], STAB = '..x...x...x...x.';
    function hz(m) { return 440 * Math.pow(2, (m - 69) / 12); }
    var noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate), d = noise.getChannelData(0);
    for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;

    var comp = ctx.createDynamicsCompressor(), limit = ctx.createDynamicsCompressor(), master = ctx.createGain();
    comp.threshold.value = -20; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.01; comp.release.value = 0.2;
    limit.threshold.value = -6; limit.knee.value = 0; limit.ratio.value = 20; limit.attack.value = 0.001; limit.release.value = 0.1;
    master.gain.value = 0.6;
    comp.connect(limit); limit.connect(master); master.connect(ctx.destination);
    var music = ctx.createGain();
    music.gain.value = 0;
    music.connect(comp);
    function filter(type, f, q, dest) {
      var n = ctx.createBiquadFilter();
      n.type = type; n.frequency.value = f;
      if (q) n.Q.value = q;
      n.connect(dest);
      return n;
    }
    // One long-lived filter per instrument; a note only adds an oscillator and a gain.
    var lead = ctx.createGain(), echo = ctx.createDelay(1), feedback = ctx.createGain(), wet = ctx.createGain();
    echo.delayTime.value = STEP * 3; feedback.gain.value = 0.25; wet.gain.value = 0.18;   // a dotted-8th echo
    lead.connect(music); lead.connect(echo); echo.connect(feedback); feedback.connect(echo); echo.connect(wet); wet.connect(music);
    var HATS = filter('highpass', 7500, 0, music), SNARES = filter('bandpass', 1800, 0.7, music), LOW = filter('lowpass', 700, 1, music),
        PADS = filter('lowpass', 1400, 0.7, music), STABS = filter('lowpass', 2400, 0, music), BRIGHT = filter('lowpass', 3000, 0, lead);

    // An envelope: up to `peak` in `attack`, then down to silence by t + len (never a ramp to 0).
    function env(g, t, peak, len, attack) {
      attack = attack || 0.005;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(peak, t + attack);
      g.gain.exponentialRampToValueAtTime(0.0001, t + Math.max(len, attack + 0.01));
    }
    function tone(type, f, t, len, peak, dest, attack) {
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type;
      o.frequency.setValueAtTime(f, t);
      o.connect(g); g.connect(dest);
      env(g, t, peak, len, attack);
      o.start(t); o.stop(t + len + 0.05);           // a stopped, unreferenced node is collected
      return o;
    }
    function hiss(t, len, peak, dest, attack) {
      var s = ctx.createBufferSource(), g = ctx.createGain();
      s.buffer = noise;
      s.loop = true;
      s.connect(g); g.connect(dest);
      env(g, t, peak, len, attack || 0.002);
      s.start(t, Math.random() * 0.4); s.stop(t + len + 0.05);
    }
    function pad(f, t, len, peak) {                 // a held chord tone: in, held, out (linear, so it can reach 0)
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sawtooth';
      o.frequency.setValueAtTime(f, t);
      o.connect(g); g.connect(PADS);
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(peak, t + 0.15);
      g.gain.setValueAtTime(peak, t + len - 0.25);
      g.gain.linearRampToValueAtTime(0, t + len);
      o.start(t); o.stop(t + len + 0.05);
    }
    function kick(t, peak, dest) {
      tone('sine', 150, t, 0.3, peak, dest).frequency.exponentialRampToValueAtTime(46, t + 0.1);
    }
    function snare(t, peak) {
      hiss(t, 0.16, peak, SNARES);
      tone('triangle', 185, t, 0.08, peak * 0.5, music);
    }

    // The effects, each (time, destination, argument).
    var sfx = {
      pop: function (t, o) {                         // a tile: a jelly bloop that bends up
        tone('sine', 380, t, 0.12, 0.35, o).frequency.exponentialRampToValueAtTime(1100, t + 0.06);
        tone('triangle', 760, t, 0.05, 0.06, o);
      },
      blip: function (t, o, up) {                    // a pick: a two-step blip, higher through the round
        var m = [72, 74, 77, 79, 81, 84, 86, 89][Math.round(Math.max(0, Math.min(1, up || 0)) * 7)];
        tone('square', hz(m), t, 0.07, 0.1, filter('lowpass', 3000, 0, o));
        tone('triangle', hz(m + 12), t + 0.045, 0.14, 0.24, o);
      },
      tick: function (t, o) {                        // 아무거나: one step of the light
        tone('triangle', 1500, t, 0.03, 0.16, o);
        hiss(t, 0.012, 0.08, filter('highpass', 4000, 0, o));
      },
      ding: function (t, o) {                        // 아무거나 lands
        tone('triangle', hz(84), t, 0.25, 0.16, o);
        tone('triangle', hz(89), t + 0.09, 0.5, 0.18, o);
        tone('sine', hz(101), t + 0.09, 0.4, 0.04, o);
      },
      whoosh: function (t, o, long) {               // a round comes in: band-passed noise sweeping up
        var len = long ? 0.36 : 0.26, f = filter('bandpass', 300, 1.2, o), g = ctx.createGain(), s = ctx.createBufferSource();
        f.frequency.setValueAtTime(300, t);
        f.frequency.exponentialRampToValueAtTime(5000, t + len);
        s.buffer = noise; s.loop = true; s.connect(g); g.connect(f);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(long ? 0.5 : 0.4, t + len * 0.85);
        g.gain.linearRampToValueAtTime(0, t + len + 0.06);
        s.start(t, Math.random() * 0.3); s.stop(t + len + 0.1);
      },
      hit: function (t, o, soft) {                  // the round title lands: a thump, a burst, a chord stab
        var k = soft ? 0.5 : 1, stab = filter('lowpass', 2500, 0, o);
        kick(t, 0.75 * k, o);
        hiss(t, 0.25, 0.3 * k, filter('lowpass', 1800, 0, o));
        [65, 69, 72, 77].forEach(function (m) { tone('square', hz(m), t, 0.3, 0.045 * k, stab); });
      },
      boom: function (t, o) {                        // 결승: a deep boom, a sweep down, then a shimmer
        tone('sine', 100, t, 1.2, 0.9, o).frequency.exponentialRampToValueAtTime(28, t + 0.8);
        tone('sine', 55, t, 1.0, 0.35, o);
        var sweep = filter('lowpass', 3000, 0, o);
        sweep.frequency.setValueAtTime(3000, t);
        sweep.frequency.exponentialRampToValueAtTime(120, t + 0.7);
        hiss(t, 0.9, 0.5, sweep);
        hiss(t + 0.02, 1.6, 0.07, filter('highpass', 6000, 0, o));
        [1397, 1760, 2093, 2794, 3520, 4186].forEach(function (f, n) {
          tone('sine', f * (1 + (n % 2 ? 0.003 : -0.003)), t + 0.05 + n * 0.035, 1.4, 0.03, o, 0.02);
        });
      },
      crank: function (t, o) {                       // the gacha's crank: a ratchet of three clicks
        var hp = filter('highpass', 3000, 0, o);
        [0, 0.06, 0.12].forEach(function (dt) { hiss(t + dt, 0.015, 0.25, hp); tone('square', 900, t + dt, 0.012, 0.04, o); });
      },
      capsule: function (t, o, n) {                  // a capsule pops open, a step higher each time
        var m = [72, 74, 77, 79, 81, 84, 86, 89][Math.min(n || 0, 7)];
        tone('sine', hz(m) * 0.6, t, 0.1, 0.3, o).frequency.exponentialRampToValueAtTime(hz(m) * 1.6, t + 0.05);
        tone('triangle', hz(m + 12), t + 0.03, 0.25, 0.07, o);
      },
      tada: function (t, o) {                        // 너의 최애는?: ta (C), da (F)
        var lp = filter('lowpass', 3200, 0, o);
        [72, 76, 79].forEach(function (m) { tone('square', hz(m), t, 0.09, 0.04, lp); tone('triangle', hz(m), t, 0.09, 0.07, o); });
        [77, 81, 84, 89].forEach(function (m) { tone('square', hz(m), t + 0.14, 0.7, 0.035, lp, 0.01); tone('triangle', hz(m), t + 0.14, 0.7, 0.06, o, 0.01); });
        tone('sine', hz(101), t + 0.16, 0.4, 0.03, o);
      },
      fanfare: function (t, o) {                     // the winner: an original brassy call over an F chord
        var brass = filter('lowpass', 2200, 0, o);
        [[0, 72, 0.12], [0.12, 77, 0.12], [0.24, 81, 0.12], [0.36, 84, 0.3], [0.7, 81, 0.14], [0.86, 84, 0.14], [1.0, 89, 1.0]]
          .forEach(function (n) { tone('sawtooth', hz(n[1]), t + n[0], n[2], 0.14, brass, 0.02); tone('triangle', hz(n[1] - 12), t + n[0], n[2], 0.09, o, 0.02); });
        [65, 69, 72].forEach(function (m) { tone('sawtooth', hz(m), t + 1.0, 1.0, 0.05, brass, 0.03); });
        hiss(t + 1.0, 1.2, 0.07, filter('highpass', 6000, 0, o), 0.05);
      }
    };

    return {
      STEP: STEP, LENGTH: LEAD.length, music: music, sfx: sfx,
      bus: function () { var g = ctx.createGain(); g.connect(comp); return g; },
      step: function (pos, t) {                      // schedule one 16th of the loop at time t
        var s = pos % 16, bar = pos >> 4, b = bar < 8 ? 0 : 1, chord = CHORDS[bar], voice = VOICE[chord], c = LEAD[pos], n = 1;
        if (KICK[b][s] === 'x') kick(t, 0.85, music);
        if (s === 4 || s === 12) {
          snare(t, b ? 0.42 : 0.32);
          if (b) hiss(t + 0.012, 0.12, 0.2, SNARES);  // B: a clap on the snare
        }
        if ((bar === 7 && s >= 13) || (bar === 15 && s >= 14)) snare(t, 0.12 + (s - 12) * 0.06);   // fills into B and back to A
        if (bar === 7 && s === 8) {                  // a riser into B
          var rise = filter('bandpass', 500, 1, music);
          rise.frequency.setValueAtTime(500, t);
          rise.frequency.exponentialRampToValueAtTime(6000, t + STEP * 8);
          hiss(t, STEP * 8, 0.12, rise, STEP * 7);
        }
        if (bar === 8 && s === 0) hiss(t, 1.4, 0.1, HATS);   // a crash on the chorus
        if (HAT[b][s] !== '.') hiss(t, HAT[b][s] === 'o' ? 0.16 : 0.035, HAT[b][s] === 'o' ? 0.09 : 0.12, HATS);
        if (BASS[b][s] !== '.') tone('sawtooth', hz(ROOT[chord] + (BASS[b][s] === 'o' ? 12 : 0)), t, STEP * (b ? 1.4 : 1.8), 0.24, LOW);
        if (s === 0) voice.forEach(function (m) { pad(hz(m), t, STEP * 16, b ? 0.022 : 0.03); });
        if (b && STAB[s] === 'x') voice.forEach(function (m) { tone('square', hz(m + 12), t, 0.1, 0.022, STABS); });
        if (!b && s % 2 === 0) {                     // A: a bubbly arpeggio of the chord, on the 8ths
          var f = hz(voice[[0, 1, 2, 1][(s / 2) % 4]] + 12);
          tone('sine', f * 0.5, t, 0.12, 0.06, music).frequency.exponentialRampToValueAtTime(f, t + 0.03);
        }
        if (c !== '-' && c !== '.') {
          while (LEAD[(pos + n) % LEAD.length] === '-') n++;
          var note = hz(65 + DEGREE['123456789abcdef'.indexOf(c)]), len = STEP * n * 0.92;
          tone('triangle', note, t, len, 0.13, lead, 0.01);
          tone('square', note * 1.003, t, len * 0.8, 0.035, BRIGHT, 0.01);
          if (b) tone('sine', note * 2, t, len * 0.6, 0.025, lead, 0.01);
        }
      }
    };
  }
  // The player: nothing exists until sound is turned on by a press (browsers let audio start only
  // from a user gesture), then one AudioContext for the whole visit. Off by default; the choice is
  // kept in `babdoduk-worldcup-sound`, except with reduced motion, where every visit starts off.
  // A remembered "on" starts at the first press anywhere. Effects play only while it is on; the
  // music ducks under a round's scene and under the big hits, and sleeps while the tab is hidden.
  var sound = (function () {
    var AC = window.AudioContext || window.webkitAudioContext;
    var KEY = 'babdoduk-worldcup-sound', AHEAD = 0.12, WAKE = 25, LEVEL = 0.5;
    var DUCK = { hit: [0.35, 0.3], boom: [0.15, 0.9], tada: [0.5, 0.6], fanfare: [0.3, 1.8] };   // [music level, seconds]
    var dock = $('wcSoundDock'), button = $('wcSound');
    var supported = !!(AC && dock && button);
    var ctx = null, kit = null, fxBus = null, timer = 0, pos = 0, next = 0, level = LEVEL, wanted = false;
    var scene = null;          // the splash on screen: { clock, plan: [[effect, ms on its clock, argument]] }
    if (supported && !reduced) {
      try { wanted = localStorage.getItem(KEY) === '1'; } catch (e) { /* no storage: off */ }
    }
    function live() { return wanted && ctx && ctx.state !== 'closed' && !document.hidden; }
    function build() {
      ctx = new AC();
      kit = soundKit(ctx);
      fxBus = kit.bus();
    }
    function loop() {
      timer = 0;
      if (!ctx || ctx.state !== 'running' || !wanted) return;
      var now = ctx.currentTime;
      if (next < now) next = now + 0.05;             // after a stall, carry on rather than burst
      while (next < now + AHEAD) {
        kit.step(pos, next);
        pos = (pos + 1) % kit.LENGTH;
        next += kit.STEP;
      }
      timer = setTimeout(loop, WAKE);
    }
    function play() {                                // fade in from the start of the bar it stopped in
      if (timer) return;
      kit.music.gain.cancelScheduledValues(ctx.currentTime);
      kit.music.gain.setTargetAtTime(level, ctx.currentTime, 0.25);
      pos -= pos % 16;
      next = ctx.currentTime + 0.06;
      loop();
    }
    function wake() {                                // inside a press, or when the tab is back
      if (!wanted || document.hidden) return;
      if (!ctx) build();
      if (ctx.state === 'running') { play(); return; }
      ctx.resume().then(function () { if (wanted && !document.hidden) play(); }, function () { /* the next press retries */ });
    }
    function hush() {                                // silence effects already scheduled (a skip, sound off)
      if (!ctx) return;
      var old = fxBus;
      old.gain.setTargetAtTime(0, ctx.currentTime, 0.015);
      setTimeout(function () { old.disconnect(); }, 300);
      fxBus = kit.bus();
    }
    function stop() {
      clearTimeout(timer);
      timer = 0;
      if (!ctx) return;
      hush();
      kit.music.gain.cancelScheduledValues(ctx.currentTime);
      kit.music.gain.setTargetAtTime(0, ctx.currentTime, 0.08);
      var c = ctx;
      setTimeout(function () { if (!wanted && c.state === 'running') c.suspend(); }, 500);
    }
    function sync() { if (button) button.setAttribute('aria-pressed', String(wanted)); }
    function fx(name, ms, arg) {                     // an effect now, or `ms` from now, ahead by the output latency
      if (!live()) return;
      var now = ctx.currentTime, t = Math.max(now, now + (ms || 0) / 1000 - (ctx.outputLatency || ctx.baseLatency || 0));
      kit.sfx[name](t, fxBus, arg);
      var dip = DUCK[name];
      if (dip) {
        kit.music.gain.setTargetAtTime(level * dip[0], t, 0.015);
        kit.music.gain.setTargetAtTime(level, t + dip[1], 0.25);
      }
    }
    function duck(on) {
      level = on ? LEVEL * 0.55 : LEVEL;
      if (live() && timer) kit.music.gain.setTargetAtTime(level, ctx.currentTime, 0.12);
    }
    function cue() {                                 // the scene's effects still to come, timed by its clock
      if (!scene || !live()) return;
      var at = scene.clock.currentTime || 0;
      scene.plan.forEach(function (e) {
        if (e.done || e[1] < at - 30) return;
        e.done = true;
        fx(e[0], e[1] - at, e[2]);
      });
    }
    if (supported) {
      button.addEventListener('click', function () {
        wanted = !wanted;
        try { localStorage.setItem(KEY, wanted ? '1' : '0'); } catch (e) { /* kept for this visit only */ }
        if (wanted) wake(); else stop();
        sync();
        cue();                                       // turned on mid-scene: the rest of it
      });
      // A remembered "on" starts at the first press; a suspended context retries on the next one.
      ['pointerdown', 'pointerup', 'keydown', 'click'].forEach(function (type) {
        document.addEventListener(type, function () { if (wanted && (!ctx || ctx.state !== 'running' || !timer)) wake(); }, true);
      });
      document.addEventListener('visibilitychange', function () {
        if (!ctx) return;
        if (document.hidden) {
          clearTimeout(timer);
          timer = 0;
          if (ctx.state === 'running') ctx.suspend();
        } else wake();
      });
    }
    return {
      fx: fx,
      // The toggle in the corner, a manual popover in the top layer: shown on worldcup.html only.
      show: function () {
        if (!supported) return;
        dock.hidden = false;
        sync();
        this.raise();
      },
      // A splash opens above everything: the toggle is shown again, so it stacks above the splash.
      raise: function () {
        if (!supported || dock.hidden || typeof dock.showPopover !== 'function') return;
        var focused = document.activeElement === button;
        try {
          if (dock.matches(':popover-open')) dock.hidePopover();
          dock.showPopover();
        } catch (e) { /* it stays where it is */ }
        if (focused) button.focus({ preventScroll: true });
      },
      owns: function (el) { return !!(supported && el && el.closest && el.closest('#wcSoundDock')); },
      scene: function (clock, plan) {
        scene = { clock: clock, plan: plan };
        duck(true);
        var s = scene;
        (clock.ready || Promise.resolve()).then(function () { if (scene === s) cue(); }, function () {});
      },
      endScene: function (reason) {
        if (!scene) return;
        scene = null;
        if (reason !== 'end') hush();
        duck(false);
      }
    };
  })();

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
      sound.raise();
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
      // Its sound: the machine lands, the crank ratchets, each capsule pops a step higher, ta-da for
      // the question, the two cards pop and bump, and a whoosh onto the match.
      var plan = [['pop', 264]];
      for (c = 0; c < G.cranks; c++) plan.push(['crank', T0 + c * G.crank]);
      for (p = 0; p < G.pour; p++) plan.push(['capsule', tR + p * G.pourGap + 234, p]);
      plan.push(['tada', tD + 200], ['pop', tD + 560], ['hit', tE + 260, true], ['whoosh', tF + 300]);
      sound.scene(clock, plan);
      splash.safety = setTimeout(function () { if (splash && splash.run === run) endSplash('end'); }, G.end + 1500);
    } catch (e) {
      endSplash('quiet');
    }
  }

  // ---- the story card ------------------------------------------------------------------------------
  // Owner 2026-10-14: the moment the winner is decided, a 1080x1920 Instagram story card (9:16 only)
  // is drawn here, shown as a small preview on the result and kept ready, so 스토리 이미지 저장 and
  // 공유하기 hand the file over inside the same tap (a share sheet needs the tap's activation). Beat by
  // beat: the brand's pink-to-indigo gradient with soft glows, rays and confetti; "🏆 나의 최애 메뉴";
  // the winner's photo, large and rounded, with a crown; the dish name huge in Jua and its other name
  // small; "한식 32강 우승"; the runner-up and the other two semifinalists as photo chips; the CTA
  // "너의 최애는? 👉 babdoduk.vercel.app" and the wordmark; the photo credits, tiny. Instagram's own
  // controls cover about 250 px at the top and at the bottom of a story, so everything that matters
  // sits between STORY.top and STORY.bottom; only decoration and the credits go outside.
  // The photos are this site's own files (images/worldcup/), so the canvas is never tainted and can be
  // exported. The lettering is Jua cut to exactly this card's letters (loadStoryFont); without it (no
  // network, a slow font) the card is drawn in Noto Sans KR rather than in a mix of the two.
  // docs/WORLDCUP_SHARE.md describes the card, the share flows and the friend link.
  var STORY = { w: 1080, h: 1920, top: 250, bottom: 1670, pad: 72 };
  var storyFonts = 0;     // each card's Jua subset is its own family: the page's own Jua is never touched
  var story = null;       // { key, promise, file, url }: the card of the result on screen
  function storyKey() { return result ? [result.id, result.finalist, (result.semis || []).join(','), result.category, lang()].join('|') : ''; }
  function rng(seed) {          // mulberry32: the same winner always gets the same confetti
    var a = 0;
    for (var i = 0; i < seed.length; i++) a = Math.imul(a ^ seed.charCodeAt(i), 2654435761);
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }
  function within(promise, ms, fallback) {
    return Promise.race([promise.catch(function () { return fallback; }),
                         new Promise(function (resolve) { setTimeout(function () { resolve(fallback); }, ms); })]);
  }
  // Jua with only `text`'s letters (Google Fonts `text=`, a few KB). The stylesheet is read but never
  // applied (media "not all"): its font file becomes a FontFace of a family of the card's own.
  function loadStoryFont(text) {
    if (typeof FontFace !== 'function' || !document.fonts) return Promise.resolve(null);
    var letters = Array.from(new Set(Array.from(text.replace(/\s+/g, '')))).join('');
    var family = 'BabdodukStory' + (++storyFonts);
    return within(new Promise(function (resolve) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.media = 'not all';
      link.crossOrigin = 'anonymous';
      link.href = 'https://fonts.googleapis.com/css2?family=Jua&display=block&text=' + encodeURIComponent(letters);
      link.onload = function () {
        var src = null;
        try {
          [].forEach.call(link.sheet.cssRules, function (rule) {
            var m = rule.style && /url\(["']?([^"')]+)["']?\)/.exec(rule.style.getPropertyValue('src'));
            if (m && !src) src = m[1];
          });
        } catch (e) { /* an unreadable sheet: the card falls back */ }
        link.remove();
        if (!src || !/^https:\/\/fonts\.gstatic\.com\//.test(src)) { resolve(null); return; }
        new FontFace(family, 'url(' + src + ')').load().then(function (face) {
          document.fonts.add(face);
          resolve(family);
        }, function () { resolve(null); });
      };
      link.onerror = function () { link.remove(); resolve(null); };
      document.head.appendChild(link);
    }), 4000, null);
  }
  function loadPhoto(id) {
    var photo = id && photoOf(id);
    if (!photo) return Promise.resolve(null);
    return within(new Promise(function (resolve) {
      var img = new Image();
      img.decoding = 'async';
      img.onload = function () { resolve(img); };
      img.onerror = function () { resolve(null); };
      img.src = photo.image;                          // same origin: the canvas stays exportable
    }), 6000, null);
  }
  function rounded(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function cover(ctx, img, x, y, w, h) {          // object-fit: cover
    var s = Math.max(w / img.naturalWidth, h / img.naturalHeight), sw = w / s, sh = h / s;
    ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x, y, w, h);
  }
  function clip(ctx, text, max) {                  // an ellipsis rather than a line that runs off
    if (ctx.measureText(text).width <= max) return text;
    var chars = Array.from(text);
    while (chars.length > 1 && ctx.measureText(chars.join('') + '…').width > max) chars.pop();
    return chars.join('').trim() + '…';
  }
  // The dish name: one line as large as fits (up to 168 px), else two balanced lines, else clipped.
  function nameLines(ctx, text, font, max) {
    var size;
    for (size = 168; size >= 96; size -= 6) {
      ctx.font = font(size);
      if (ctx.measureText(text).width <= max) return { size: size, lines: [text] };
    }
    var words = text.split(' ');
    if (words.length > 1) {
      var best = null;
      for (var i = 1; i < words.length; i++) {
        var pair = [words.slice(0, i).join(' '), words.slice(i).join(' ')];
        ctx.font = font(100);
        var wide = Math.max(ctx.measureText(pair[0]).width, ctx.measureText(pair[1]).width);
        if (!best || wide < best.wide) best = { lines: pair, wide: wide };
      }
      for (size = 112; size >= 64; size -= 4) {
        ctx.font = font(size);
        if (best.lines.every(function (line) { return ctx.measureText(line).width <= max; })) return { size: size, lines: best.lines };
      }
      ctx.font = font(64);
      return { size: 64, lines: best.lines.map(function (line) { return clip(ctx, line, max); }) };
    }
    ctx.font = font(96);
    return { size: 96, lines: [clip(ctx, text, max)] };
  }
  function sparkle(ctx, x, y, r, color, alpha) {   // a four-pointed star
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.quadraticCurveTo(x, y, x, y + r);
    ctx.quadraticCurveTo(x, y, x - r, y);
    ctx.quadraticCurveTo(x, y, x, y - r);
    ctx.fill();
    ctx.restore();
  }
  // A gold crown with three points, pearls on the points and gems on the band.
  function crown(ctx, cx, cy, w, angle) {
    var h = w * 0.74, x = -w / 2, top = -h / 2, base = h / 2;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.shadowColor = 'rgba(80, 20, 60, 0.35)';
    ctx.shadowBlur = 24;
    ctx.shadowOffsetY = 10;
    var gold = ctx.createLinearGradient(0, top, 0, base);
    gold.addColorStop(0, '#fff3a3');
    gold.addColorStop(0.45, '#fcd34d');
    gold.addColorStop(1, '#f59e0b');
    ctx.beginPath();
    ctx.moveTo(x + w * 0.08, base);
    ctx.lineTo(x + w * 0.02, top + h * 0.2);
    ctx.lineTo(x + w * 0.29, top + h * 0.5);
    ctx.lineTo(0, top + h * 0.02);
    ctx.lineTo(x + w * 0.71, top + h * 0.5);
    ctx.lineTo(x + w * 0.98, top + h * 0.2);
    ctx.lineTo(x + w * 0.92, base);
    ctx.closePath();
    ctx.fillStyle = gold;
    ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineJoin = 'round';
    ctx.lineWidth = w * 0.035;
    ctx.strokeStyle = '#b45309';
    ctx.stroke();
    rounded(ctx, x + w * 0.06, base - h * 0.26, w * 0.88, h * 0.26, h * 0.06);   // the band
    ctx.fillStyle = '#f59e0b';
    ctx.fill();
    ctx.stroke();
    [[x + w * 0.02, top + h * 0.2], [0, top + h * 0.02], [x + w * 0.98, top + h * 0.2]].forEach(function (p) {
      ctx.beginPath();
      ctx.arc(p[0], p[1], w * 0.065, 0, Math.PI * 2);
      ctx.fillStyle = '#fffbeb';
      ctx.fill();
      ctx.stroke();
    });
    [[-w * 0.27, '#60a5fa'], [0, '#ec4899'], [w * 0.27, '#60a5fa']].forEach(function (g, i) {
      ctx.beginPath();
      ctx.arc(g[0], base - h * 0.13, w * (i === 1 ? 0.07 : 0.05), 0, Math.PI * 2);
      ctx.fillStyle = g[1];
      ctx.fill();
      ctx.lineWidth = w * 0.02;
      ctx.stroke();
    });
    ctx.beginPath();                                  // a glint on the left point
    ctx.moveTo(x + w * 0.12, top + h * 0.42);
    ctx.lineTo(x + w * 0.2, top + h * 0.62);
    ctx.lineWidth = w * 0.03;
    ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.85)';
    ctx.stroke();
    ctx.restore();
  }
  function storyTexts() {
    var host = /^babdoduk(-lab)?\.vercel\.app$/.test(location.hostname) ? location.hostname : 'babdoduk.vercel.app';
    var opponents = [result.finalist].concat(result.semis || []).filter(Boolean);
    var photos = [result.id].concat(opponents).map(photoOf).filter(Boolean);
    var credits = photos.filter(function (p) { return p.author; }).map(function (p) { return p.author + ' (' + p.license + ')'; });
    return {
      kicker: t('wc.cardKicker', '나의 최애 메뉴'),
      name: name(result.id),
      sub: otherName(result.id),
      won: fill(t('wc.story.won', '{game} 우승'), { game: gameLabel(result.category) }),
      emoji: CATEGORY_EMOJI[result.category] || '🏆',
      chips: opponents.map(function (id, i) {
        return { id: id, label: t(i ? 'wc.story.semi' : 'wc.story.final', i ? '4강' : '결승 상대'), name: name(id) };
      }),
      cta: t('wc.story.cta', '너의 최애는?'),
      host: host,
      brand: t('wc.cardBrand', '밥도둑 먹방 월드컵'),
      credit: credits.length ? fill(t('wc.story.credit', '사진: 위키미디어 공용 · {credits}'), { credits: credits.join(', ') }) : ''
    };
  }
  // The card, top to bottom. The photo gives way when the name needs two lines, so the wordmark always
  // ends inside the safe zone.
  function drawStory(canvas, words, family, photos) {
    var W = STORY.w, H = STORY.h, ctx = canvas.getContext('2d'), inner = W - 2 * STORY.pad;
    var sans = "'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif";
    var display = function (px) { return family ? px + "px '" + family + "', " + sans : '900 ' + px + 'px ' + sans; };
    var plain = function (weight, px) { return weight + ' ' + px + 'px ' + sans; };
    var random = rng(result.id);
    function shadow(color, blur, y) { ctx.shadowColor = color; ctx.shadowBlur = blur; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = y; }
    function noShadow() { ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0; }
    function pill(text, font, y, h, fill, ink, stroke) {
      ctx.font = font;
      var w = Math.min(ctx.measureText(text).width + h, inner);
      rounded(ctx, (W - w) / 2, y, w, h, h / 2);
      ctx.fillStyle = fill;
      ctx.fill();
      noShadow();
      if (stroke) { ctx.lineWidth = 3; ctx.strokeStyle = stroke; ctx.stroke(); }
      ctx.fillStyle = ink;
      ctx.textBaseline = 'middle';
      ctx.fillText(clip(ctx, text, w - h * 0.6), W / 2, y + h / 2 + 2);
      ctx.textBaseline = 'alphabetic';
    }
    ctx.textAlign = 'center';

    // The layout first: the name's size decides how tall the photo can be.
    var fit = nameLines(ctx, words.name, display, inner);
    var lineH = Math.round(fit.size * 1.06), nameH = fit.size + (fit.lines.length - 1) * lineH;
    var chips = words.chips.slice(0, 3), subH = words.sub ? 58 : 0, chipsH = chips.length ? 128 : 0;
    var photoH = Math.max(380, Math.min(540, 882 - nameH - subH - chipsH));
    var photoW = Math.round(photoH * 1.4);
    var photoTop = 410, frame = 18;
    var nameTop = photoTop + photoH + frame + 46;
    var wonY = nameTop + nameH + subH + 34, chipY = wonY + 78 + 30, ctaY = chipY + chipsH + (chipsH ? 2 : 30);

    // The brand gradient, pink at the top to indigo at the bottom, with soft lights.
    var bg = ctx.createLinearGradient(0, 0, W * 0.55, H);
    bg.addColorStop(0, '#f472b6');
    bg.addColorStop(0.22, '#db2777');
    bg.addColorStop(0.55, '#a21caf');
    bg.addColorStop(0.82, '#6d28d9');
    bg.addColorStop(1, '#4338ca');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
    [[140, 360, 520, 'rgba(255, 255, 255, 0.30)'], [1000, 980, 560, 'rgba(251, 207, 232, 0.22)'],
     [880, 150, 420, 'rgba(253, 224, 71, 0.20)'], [120, 1700, 620, 'rgba(129, 140, 248, 0.45)'],
     [980, 1820, 520, 'rgba(56, 189, 248, 0.22)']].forEach(function (g) {
      var glow = ctx.createRadialGradient(g[0], g[1], 0, g[0], g[1], g[2]);
      glow.addColorStop(0, g[3]);
      glow.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, W, H);
    });
    // Rays from behind the photo, a trophy-stage light.
    var cx = W / 2, cy = photoTop + photoH / 2;
    ctx.save();
    ctx.translate(cx, cy);
    var rays = ctx.createRadialGradient(0, 0, 80, 0, 0, 1000);
    rays.addColorStop(0, 'rgba(255, 255, 255, 0.17)');
    rays.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = rays;
    for (var r = 0; r < 18; r++) {
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, 1100, r * Math.PI / 9, r * Math.PI / 9 + Math.PI / 22);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
    // Confetti and sparkles: thick in the bands Instagram covers, a few down the sides, none on words.
    var colors = ['#fde047', '#fbcfe8', '#ffffff', '#a5f3fc', '#c4b5fd', '#fdba74', '#f9a8d4'];
    for (var i = 0; i < 96; i++) {
      var band = i % 3, x = random() * W, y;
      if (band === 0) y = 14 + random() * (STORY.top - 10);
      else if (band === 1) y = STORY.bottom + 24 + random() * (H - STORY.bottom - 150);
      else { y = STORY.top + random() * (STORY.bottom - STORY.top); x = random() < 0.5 ? 8 + random() * 44 : W - 8 - random() * 44; }
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(random() * Math.PI);
      ctx.globalAlpha = 0.55 + random() * 0.45;
      ctx.fillStyle = colors[i % colors.length];
      var kind = i % 4, s = 12 + random() * 16;
      if (kind === 0) ctx.fillRect(-s / 2, -s * 0.22, s, s * 0.44);
      else if (kind === 1) { ctx.beginPath(); ctx.arc(0, 0, s * 0.34, 0, Math.PI * 2); ctx.fill(); }
      else if (kind === 2) { rounded(ctx, -s * 0.8, -s * 0.16, s * 1.6, s * 0.32, s * 0.16); ctx.fill(); }
      else { ctx.beginPath(); ctx.moveTo(0, -s * 0.5); ctx.lineTo(s * 0.45, s * 0.35); ctx.lineTo(-s * 0.45, s * 0.35); ctx.closePath(); ctx.fill(); }
      ctx.restore();
    }
    [[96, 300, 28], [986, 300, 36], [44, 760, 22], [1040, 900, 26], [150, 1726, 34], [930, 1730, 26], [540, 110, 32],
     [290, 176, 18], [790, 196, 22], [1036, 1650, 18]].forEach(function (s, n) {
      sparkle(ctx, s[0], s[1], s[2], n % 3 ? '#ffffff' : '#fef08a', 0.92);
    });

    // "🏆 나의 최애 메뉴" on a glassy pill.
    pill('🏆 ' + words.kicker, display(52), 268, 92, 'rgba(255, 255, 255, 0.2)', '#ffffff', 'rgba(255, 255, 255, 0.6)');
    // The winner's photo in a white frame, tilted a little, with a crown on its corner.
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-0.035);
    shadow('rgba(46, 16, 101, 0.45)', 70, 34);
    rounded(ctx, -photoW / 2 - frame, -photoH / 2 - frame, photoW + 2 * frame, photoH + 2 * frame, 60);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    noShadow();
    rounded(ctx, -photoW / 2, -photoH / 2, photoW, photoH, 44);
    if (photos[0]) {
      ctx.save();
      ctx.clip();
      cover(ctx, photos[0], -photoW / 2, -photoH / 2, photoW, photoH);
      ctx.restore();
    } else {
      var empty = ctx.createLinearGradient(0, -photoH / 2, 0, photoH / 2);
      empty.addColorStop(0, '#fdf2f8');
      empty.addColorStop(1, '#eef2ff');
      ctx.fillStyle = empty;
      ctx.fill();
      ctx.font = plain(400, 240);
      ctx.textBaseline = 'middle';
      ctx.fillText(words.emoji, 0, 0);
      ctx.textBaseline = 'alphabetic';
    }
    ctx.restore();
    crown(ctx, cx - photoW / 2 + 24, photoTop - 4, 196, -0.36);

    // The dish name, huge, and its other name.
    ctx.font = display(fit.size);
    shadow('rgba(59, 7, 100, 0.5)', 32, 8);
    ctx.fillStyle = '#ffffff';
    fit.lines.forEach(function (line, n) { ctx.fillText(line, W / 2, nameTop + fit.size * 0.86 + n * lineH); });
    noShadow();
    if (words.sub) {
      ctx.font = plain(600, 40);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.88)';
      ctx.fillText(clip(ctx, words.sub, inner), W / 2, nameTop + nameH + 46);
    }
    // "🍚 한식 32강 우승" on a white pill.
    shadow('rgba(46, 16, 101, 0.3)', 24, 8);
    pill(words.emoji + ' ' + words.won, display(46), wonY, 78, '#ffffff', '#be185d');

    // The runner-up and the semifinalists: photo chips in one row.
    var gap = 16, chipH = 100;
    var chipW = chips.length === 1 ? 560 : (inner - gap * (chips.length - 1)) / chips.length;
    var rowX = (W - (chipW * chips.length + gap * (chips.length - 1))) / 2;
    chips.forEach(function (chip, n) {
      var x = rowX + n * (chipW + gap), img = photos[n + 1], d = 76, px = x + 12, py = chipY + (chipH - d) / 2;
      rounded(ctx, x, chipY, chipW, chipH, chipH / 2);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.17)';
      ctx.fill();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.stroke();
      ctx.save();
      ctx.beginPath();
      ctx.arc(px + d / 2, py + d / 2, d / 2, 0, Math.PI * 2);
      ctx.fillStyle = '#fce7f3';
      ctx.fill();
      if (img) { ctx.clip(); cover(ctx, img, px, py, d, d); }
      ctx.restore();
      ctx.beginPath();
      ctx.arc(px + d / 2, py + d / 2, d / 2, 0, Math.PI * 2);
      ctx.lineWidth = 4;
      ctx.strokeStyle = '#ffffff';
      ctx.stroke();
      var tx = px + d + 14, room = x + chipW - tx - 26;
      ctx.textAlign = 'left';
      ctx.font = plain(700, 23);
      ctx.fillStyle = n ? 'rgba(255, 255, 255, 0.8)' : '#fde68a';
      ctx.fillText(clip(ctx, chip.label, room), tx, chipY + 40);
      var size = chips.length === 1 ? 40 : 34;
      ctx.font = display(size);
      while (size > 24 && ctx.measureText(chip.name).width > room) { size -= 2; ctx.font = display(size); }
      ctx.fillStyle = '#ffffff';
      ctx.fillText(clip(ctx, chip.name, room), tx, chipY + 44 + size);
      ctx.textAlign = 'center';
    });

    // The call to play, "너의 최애는? 👉 babdoduk.vercel.app", and the wordmark: both inside the safe zone.
    shadow('rgba(30, 10, 60, 0.4)', 28, 10);
    pill(words.cta + ' 👉 ' + words.host, display(44), ctaY, 88, '#1e1d1a', '#ffffff');
    ctx.font = plain(900, 46);
    var mark = 'Babdoduk', mw = ctx.measureText(mark).width;
    ctx.font = plain(700, 26);
    var bw = ctx.measureText(words.brand).width, total = mw + 20 + bw, left = (W - total) / 2, base = ctaY + 88 + 62;
    ctx.textAlign = 'left';
    ctx.font = plain(900, 46);
    var holo = ctx.createLinearGradient(left, 0, left + mw, 0);
    holo.addColorStop(0, '#ffffff');
    holo.addColorStop(0.5, '#fce7f3');
    holo.addColorStop(1, '#e0e7ff');
    ctx.fillStyle = holo;
    ctx.fillText(mark, left, base);
    ctx.font = plain(700, 26);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.82)';
    ctx.fillText(words.brand, left + mw + 20, base - 4);
    ctx.textAlign = 'center';

    // The photo credits (the licences ask for them), small, at the very bottom: two lines at most.
    if (words.credit) {
      ctx.font = plain(500, 20);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.72)';
      var lines = [words.credit];
      if (ctx.measureText(words.credit).width > inner) {
        var parts = words.credit.split(', '), first = '';
        while (parts.length && ctx.measureText(first + parts[0] + ',').width <= inner) first += parts.shift() + ', ';
        lines = [first.replace(/, $/, ','), clip(ctx, parts.join(', '), inner)];
      }
      lines.forEach(function (line, n) { ctx.fillText(line, W / 2, H - 70 + n * 28 - (lines.length - 1) * 14); });
    }
  }
  // The card of the result on screen: drawn once per winner and language, then kept.
  function prepareStory() {
    var key = storyKey();
    if (!key) return Promise.resolve(null);
    if (story && story.key === key) return story.promise;
    if (story && story.url) URL.revokeObjectURL(story.url);
    var mine = story = { key: key, file: null, url: null };
    var words = storyTexts(), preview = $('wcStoryPreview');
    preview.hidden = true;
    $('wcStory').setAttribute('aria-busy', 'true');
    var juaText = ['🏆 ' + words.kicker, words.name, words.emoji + ' ' + words.won, words.cta + ' 👉 ' + words.host]
      .concat(words.chips.map(function (c) { return c.name; })).join('');
    var plainText = [words.sub, words.credit, words.brand, 'Babdoduk'].concat(words.chips.map(function (c) { return c.label; })).join('');
    var noto = document.fonts && document.fonts.load ? Promise.all(['500', '600', '700', '900'].map(function (w) {
      return document.fonts.load(w + " 40px 'Noto Sans KR'", plainText + juaText);
    })) : Promise.resolve();
    mine.promise = Promise.all([loadStoryFont(juaText), within(noto, 3000, null),
                                Promise.all([result.id].concat(words.chips.map(function (c) { return c.id; })).map(loadPhoto))])
      .then(function (got) {
        if (story !== mine) return null;
        var canvas = document.createElement('canvas');
        canvas.width = STORY.w;
        canvas.height = STORY.h;
        drawStory(canvas, words, got[0], got[2]);
        return new Promise(function (resolve) { canvas.toBlob(resolve, 'image/png'); });
      })
      .then(function (blob) {
        if (story !== mine || !blob) return null;
        mine.file = typeof File === 'function' ? new File([blob], 'babdoduk-worldcup-story.png', { type: 'image/png' }) : blob;
        mine.url = URL.createObjectURL(blob);
        preview.src = mine.url;
        preview.alt = fill(t('wc.story.alt', '스토리 이미지 미리보기: {dish}'), { dish: words.name });
        preview.hidden = false;
        $('wcStory').removeAttribute('aria-busy');
        return mine.file;
      })
      .catch(function () { $('wcStory').removeAttribute('aria-busy'); return null; });
    return mine.promise;
  }
  // A short message in the toast, read out once (role="status").
  var toastTimer = 0;
  function toast(text) {
    var box = $('wcShareStatus');
    clearTimeout(toastTimer);
    box.textContent = '';
    box.classList.remove('is-shown');
    setTimeout(function () {
      box.textContent = text;
      box.classList.add('is-shown');
      toastTimer = setTimeout(function () { box.classList.remove('is-shown'); }, 2800);
    }, 30);
  }
  function touchDevice() { return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches); }
  function canShareFile(file) {
    try { return !!(file && navigator.share && navigator.canShare && navigator.canShare({ files: [file] })); } catch (e) { return false; }
  }
  function download(file) {
    var link = document.createElement('a');
    link.href = URL.createObjectURL(file);
    link.download = 'babdoduk-worldcup-story.png';
    document.body.appendChild(link);
    link.click();
    setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    toast(t('wc.saved', '저장했어요'));
  }
  // 📥 스토리 이미지 저장: a computer downloads the PNG; a phone, where a download lands somewhere hard
  // to find, opens the share sheet with the file alone ("이미지 저장" or straight to a story).
  function saveStory() {
    var file = story && story.key === storyKey() ? story.file : null;
    if (!file) {
      toast(t('wc.preparing', '이미지를 만드는 중이에요'));
      prepareStory().then(function (made) { if (made) download(made); else toast(t('wc.shareFailed', '공유하지 못했어요.')); });
      return;
    }
    if (touchDevice() && canShareFile(file)) {
      navigator.share({ files: [file] }).catch(function (e) { if (!e || e.name !== 'AbortError') download(file); });
      return;
    }
    download(file);
  }
  // The friend challenge: this page with the winner and the category, on this host (lab links stay on lab).
  function shareUrl() {
    return location.origin + location.pathname + '?from=' + encodeURIComponent(result.id) + '&cat=' + encodeURIComponent(result.category);
  }
  function copyLink(url) {
    function done() { toast(t('wc.copied', '링크를 복사했어요')); }
    function legacy() {
      var area = document.createElement('textarea');
      area.value = url;
      area.setAttribute('readonly', '');
      area.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      area.remove();
      if (ok) done(); else toast(t('wc.shareFailed', '공유하지 못했어요.'));
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, legacy);
    else legacy();
  }
  // 📤 공유하기: on a phone the share sheet (Web Share Level 2) with the card, the text and the link,
  // where Instagram (스토리) and KakaoTalk are; without file sharing the text and the link; on a
  // computer the link is copied.
  function share() {
    var text = fill(t('wc.shareText', '나의 먹방 월드컵({cat}) 우승 메뉴는 {dish}!'),
      { cat: catName(result.category), dish: name(result.id) });
    var url = shareUrl(), file = story && story.key === storyKey() ? story.file : null;
    if (!touchDevice() || !navigator.share) { copyLink(url); return; }
    var data = { title: document.title, text: text, url: url };
    if (canShareFile(file)) data.files = [file];
    navigator.share(data).catch(function (e) { if (!e || e.name !== 'AbortError') copyLink(url); });
  }
  // The KakaoTalk hook (docs/WORLDCUP_SHARE.md): no SDK is loaded until the owner has an app key. Once
  // the Kakao JS SDK is on the page and Kakao.init(<key>) has run, a 카카오톡 button can call
  // Kakao.Share.sendDefault(window.BabdodukWorldcupShare.kakaoFeed()) for a feed card.
  window.BabdodukWorldcupShare = {
    kakaoFeed: function () {
      if (!result) return null;
      var url = shareUrl(), photo = photoOf(result.id);
      return {
        objectType: 'feed',
        content: {
          title: fill(t('wc.shareText', '나의 먹방 월드컵({cat}) 우승 메뉴는 {dish}!'), { cat: catName(result.category), dish: name(result.id) }),
          description: t('wc.story.cta', '너의 최애는?'),
          imageUrl: photo ? new URL(photo.image, location.href).href : new URL('images/worldcup/og-worldcup.jpg', location.href).href,
          link: { mobileWebUrl: url, webUrl: url }
        },
        buttons: [{ title: t('wc.friendCta', '나도 해보기'), link: { mobileWebUrl: url, webUrl: url } }]
      };
    }
  };
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
  // The friend challenge (a shared result): worldcup.html?from=<dish>&cat=<category>. A dish of the
  // pool shows "친구의 최애는 ○○! 🏆 너도 해봐" over the start screen, a known category is the tile
  // chosen; anything else is ignored. It never starts a game (that is go=1 alone), and before the
  // launch the banner shows while the game stays locked, with no photo.
  var friend = null;    // the friend's dish id, from the address
  function challenge() {
    if (embedded || !window.URLSearchParams) return { id: null, cat: null };
    var query = new URLSearchParams(location.search), id = query.get('from'), cat = query.get('cat');
    return { id: set.indexOf(id) >= 0 ? id : null,
             cat: CATEGORIES.indexOf(cat) >= 0 && poolOf(cat).length >= size ? cat : null };
  }
  function renderFriend() {
    var box = $('wcFriend');
    if (!box) return;
    box.hidden = !friend;
    if (!friend) return;
    var text = $('wcFriendText'), parts = t('wc.friend', '친구의 최애는 {dish}! 🏆 너도 해봐').split('{dish}');
    text.textContent = '';
    text.appendChild(document.createTextNode(parts[0]));
    node('strong', 'wc-friend-dish', text).textContent = name(friend);
    text.appendChild(document.createTextNode(parts.slice(1).join(name(friend))));
    var img = $('wcFriendPhoto'), photo = photoOf(friend);
    img.hidden = locked() || !photo;                              // before the launch no photo is requested
    if (!img.hidden && img.getAttribute('src') !== photo.image) {
      img.onerror = function () { img.hidden = true; };
      img.src = photo.image;
    }
  }
  function cleanAddress() {
    try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) { /* keep the address */ }
  }
  function ready() {
    buildTiles();
    if (!embedded) sound.show();
    if (!embedded) restore();                  // the news page's card starts fresh, whatever is saved
    buildFloaters();
    show('intro');
    var asked = requested();
    if (asked) cleanAddress();
    var pal = asked ? { id: null, cat: null } : challenge();
    friend = pal.id;
    if (pal.cat) category = pal.cat;           // the friend's category is the tile chosen
    if (asked && locked()) asked = null;       // go=1 before the launch is just the locked start screen
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
    if (locked()) return;
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
    $('wcSaveImage').addEventListener('click', saveStory);
    $('wcHistoryClear').addEventListener('click', clearHistory);
  }
  document.addEventListener('babdoduk-lang', render);
  document.addEventListener('babdoduk-lang', function () { endSplash('quiet'); });
  // The launch moment passing while the start screen is open: the locked pill gives way to the button.
  // The photos and the tile choice, which stayed hidden until now, come in with it.
  document.addEventListener('babdoduk-wc-phase', function () {
    if (view !== 'intro') return;
    buildFloaters();
    choose(category, false);
    renderIntro();
    ambient(true);
  });

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
    if (sound.owns(e.target) && (e.key === 'Enter' || e.key === ' ')) return;   // the sound toggle never skips
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
