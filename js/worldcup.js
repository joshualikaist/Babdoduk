/* Babdoduk food world cup (worldcup.html): each game draws `size` dishes (32) from the pool in
   data/content/worldcup.json (the sync writes it into the page as window.BABDODUK_WORLDCUP;
   data/content/ is never deployed) and plays them two at a time, with names and flavours from the
   food catalog (data/foods/). A pick pops, a new round gets a banner, the winner gets confetti and
   a result image to save. Progress and past winners stay in this browser (localStorage
   `babdoduk-worldcup`). Lab only, stage 2 (docs/WORLDCUP_STATS.md): with the public project
   config, everyone's anonymous counts are read and a finished game is recorded once through the
   validating RPC worldcup_record_game; without it, or when that fails, the game is unchanged. */
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
    renderRanking();
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
    if (resumable) $('wcResume').textContent = fill(t('wc.resume', '이어서 하기 · {round} {n}/{total}'), progress());
  }
  function renderMatch(focus) {
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
    renderLastPick();
    var next = game.winners.length * 2 + 2;
    preload([game.entrants[next], game.entrants[next + 1]]);
    $('wcUndo').disabled = !game.stack.length;
    if (focus) {
      // Keep the round title and both cards in view rather than scrolling to the focused card.
      cards[0].focus({ preventScroll: true });
      var box = $('wcMatch').getBoundingClientRect();
      if (box.top < 0 || box.top > window.innerHeight * 0.4) $('wcMatch').scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
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
  // ---- everyone's picks (lab, stage 2) ----------------------------------------------------------
  var stats = {}, totalGames = 0, statsApi = null, lastPick = null;
  function statsConfig() {
    var c = window.BABDODUK_PUBLIC_FEED_CONFIG;
    try {
      var url = new URL(c.SUPABASE_URL), key = c.SUPABASE_PUBLISHABLE_KEY;
      if (url.protocol !== 'https:' || url.pathname !== '/' || url.search || url.hash || url.username) return null;
      if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) return null;
      return { base: url.origin + '/rest/v1/', key: key };
    } catch (e) { return null; }
  }
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
  function loadStats() {
    if (!statsApi) return Promise.resolve();
    return Promise.all([api('worldcup_dish_stats?select=dish_id,matches,wins,entries,titles'),
                        api('worldcup_totals?select=games')]).then(function (got) {
      stats = {};
      (got[0] || []).forEach(function (row) { if (dishes[row.dish_id]) stats[row.dish_id] = row; });
      totalGames = (got[1] && got[1][0] && got[1][0].games) || 0;
      render();
    }).catch(function () { stats = {}; totalGames = 0; renderRanking(); });
  }
  // A finished game, once: the whole bracket in play order. The server checks it against the pool.
  function record(log) {
    if (!statsApi || !log || log.length !== size - 1) return;
    api('rpc/worldcup_record_game', { p_size: size, p_matches: log }).then(loadStats, function () {});
  }
  function winRate(id) {
    var s = stats[id];
    return s && s.matches >= 3 ? Math.round(s.wins / s.matches * 100) : null;
  }
  function ranked() {
    return Object.keys(stats).filter(function (id) { return stats[id].entries >= 3; }).sort(function (a, b) {
      var x = stats[a], y = stats[b];
      return y.titles / y.entries - x.titles / x.entries || y.wins / Math.max(y.matches, 1) - x.wins / Math.max(x.matches, 1);
    });
  }
  function renderLastPick() {
    var line = $('wcLastPick');
    if (!lastPick || !statsApi || !Object.keys(stats).length) { line.hidden = true; return; }
    var a = winRate(lastPick.w), b = winRate(lastPick.l);
    line.textContent = a !== null && b !== null
      ? fill(t('wc.last', '방금 고른 {a}: 모두의 승률 {pa}% · {b} {pb}%'), { a: name(lastPick.w), pa: a, b: name(lastPick.l), pb: b })
      : fill(t('wc.lastNew', '방금 고른 {a}: 아직 모두의 기록이 적어요'), { a: name(lastPick.w) });
    line.hidden = false;
  }
  function renderRanking() {
    var box = $('wcRanking'), list = $('wcRankingList'), order = ranked();
    box.hidden = !statsApi || !totalGames || !order.length || view === 'match' || view === 'loading';
    if (box.hidden) return;
    $('wcRankingTotal').textContent = fill(t('wc.rankingTotal', '지금까지 {n}판'), { n: totalGames.toLocaleString() });
    list.textContent = '';
    order.slice(0, 10).forEach(function (id, i) {
      var s = stats[id], item = document.createElement('li'), photo = (cup.photos || {})[id];
      if (photo) {
        var img = document.createElement('img');
        img.src = photo.image; img.alt = ''; img.width = 48; img.height = 36; img.loading = 'lazy';
        item.appendChild(img);
      }
      var label = document.createElement('span');
      label.className = 'wc-ranking-name';
      label.textContent = (i + 1) + '. ' + name(id);
      var rate = document.createElement('span');
      rate.className = 'wc-ranking-rate';
      rate.textContent = fill(t('wc.rankingRate', '우승 {t}% · 승률 {w}%'),
        { t: Math.round(s.titles / s.entries * 100), w: Math.round(s.wins / Math.max(s.matches, 1) * 100) });
      item.appendChild(label);
      item.appendChild(rate);
      list.appendChild(item);
    });
    var mine = $('wcRankingMine');
    var place = result ? order.indexOf(result.id) : -1;
    mine.hidden = view !== 'result' || place < 0;
    if (!mine.hidden) mine.textContent = fill(t('wc.rankingMine', '내 우승 메뉴 {dish}는 모두의 랭킹 {n}위예요'), { dish: name(result.id), n: place + 1 });
  }
  function render() {
    if (view === 'intro') renderIntro();
    if (view === 'match') renderMatch(null);
    if (view === 'result') renderResult(false);
    renderHistory();
    renderRanking();
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
    game = { entrants: shuffle(set).slice(0, size), winners: [], stack: [], log: [] };
    lastPick = null;
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
    record(game.log);
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
    if (busy || view !== 'match') return;
    var ids = pair(), chosen = ids[side];
    game.stack.push({ entrants: game.entrants.slice(), winners: game.winners.slice(), log: (game.log || []).length });
    game.winners.push(chosen);
    if (game.log) game.log.push([chosen, ids[1 - side]]);
    lastPick = { w: chosen, l: ids[1 - side] };
    if (game.winners.length * 2 === game.entrants.length) {
      if (game.winners.length === 1) { finish(chosen, ids[1 - side]); return; }
      game.entrants = game.winners;
      game.winners = [];
    }
    store();
    var newRound = game.winners.length === 0;          // this pick closed a round
    if (reduced) { renderMatch(true); if (newRound) banner(); return; }
    busy = true;
    cards[side].classList.add('is-picked');
    cards[1 - side].classList.add('is-dropped');
    burst(cards[side]);
    setTimeout(function () {
      cards[side].classList.remove('is-picked');
      cards[1 - side].classList.remove('is-dropped');
      busy = false;
      renderMatch(true);
      if (newRound) banner();
    }, 480);
  }

  // ---- celebration ---------------------------------------------------------------------------
  // A round banner ("16강 진출!", "결승전!") for a moment; screen readers get the match announcement.
  function banner() {
    var el = $('wcBanner'), round = game.entrants.length;
    el.textContent = round === 2 ? t('wc.banner.final', '결승전!') : round === 4 ? t('wc.banner.semi', '준결승!')
      : fill(t('wc.banner.n', '{n}강 진출!'), { n: round });
    el.hidden = false;
    el.classList.remove('is-on');
    void el.offsetWidth;                                // restart the animation
    el.classList.add('is-on');
    clearTimeout(banner.timer);
    banner.timer = setTimeout(function () { el.hidden = true; el.classList.remove('is-on'); }, 1100);
  }
  // Confetti on a full-window canvas that ignores the pointer and removes itself; nothing with
  // reduced motion. A pick gets a small burst from the card, the winner two big ones.
  var COLORS = ['#f45e45', '#ffb703', '#219ebc', '#8ecae6', '#fb8500', '#6a994e', '#c77dff'];
  function confetti(origins, count, duration) {
    if (reduced) return;
    var canvas = document.createElement('canvas');
    canvas.className = 'wc-confetti';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.appendChild(canvas);
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
                    color: COLORS[i % COLORS.length], shape: i % 3 });
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
      ctx.fillStyle = '#b43d27';
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
        status.textContent = t('wc.saved', '이미지를 저장했어요.');
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
    game.entrants = previous.entrants;
    game.winners = previous.winners;
    if (game.log) game.log.length = previous.log || 0;
    lastPick = null;
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
    statsApi = statsConfig();
    loadStats();
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
  $('wcSaveImage').addEventListener('click', saveImage);
  $('wcHistoryClear').addEventListener('click', clearHistory);
  document.addEventListener('babdoduk-lang', render);

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
