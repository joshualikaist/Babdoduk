/* Babdoduk food world cup (worldcup.html): each game draws `size` dishes (32) from the pool in
   data/content/worldcup.json (the sync writes it into the page as window.BABDODUK_WORLDCUP;
   data/content/ is never deployed) and plays them two at a time, with names and flavours from the
   food catalog (data/foods/). A pick pops; from the quarterfinals on a new round takes the screen
   for a beat (the final with a crash of the two finalists); the winner gets confetti and a result
   image to save. Progress and past winners stay in this browser (localStorage
   `babdoduk-worldcup`); nothing is sent anywhere. */
(function () {
  'use strict';
  var KEY = 'babdoduk-worldcup';
  var HISTORY = 10;
  // Flavour and texture tags, most telling first; a card shows at most two (score 4 or 5).
  var TAGS = ['spicy', 'crispy', 'soupy', 'sweet', 'chewy', 'rich', 'umami', 'sour', 'salty', 'soft'];
  var cup = window.BABDODUK_WORLDCUP || {};
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var dishes = {};
  var set = [];         // the pool
  var size = 0;         // dishes per game (a power of two)
  var basis = null;
  var game = null;      // { entrants: [ids], winners: [ids], stack: [{ entrants, winners }] }
  var winners = [];     // [{ id, finalist, date }], newest first
  var result = null;    // { id, finalist } of the game just finished
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
    var photo = (cup.photos || {})[id];
    var caption = link.parentNode;
    img.hidden = caption.hidden = !photo;
    if (!photo) { img.removeAttribute('src'); return; }
    img.onerror = function () { img.hidden = caption.hidden = true; };
    if (img.getAttribute('src') !== photo.image) img.src = photo.image;
    link.href = photo.source;
    link.textContent = fill(t('wc.photoCredit', '사진 {author} · {license}'), { author: photo.author, license: photo.license });
  }
  function preload(ids) {
    ids.forEach(function (id) {
      var photo = id && (cup.photos || {})[id];
      if (photo) { var img = new Image(); img.src = photo.image; }
    });
  }
  function roundName(size) {
    if (size === 2) return t('wc.round.final', '결승');
    if (size === 4) return t('wc.round.semi', '준결승');
    return fill(t('wc.round.n', '{n}강'), { n: size });
  }

  // ---- saved state ---------------------------------------------------------------------------
  function signature() { return size + ':' + set.join(','); }
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
    var made = 0, round = size;
    while (round > game.entrants.length) { made += round / 2; round /= 2; }
    return made + game.winners.length;
  }
  function pair() {
    var i = game.winners.length * 2;
    return [game.entrants[i], game.entrants[i + 1]];
  }
  function renderIntro() {
    $('wcBasis').textContent = basis ? (basis[lang()] || basis.ko) : '';
    $('wcStart').textContent = fill(t('wc.start', '{n}강 시작'), { n: size });
    var resumable = !!game;
    $('wcResume').hidden = !resumable;
    // A game in progress makes resuming the main action; starting over stays one tap away.
    $('wcResume').classList.toggle('wc-btn--main', resumable);
    $('wcStart').classList.toggle('wc-btn--main', !resumable);
    if (resumable) $('wcResume').textContent = fill(t('wc.resume', '이어하기 · {round} {n}/{total}'), progress());
  }
  // `instant`: a round splash covers the screen, so the match jumps into view rather than scrolling.
  function renderMatch(focus, instant) {
    var p = progress(), ids = pair(), done = picksMade(), all = size - 1;
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
    // 처음부터 keeps the bracket being left as the new game's first undo step, so 되돌리기 brings it
    // back. One is kept: its own restart step is dropped, and restarting again before a pick keeps
    // the one already there.
    var before = null;
    if (game && game.stack.length) {
      var own = game.stack.filter(function (step) { return !step.game; });
      before = own.length ? { game: { entrants: game.entrants, winners: game.winners, stack: own, log: game.log || [] } }
        : game.stack[0];
    }
    game = { entrants: shuffle(set).slice(0, size), winners: [], stack: before ? [before] : [], log: [] };
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
    var cx = w / 2, cy = h / 2, phone = w <= 560;
    var gap = phone ? 12 : 28, kick = phone ? 22 : 40, IMPACT = 1100, STOP = 110;
    var cardHeight = cards[0].getBoundingClientRect().height;
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
      var r = card.getBoundingClientRect(), dir = side ? 1 : -1;
      var fighter = node('div', 'wc-fighter wc-fighter--' + (side ? 'right' : 'left'), stage);
      fighter.style.cssText = 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
      var glow = node('i', 'wc-fighter-glow', fighter), trail = node('i', 'wc-fighter-trail', fighter);
      [0.16, 0.34, 0.5, 0.66, 0.84].forEach(function (y, i) {
        var streak = node('i', 'wc-fighter-streak', trail);
        streak.style.cssText = 'top:' + y * 100 + '%;width:' + [70, 100, 55, 90, 65][i] + '%';
      });
      var face = node('div', 'wc-fighter-face', fighter);
      [].forEach.call(card.childNodes, function (child) { face.appendChild(child.cloneNode(true)); });
      var homeX = r.left + r.width / 2, homeY = r.top + r.height / 2;
      // A little bigger on a wide stage; on a phone the pair already fills the width.
      var z = Math.max(1, Math.min(1.2, w * 0.9 / (2 * r.width + gap), h * 0.7 / r.height)), half = r.width * z / 2;
      function at(x, rot, sx, sy) { return { transform: pose(x - homeX, cy - homeY, rot, sx * z, (sy == null ? sx : sy) * z) }; }
      var contact = cx + dir * (half - 2), seat = cx + dir * (half + gap / 2);
      var off = half + r.height * z * 0.17 + 48;        // tilted, with its glow, still wholly off screen
      track(fighter, [[780, at(dir < 0 ? -off : w + off, dir * -9, 1.04, 0.97), EASE.rush],
                      [IMPACT, at(contact, dir * -2, 0.86, 1.08)],
                      [IMPACT + STOP, at(contact, dir * -2, 0.86, 1.08), EASE.out],
                      [IMPACT + STOP + 90, at(seat + dir * kick, dir * 4, 1.05, 0.97), EASE.bouncy],
                      [1480, at(seat, 0, 1, 1)],
                      [1560, at(seat, 0, 1, 1), EASE.soft],
                      [1960, { transform: pose(0, 0, 0, 1) }]]);
      track(trail, [[780, { transform: 'scaleX(0.4)', opacity: 0 }], [840, { transform: 'scaleX(1)', opacity: 1 }],
                    [IMPACT - 30, { transform: 'scaleX(1)', opacity: 1 }], [IMPACT + 20, { transform: 'scaleX(0.2)', opacity: 0 }]]);
      track(glow, [[780, { opacity: 1 }], [1560, { opacity: 1 }, EASE.io], [1800, { opacity: 0 }]]);
      card.style.opacity = '0';                         // until its double lands on it
    });
    var vsBox = node('div', 'wc-splash-center', stage), vs = node('p', 'wc-splash-vs', vsBox);
    vs.textContent = t('wc.vs', 'VS');
    var vsSize = Math.min(w * 0.27, h * 0.23, 190);
    vs.style.fontSize = vsSize + 'px';
    var real = document.querySelector('.wc-vs').getBoundingClientRect();
    var to = real.width ? pose(real.left + real.width / 2 - cx, real.top + real.height / 2 - cy, 0, Math.max(0.12, real.height / vsSize * 1.2))
      : pose(0, 0, 0, 0.3);
    track(vs, [[IMPACT + 30, { transform: pose(0, 0, -14, 3.2), opacity: 0 }, EASE.in],
               [IMPACT + 150, { transform: pose(0, 0, 4, 0.82), opacity: 1 }, 'ease-out'],
               [IMPACT + 230, { transform: pose(0, 0, -2, 1.12), opacity: 1 }, 'ease-in-out'],
               [IMPACT + 320, { transform: pose(0, 0, 0, 1), opacity: 1 }],
               [1560, { transform: pose(0, 0, 0, 1), opacity: 1 }, EASE.io],
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
      // The clock: when it runs out (or a test finishes it) the splash ends; if it never does, a
      // timer ends it anyway, unless someone paused it to look.
      var clock = splashEl.animate(null, { duration: spec.ms });
      clock.onfinish = function () { if (splash && splash.run === run) endSplash('end'); };
      splash.anims.push(clock);
      (function later() {
        splash.safety = setTimeout(function () {
          if (!splash || splash.run !== run) return;
          if (clock.playState === 'paused') later(); else endSplash('end');
        }, spec.ms + 1500);
      })();
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
    cards.forEach(function (card) { card.style.opacity = ''; });
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
    s.anims.forEach(function (a) { a.onfinish = null; a.pause(); });
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
  var COLORS = ['#f45e45', '#ffb703', '#219ebc', '#8ecae6', '#fb8500', '#6a994e', '#c77dff'];
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
      fitText(ctx, t('wc.cardKicker', '나의 최애 메뉴'), 540, 120, 900, 40, 800);
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
      if (validGame(previous.game)) game = previous.game;       // takes back 처음부터
    } else {
      game.entrants = previous.entrants;
      game.winners = previous.winners;
      if (game.log) game.log.length = previous.log || 0;
    }
    store();
    renderMatch(true);
  }
  function share() {
    var text = fill(t('wc.shareText', '나의 먹방 월드컵 우승 메뉴는 {dish}!'), { dish: name(result.id) });
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
  function ready() {
    restore();
    show('intro');
    renderIntro();
    // The splash font, fetched now so the first splash does not start in the fallback.
    if (!reduced && document.fonts && document.fonts.load) {
      document.fonts.load('1em Jua', t('wc.splash.quarter', '8강 진출!') + t('wc.splash.final', '결승!')).catch(function () {});
    }
  }
  function failed() {
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
  $('wcStart').addEventListener('click', function () { start(); });
  $('wcResume').addEventListener('click', resume);
  $('wcUndo').addEventListener('click', undo);
  $('wcRestart').addEventListener('click', start);
  $('wcAgain').addEventListener('click', start);
  $('wcShare').addEventListener('click', share);
  $('wcSaveImage').addEventListener('click', saveImage);
  $('wcHistoryClear').addEventListener('click', clearHistory);
  document.addEventListener('babdoduk-lang', render);
  document.addEventListener('babdoduk-lang', function () { endSplash('quiet'); });

  // Skipping a splash. A tap anywhere (on the up event, so it is never a pick; the down event
  // keeps focus on the card); any key but a bare modifier, browser shortcuts still work. A key
  // held from the pick or through the skip neither skips again nor picks: its repeats and its
  // release are swallowed.
  splashEl.addEventListener('click', function () { endSplash('skip'); });
  splashEl.addEventListener('mousedown', function (e) { e.preventDefault(); });
  splashEl.addEventListener('wheel', function () { endSplash('quiet'); }, { passive: true });
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
    var onMotion = function (e) { reduced = e.matches; if (reduced) endSplash('skip'); };
    if (motion.addEventListener) motion.addEventListener('change', onMotion);
    else if (motion.addListener) motion.addListener(onMotion);
  }

  getJson('data/foods/catalog.json').then(function (catalog) {
    return Promise.all((catalog.packs || []).map(function (pack) { return getJson(pack.src); })).then(function (packs) {
      packs.forEach(function (pack) { (pack.items || []).forEach(function (dish) { dishes[dish.id] = dish; }); });
      set = (cup.dishes || []).filter(function (id) { return dishes[id]; });
      size = cup.size || set.length;
      if (size < 4 || (size & (size - 1)) || set.length < size) throw new Error('bracket');
      basis = cup.basis || null;
    });
  }).then(ready, failed);
})();
