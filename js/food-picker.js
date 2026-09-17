(function () {
  var app = document.getElementById('eatApp');
  var panel = document.getElementById('eatPanel');
  if (!app || !panel || !window.BabdodukFoods || !window.BabdodukRoulette) return;

  var POCKETS = window.BabdodukRoulette.EURO.length;

  var state = {
    view: 'home',
    hunger: 'any',
    answers: {},
    seenIds: [],
    result: null,
    spinning: false,
    ready: false,
    wheel: null,
    pockets: [],
    closed: false
  };

  var HUNGERS = [
    { id: 'hungry', label: 'eat.hunger.hungry' },
    { id: 'light', label: 'eat.hunger.light' },
    { id: 'any', label: 'eat.hunger.any' }
  ];

  function t(key, fallback) {
    var langNow = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[langNow];
    if (pack && pack[key] != null) return pack[key];
    return fallback || key;
  }

  function lang() {
    return window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
  }

  function foodName(food) {
    return lang() === 'en' ? food.nameEn : food.nameKo;
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function reduceMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function answersFromHunger(hunger) {
    if (hunger === 'hungry') return { craving: 'hearty', kind: 'any', hunger: 'heavy', dining: 'any', budget: 'any' };
    if (hunger === 'light') return { craving: 'light', kind: 'any', hunger: 'light', dining: 'any', budget: 'any' };
    return { craving: 'any', kind: 'any', hunger: 'any', dining: 'any', budget: 'any' };
  }

  function chipLabel(id) {
    return t('eat.chip.' + id, id);
  }

  function shuffle(list) {
    var arr = list.slice();
    var i;
    for (i = arr.length - 1; i > 0; i -= 1) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i];
      arr[i] = arr[j];
      arr[j] = tmp;
    }
    return arr;
  }

  function destroyWheel() {
    if (state.wheel && state.wheel.destroy) state.wheel.destroy();
    state.wheel = null;
  }

  function setView(view) {
    state.view = view;
    app.classList.toggle('eat--result', view === 'result');
    app.classList.toggle('eat--spin', view === 'home' && state.spinning);
  }

  function navRow() {
    var html = '<div class="eat-nav">';
    html += '<button type="button" class="eat-textbtn" data-eat="back">' + escapeHtml(t('eat.back', '뒤로')) + '</button>';
    html += '<span></span>';
    html += '<button type="button" class="eat-textbtn" data-eat="reset">' + escapeHtml(t('eat.reset', '처음부터')) + '</button>';
    html += '</div>';
    return html;
  }

  function hungerRow() {
    var html = '<div class="eat-hunger" role="radiogroup" aria-label="' + escapeHtml(t('eat.hungerAria', '배고픈 정도')) + '">';
    HUNGERS.forEach(function (opt) {
      var on = state.hunger === opt.id;
      html += '<button type="button" class="eat-hchip' + (on ? ' is-on' : '') + '" data-eat="hunger" data-id="' + opt.id + '" role="radio" aria-checked="' + (on ? 'true' : 'false') + '"' + (state.spinning ? ' disabled' : '') + '>';
      html += escapeHtml(t(opt.label, opt.id));
      html += '</button>';
    });
    html += '</div>';
    return html;
  }

  function hungerPool() {
    var answers = answersFromHunger(state.hunger);
    state.answers = answers;
    var pick = window.BabdodukFoods.quickPick({ answers: answers, excludeIds: state.seenIds });
    var rolling = (pick && pick.rolling) ? pick.rolling.slice() : [];
    var all = window.BabdodukFoods.all() || [];
    var skip = {};
    state.seenIds.forEach(function (id) { skip[id] = true; });
    var extra = shuffle(all.filter(function (food) {
      if (!food || skip[food.id]) return false;
      if (answers.hunger === 'heavy' && (food.satiety || 0) < 3) return false;
      if (answers.hunger === 'light' && (food.satiety || 0) > 3) return false;
      return true;
    }));
    var seen = {};
    var out = [];
    rolling.concat(extra).forEach(function (food) {
      if (!food || seen[food.id]) return;
      seen[food.id] = true;
      out.push(food);
    });
    if (out.length < POCKETS) {
      shuffle(all).forEach(function (food) {
        if (out.length >= POCKETS) return;
        if (!food || seen[food.id]) return;
        seen[food.id] = true;
        out.push(food);
      });
    }
    while (out.length < POCKETS && out.length) out.push(out[out.length % Math.max(out.length, 1)]);
    return out.slice(0, POCKETS);
  }

  function buildPockets() {
    var foods = hungerPool();
    return window.BabdodukRoulette.EURO.map(function (num, idx) {
      return {
        number: num,
        color: window.BabdodukRoulette.colorOf(num),
        index: idx,
        food: foods[idx] || foods[0]
      };
    });
  }

  function idleHintHtml() {
    return '<span class="eat-wheel-hint-main">' + escapeHtml(t('eat.hint.main', '휠을 밀거나 연타해보세요')) + '</span>' +
      '<span class="eat-wheel-hint-sub">' + escapeHtml(t('eat.hint.sub', '세게, 오래 누를수록 더 오래 돌아가요.')) + '</span>';
  }

  function spinBtnInner(label) {
    return '<svg class="eat-spinbtn-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      '<path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M4.8 12a7.2 7.2 0 0 1 12.2-5.2M19.2 12a7.2 7.2 0 0 1-12.2 5.2"/>' +
      '<path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M16.2 4.8v3.4h-3.4M7.8 19.2v-3.4h3.4"/>' +
      '</svg><span class="eat-spinbtn-label">' + escapeHtml(label) + '</span>';
  }

  function setHint(kind) {
    var el = document.getElementById('eatWheelHint');
    if (!el) return;
    if (kind === 'charge') el.textContent = t('eat.hint.charge', '손을 떼면 그 힘으로 공이 나갑니다.');
    else if (kind === 'spin') el.textContent = t('eat.hint.spin', '공이 트랙에서 떨어지는 중. 세게 밀수록 오래 돕니다.');
    else if (kind === 'land') el.textContent = t('eat.hint.land', '공이 칸에 멈췄어요.');
    else el.innerHTML = idleHintHtml();
  }

  function mountWheel() {
    destroyWheel();
    var host = document.getElementById('eatWheel');
    if (!host || !state.ready) return;
    state.pockets = buildPockets();
    state.closed = false;
    state.wheel = window.BabdodukRoulette.create({
      host: host,
      pockets: state.pockets,
      reducedMotion: reduceMotion(),
      aria: t('eat.wheelAria', '오늘 뭐 먹지 다이얼. 밀어 돌리면 공이 칸에 떨어집니다.'),
      onStatus: function (kind) {
        if (kind === 'spin') {
          state.spinning = true;
          app.classList.add('eat--spin');
          Array.prototype.forEach.call(panel.querySelectorAll('.eat-hchip'), function (el) {
            el.disabled = true;
          });
          var btn = panel.querySelector('[data-eat="spin"]');
          if (btn) {
            btn.disabled = true;
            var label = btn.querySelector('.eat-spinbtn-label');
            if (label) label.textContent = t('eat.spinning', '공이 도는 중');
            else btn.textContent = t('eat.spinning', '공이 도는 중');
          }
        }
        setHint(kind);
      },
      onSettle: function (pocket) {
        if (state.closed) return;
        state.closed = true;
        finishSpin(pocket && pocket.food, pocket);
      }
    });
  }

  function renderHome() {
    destroyWheel();
    setView('home');
    state.spinning = false;
    state.closed = false;
    var html = '<div class="eat-home">';
    html += hungerRow();
    html += '<div class="eat-wheel" id="eatWheel"></div>';
    html += '<p class="eat-wheel-hint" id="eatWheelHint">' + idleHintHtml() + '</p>';
    html += '<button type="button" class="eat-spinbtn" data-eat="spin">';
    html += spinBtnInner(t('eat.spin', '한 번 돌려보기'));
    html += '</button>';
    html += '</div>';
    panel.innerHTML = html;
    mountWheel();
  }

  function nudgeSpin() {
    if (!state.wheel || state.closed) return;
    if (reduceMotion()) {
      state.wheel.impulse(8);
      return;
    }
    var strength = 7 + Math.random() * 5;
    state.wheel.impulse(strength);
  }

  function finishSpin(food, pocket) {
    state.spinning = false;
    app.classList.remove('eat--spin');
    if (!food) {
      renderHome();
      return;
    }
    var rec = window.BabdodukFoods.recommend(state.answers, { limit: 3, excludeIds: state.seenIds });
    var ranked = rec.ranked.filter(function (row) { return row.food.id === food.id; });
    if (ranked[0]) {
      rec.picks = [ranked[0]].concat(rec.picks.filter(function (row) { return row.food.id !== food.id; })).slice(0, 3);
    } else {
      rec.picks = [{ food: food, score: 80, parts: {}, chips: [], pocket: pocket }].concat(rec.picks).slice(0, 3);
    }
    rec.picks[0].pocket = pocket;
    state.result = rec;
    destroyWheel();
    renderResult();
  }

  function pocketLine(row) {
    var pocket = row && row.pocket;
    if (!pocket || pocket.number == null) return t('eat.result.blurb', '지금 시간과 한 끼의 크기에 맞춰 골랐어요.');
    var colorKey = 'eat.color.' + (pocket.color || 'black');
    var color = t(colorKey, pocket.color);
    return t('eat.result.pocket', '공이 {n} {c}에 멈췄어요.').replace('{n}', String(pocket.number)).replace('{c}', color);
  }

  function renderResult() {
    setView('result');
    var rec = state.result;
    if (!rec || !rec.picks.length) {
      panel.innerHTML = navRow() + '<p class="eat-empty">' + escapeHtml(t('eat.empty', '지금은 맞는 메뉴가 없어요. 배고픔만 바꿔 다시 돌려볼까요.')) + '</p>';
      return;
    }
    var top = rec.picks[0];
    var rest = rec.picks.slice(1);
    var match = Math.round(Math.min(99, Math.max(62, top.score)));
    var html = navRow();
    html += '<p class="eat-kicker">' + escapeHtml(t('eat.result.kicker', '오늘의 밥도둑 PICK')) + '</p>';
    html += '<article class="eat-hero">';
    html += '<span class="eat-num">01</span>';
    html += '<h3>' + escapeHtml(foodName(top.food)) + '</h3>';
    html += '<p class="eat-whyline">' + escapeHtml(pocketLine(top)) + '</p>';
    html += '<p class="eat-match"><b>' + match + '%</b> MATCH</p>';
    html += '<p class="eat-chips">';
    (top.chips || []).forEach(function (chip) {
      html += '<span>' + escapeHtml(chipLabel(chip)) + '</span>';
    });
    html += '</p>';
    html += '<div class="eat-cta">';
    html += '<button type="button" class="eat-btn eat-btn--main" data-eat="take" data-id="' + top.food.id + '">' + escapeHtml(t('eat.take', '이거 먹을래')) + '</button>';
    html += '<button type="button" class="eat-btn" data-eat="more">' + escapeHtml(t('eat.more', '다시 돌리기')) + '</button>';
    html += '</div>';
    html += '<button type="button" class="eat-textbtn eat-why-toggle" data-eat="why" aria-expanded="false">' + escapeHtml(t('eat.why', '왜 이거야?')) + '</button>';
    html += '<div class="eat-explain" hidden><p>' + escapeHtml(explainText(top)) + '</p></div>';
    html += '<div class="eat-feedback" role="group" aria-label="' + escapeHtml(t('eat.fb.aria', '이 추천은 어땠나요')) + '">';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="like" data-id="' + top.food.id + '">' + escapeHtml(t('eat.fb.like', '좋아요')) + '</button>';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="dislike" data-id="' + top.food.id + '">' + escapeHtml(t('eat.fb.dislike', '별로예요')) + '</button>';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="eaten" data-id="' + top.food.id + '">' + escapeHtml(t('eat.fb.eaten', '먹었어요')) + '</button>';
    html += '</div></article>';
    if (rest.length) {
      html += '<p class="eat-alts-label">' + escapeHtml(t('eat.alts', '다른 추천')) + '</p>';
      html += '<ul class="eat-alts">';
      rest.forEach(function (row, idx) {
        html += '<li><button type="button" class="eat-alt" data-eat="alt" data-id="' + row.food.id + '"><span>0' + (idx + 2) + '</span><strong>' + escapeHtml(foodName(row.food)) + '</strong></button></li>';
      });
      html += '</ul>';
    }
    panel.innerHTML = html;
  }

  function explainText(row) {
    var base = t('eat.why.body', '미는 힘과 공의 감속이 칸을 정했어요.');
    var labels = (row.chips || []).map(chipLabel);
    if (!labels.length) return base;
    return labels.join(' + ') + '\n' + t('eat.why.tail', '그 조건의 메뉴가 37칸에 올라가 있었어요.');
  }

  function goHome(opts) {
    opts = opts || {};
    destroyWheel();
    var hunger = opts.keepHunger ? state.hunger : 'any';
    var seen = opts.keepSeen ? state.seenIds.slice() : [];
    state = {
      view: 'home',
      hunger: hunger,
      answers: {},
      seenIds: seen,
      result: null,
      spinning: false,
      ready: state.ready,
      wheel: null,
      pockets: [],
      closed: false
    };
    renderHome();
  }

  function markSeen() {
    (state.result && state.result.picks || []).forEach(function (row) {
      if (row.food && state.seenIds.indexOf(row.food.id) === -1) state.seenIds.push(row.food.id);
    });
  }

  function promote(id) {
    if (!state.result) return;
    var row = null;
    state.result.ranked.forEach(function (item) {
      if (item.food.id === id) row = item;
    });
    if (!row) return;
    var others = state.result.picks.filter(function (item) { return item.food.id !== id; });
    state.result.picks = [row].concat(others).slice(0, 3);
    renderResult();
  }

  function onClick(e) {
    var node = e.target;
    var btn = null;
    while (node && node !== panel) {
      if (node.getAttribute && node.getAttribute('data-eat')) {
        btn = node;
        break;
      }
      node = node.parentElement;
    }
    if (!btn || !panel.contains(btn)) return;
    var act = btn.getAttribute('data-eat');
    if (act === 'hunger') {
      if (state.spinning) return;
      state.hunger = btn.getAttribute('data-id');
      renderHome();
      return;
    }
    if (act === 'spin') nudgeSpin();
    if (act === 'back') goHome({ keepHunger: true });
    if (act === 'reset') goHome({});
    if (act === 'more') {
      markSeen();
      goHome({ keepHunger: true, keepSeen: true });
    }
    if (act === 'take') {
      window.BabdodukFoods.prefs.feedback(btn.getAttribute('data-id'), 'eaten');
      btn.textContent = t('eat.taken', '좋아, 그걸로.');
      btn.disabled = true;
    }
    if (act === 'why') {
      var box = panel.querySelector('.eat-explain');
      var open = box && box.hasAttribute('hidden');
      if (box) {
        if (open) box.removeAttribute('hidden');
        else box.setAttribute('hidden', '');
      }
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    if (act === 'fb') {
      var kind = btn.getAttribute('data-kind');
      window.BabdodukFoods.prefs.feedback(btn.getAttribute('data-id'), kind);
      btn.classList.add('is-on');
      Array.prototype.forEach.call(panel.querySelectorAll('.eat-fb'), function (el) {
        if (el !== btn) el.classList.remove('is-on');
      });
      if (kind === 'dislike') {
        var hideId = btn.getAttribute('data-id');
        if (state.seenIds.indexOf(hideId) === -1) state.seenIds.push(hideId);
        goHome({ keepHunger: true, keepSeen: true });
      }
    }
    if (act === 'alt') promote(btn.getAttribute('data-id'));
  }

  function render() {
    if (state.view === 'result') renderResult();
    else if (!state.spinning) renderHome();
  }

  panel.addEventListener('click', onClick);

  document.addEventListener('babdoduk-lang', function () {
    render();
  });

  window.BabdodukFoods.load().then(function () {
    state.ready = true;
    renderHome();
  }).catch(function () {
    panel.innerHTML = '<p class="eat-empty">' + escapeHtml(t('eat.loadFail', '메뉴 데이터를 아직 못 읽었어요.')) + '</p>';
  });
})();
