/* KAIST menu world cup (worldcup.html): two dishes at a time from data/content/worldcup.json, with
   names and flavours from the food catalog (data/foods/). Progress and past winners stay in this
   browser (localStorage `babdoduk-worldcup`); nothing is sent anywhere. */
(function () {
  'use strict';
  var KEY = 'babdoduk-worldcup';
  var HISTORY = 10;
  // Flavour and texture tags, most telling first; a card shows at most two (score 4 or 5).
  var TAGS = ['spicy', 'crispy', 'soupy', 'sweet', 'chewy', 'rich', 'umami', 'sour', 'salty', 'soft'];
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var dishes = {};
  var set = [];
  var basis = null;
  var game = null;      // { entrants: [ids], winners: [ids], stack: [{ entrants, winners }] }
  var winners = [];     // [{ id, finalist, date }], newest first
  var result = null;    // { id, finalist } of the game just finished
  var view = 'loading';
  var busy = false;
  var $ = function (id) { return document.getElementById(id); };
  var cards = [].slice.call(document.querySelectorAll('.wc-card'));

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
  function roundName(size) {
    if (size === 2) return t('wc.round.final', '결승');
    if (size === 4) return t('wc.round.semi', '준결승');
    return fill(t('wc.round.n', '{n}강'), { n: size });
  }

  // ---- saved state ---------------------------------------------------------------------------
  function signature() { return set.join(','); }
  function validGame(g) {
    if (!g || !Array.isArray(g.entrants) || !Array.isArray(g.winners) || !Array.isArray(g.stack)) return false;
    var size = g.entrants.length;
    if (size < 2 || (size & (size - 1)) || g.winners.length >= size / 2) return false;
    return g.entrants.concat(g.winners).every(function (id) { return set.indexOf(id) >= 0; });
  }
  function restore() {
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!saved || saved.v !== 1) return;
      winners = (Array.isArray(saved.winners) ? saved.winners : []).filter(function (w) {
        return w && dishes[w.id] && typeof w.date === 'string';
      }).slice(0, HISTORY);
      if (saved.set === signature() && validGame(saved.game)) game = saved.game;
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
      $('wc' + part).hidden = part.toLowerCase() !== which;
    });
    renderHistory();
  }
  function progress() {
    return { round: roundName(game.entrants.length), n: game.winners.length + 1, total: game.entrants.length / 2 };
  }
  function picksMade() {
    var made = 0, size = set.length;
    while (size > game.entrants.length) { made += size / 2; size /= 2; }
    return made + game.winners.length;
  }
  function pair() {
    var i = game.winners.length * 2;
    return [game.entrants[i], game.entrants[i + 1]];
  }
  function renderIntro() {
    $('wcBasis').textContent = basis ? (basis[lang()] || basis.ko) : '';
    $('wcStart').textContent = fill(t('wc.start', '{n}강 시작'), { n: set.length });
    var resumable = !!game;
    $('wcResume').hidden = !resumable;
    // A game in progress makes resuming the main action; starting over stays one tap away.
    $('wcResume').classList.toggle('wc-btn--main', resumable);
    $('wcStart').classList.toggle('wc-btn--main', !resumable);
    if (resumable) $('wcResume').textContent = fill(t('wc.resume', '이어서 하기 · {round} {n}/{total}'), progress());
  }
  function renderMatch(focus) {
    var p = progress(), ids = pair(), done = picksMade(), all = set.length - 1;
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
    });
    $('wcUndo').disabled = !game.stack.length;
    if (focus) cards[0].focus();
    if (focus !== null) announce(fill(t('wc.announce', '{round} {n}번째 경기: {a} 대 {b}'),
      { round: p.round, n: p.n, a: name(ids[0]), b: name(ids[1]) }));
  }
  function renderResult(focus) {
    $('wcWinner').textContent = name(result.id);
    $('wcWinnerSub').textContent = otherName(result.id);
    $('wcFinalist').textContent = fill(t('wc.finalist', '결승 상대: {dish}'), { dish: name(result.finalist) });
    $('wcShareStatus').textContent = '';
    if (focus) {
      $('wcWinner').focus();
      announce(fill(t('wc.announceWinner', '우승 메뉴: {dish}'), { dish: name(result.id) }));
    }
  }
  function renderHistory() {
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
  function start() {
    game = { entrants: shuffle(set), winners: [], stack: [] };
    result = null;
    store();
    show('match');
    renderMatch(true);
  }
  function resume() {
    if (!game) { start(); return; }
    show('match');
    renderMatch(true);
  }
  function finish(winner, finalist) {
    winners.unshift({ id: winner, finalist: finalist, date: todayKst() });
    winners = winners.slice(0, HISTORY);
    result = { id: winner, finalist: finalist };
    game = null;
    store();
    show('result');
    renderResult(true);
  }
  function pick(side) {
    if (busy || view !== 'match') return;
    var ids = pair(), chosen = ids[side];
    game.stack.push({ entrants: game.entrants.slice(), winners: game.winners.slice() });
    game.winners.push(chosen);
    if (game.winners.length * 2 === game.entrants.length) {
      if (game.winners.length === 1) { finish(chosen, ids[1 - side]); return; }
      game.entrants = game.winners;
      game.winners = [];
    }
    store();
    if (reduced) { renderMatch(true); return; }
    busy = true;
    cards[side].classList.add('is-picked');
    setTimeout(function () {
      cards[side].classList.remove('is-picked');
      busy = false;
      renderMatch(true);
    }, 220);
  }
  function undo() {
    if (!game || !game.stack.length || busy) return;
    var previous = game.stack.pop();
    game.entrants = previous.entrants;
    game.winners = previous.winners;
    store();
    renderMatch(true);
  }
  function share() {
    var text = fill(t('wc.shareText', '나의 KAIST 메뉴 월드컵 우승 메뉴는 {dish}!'), { dish: name(result.id) });
    var url = location.origin + location.pathname;
    var status = $('wcShareStatus');
    if (navigator.share) {
      navigator.share({ title: document.title, text: text, url: url }).catch(function () {});
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text + ' ' + url).then(function () {
        status.textContent = t('wc.copied', '결과와 주소를 복사했어요.');
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
  function ready() {
    restore();
    show('intro');
    renderIntro();
  }
  function failed() {
    show('loading');
    $('wcLoadingText').hidden = true;
    $('wcError').hidden = false;
  }

  cards.forEach(function (card, side) { card.addEventListener('click', function () { pick(side); }); });
  $('wcStart').addEventListener('click', function () { start(); });
  $('wcResume').addEventListener('click', resume);
  $('wcUndo').addEventListener('click', undo);
  $('wcRestart').addEventListener('click', start);
  $('wcAgain').addEventListener('click', start);
  $('wcShare').addEventListener('click', share);
  $('wcHistoryClear').addEventListener('click', clearHistory);
  document.addEventListener('babdoduk-lang', render);

  Promise.all([getJson('data/content/worldcup.json'), getJson('data/foods/catalog.json')]).then(function (loaded) {
    var cup = loaded[0], catalog = loaded[1];
    return Promise.all((catalog.packs || []).map(function (pack) { return getJson(pack.src); })).then(function (packs) {
      packs.forEach(function (pack) { (pack.items || []).forEach(function (dish) { dishes[dish.id] = dish; }); });
      set = (cup.dishes || []).filter(function (id) { return dishes[id]; });
      if (set.length < 4 || (set.length & (set.length - 1))) throw new Error('bracket');
      basis = cup.basis || null;
    });
  }).then(ready, failed);
})();
