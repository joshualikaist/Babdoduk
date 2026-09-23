(function () {
  var app = document.getElementById('eatApp');
  var panel = document.getElementById('eatPanel');
  if (!app || !panel || !window.BabdodukFoods || !window.BabdodukSlot) return;

  var state = {
    view: 'home',
    hunger: 'any',
    answers: {},
    seenIds: [],
    result: null,
    spinning: false,
    ready: false,
    slot: null,
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

  // One persistent polite region: panel markup is replaced on every step.
  var status = document.getElementById('eatStatus');
  if (!status) {
    status = document.createElement('p');
    status.id = 'eatStatus';
    status.className = 'eat-sr';
    status.setAttribute('role', 'status');
    app.appendChild(status);
  }
  function announce(text) {
    status.textContent = text || '';
  }

  function reduceMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function answersFromHunger(hunger) {
    if (hunger === 'hungry') return { craving: 'hearty', kind: 'any', hunger: 'heavy', dining: 'any', budget: 'any' };
    if (hunger === 'light') return { craving: 'light', kind: 'any', hunger: 'light', dining: 'any', budget: 'any' };
    return { craving: 'any', kind: 'any', hunger: 'any', dining: 'any', budget: 'any' };
  }

  function destroySlot() {
    if (state.slot && state.slot.destroy) state.slot.destroy();
    state.slot = null;
  }

  function setView(view) {
    state.view = view;
    app.classList.toggle('eat--result', view === 'result');
    app.classList.toggle('eat--spin', view === 'home' && state.spinning);
  }

  function navRow() {
    return '<div class="eat-nav">' +
      '<button type="button" class="eat-textbtn" data-eat="back">' + escapeHtml(t('eat.back', '뒤로')) + '</button>' +
      '<span></span>' +
      '<button type="button" class="eat-textbtn" data-eat="reset">' + escapeHtml(t('eat.reset', '처음부터')) + '</button>' +
      '</div>';
  }

  function hungerRow() {
    var html = '<div class="eat-hunger" role="group" aria-label="' + escapeHtml(t('eat.hungerAria', '배고픈 정도')) + '">';
    HUNGERS.forEach(function (opt) {
      var on = state.hunger === opt.id;
      html += '<button type="button" class="eat-hchip' + (on ? ' is-on' : '') + '" data-eat="hunger" data-id="' + opt.id + '" aria-pressed="' + (on ? 'true' : 'false') + '"' + (state.spinning ? ' disabled' : '') + '>';
      html += escapeHtml(t(opt.label, opt.id));
      html += '</button>';
    });
    html += '</div>';
    return html;
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
    if (kind === 'spin') el.textContent = t('eat.hint.spin', '세 칸이 차례로 멈출 때까지 기다려 주세요.');
    else if (kind === 'land') el.textContent = t('eat.hint.land', '오늘의 한 끼가 정해졌어요.');
    else el.innerHTML = '<span class="eat-wheel-hint-main">' + escapeHtml(t('eat.hint.main', '버튼을 누르면 오늘의 메뉴가 뽑혀요')) + '</span>' +
      '<span class="eat-wheel-hint-sub">' + escapeHtml(t('eat.hint.sub', '카테고리, 음식, 느낌이 한 줄로 맞춰집니다.')) + '</span>';
  }

  function setSpinLabel(text) {
    var btn = panel.querySelector('[data-eat="spin"]');
    if (!btn) return;
    var label = btn.querySelector('.eat-spinbtn-label');
    if (label) label.textContent = text;
    else btn.textContent = text;
  }

  function catalogFoods() {
    return window.BabdodukFoods.all() || [];
  }

  function pickFood() {
    state.answers = answersFromHunger(state.hunger);
    var rec = window.BabdodukFoods.recommend(state.answers, { limit: 3, excludeIds: state.seenIds });
    var top = rec && rec.picks && rec.picks[0];
    return { rec: rec, food: top && top.food };
  }

  function mountSlot() {
    destroySlot();
    var host = document.getElementById('eatWheel');
    if (!host || !state.ready) return;
    state.closed = false;
    state.slot = window.BabdodukSlot.create({
      host: host,
      foods: catalogFoods(),
      reducedMotion: reduceMotion(),
      aria: t('eat.wheelAria', '오늘 메뉴를 뽑는 슬롯. 버튼을 누르면 세 칸이 돌아 한 끼가 정해집니다.'),
      onStatus: function (kind) {
        if (kind === 'spin') {
          state.spinning = true;
          app.classList.add('eat--spin');
          Array.prototype.forEach.call(panel.querySelectorAll('.eat-hchip'), function (el) {
            el.disabled = true;
          });
          var btn = panel.querySelector('[data-eat="spin"]');
          if (btn) btn.disabled = true;
          setSpinLabel(t('eat.spinning', '고르는 중…'));
          announce(t('eat.spinning', '고르는 중…'));
        }
        setHint(kind);
      },
      onSettle: function (payload) {
        if (state.closed) return;
        state.closed = true;
        finishSpin(payload && payload.food, payload && payload.labels);
      }
    });
  }

  function renderHome(focusSpin) {
    destroySlot();
    setView('home');
    state.spinning = false;
    state.closed = false;
    var html = '<div class="eat-home">';
    html += hungerRow();
    html += '<div class="eat-wheel" id="eatWheel"></div>';
    html += '<p class="eat-wheel-hint" id="eatWheelHint"></p>';
    html += '<button type="button" class="eat-spinbtn" data-eat="spin">';
    html += spinBtnInner(t('eat.spin', '오늘 메뉴 뽑기'));
    html += '</button></div>';
    panel.innerHTML = html;
    setHint('idle');
    mountSlot();
    if (focusSpin) {
      var spinBtn = panel.querySelector('[data-eat="spin"]');
      if (spinBtn) spinBtn.focus();
    }
  }

  function startSpin() {
    if (!state.slot || state.closed || state.spinning) return;
    if (state.slot.spinning && state.slot.spinning()) return;
    var picked = pickFood();
    if (!picked.food) {
      panel.innerHTML = navRow() + '<p class="eat-empty">' + escapeHtml(t('eat.empty', '지금은 맞는 메뉴가 없어요. 배고픔만 바꿔 다시 돌려볼까요.')) + '</p>';
      return;
    }
    state.pendingRec = picked.rec;
    state.pendingFood = picked.food;
    state.slot.spin(picked.food, catalogFoods());
  }

  function finishSpin(food, labels) {
    state.spinning = false;
    app.classList.remove('eat--spin');
    food = food || state.pendingFood;
    if (!food) {
      renderHome();
      return;
    }
    var rec = state.pendingRec || window.BabdodukFoods.recommend(state.answers, { limit: 3, excludeIds: state.seenIds });
    var ranked = rec.ranked.filter(function (row) { return row.food.id === food.id; });
    if (ranked[0]) {
      rec.picks = [ranked[0]].concat(rec.picks.filter(function (row) { return row.food.id !== food.id; })).slice(0, 3);
    } else {
      rec.picks = [{ food: food, score: 80, parts: {}, chips: [], labels: labels }].concat(rec.picks).slice(0, 3);
    }
    rec.picks[0].labels = labels || window.BabdodukSlot.labelsOf(food);
    state.result = rec;
    destroySlot();
    renderResult(true);
  }

  function resultLine(row) {
    var labels = row && row.labels;
    // Slot labels are Korean-only reel text; English shows the reasons alone.
    if (!labels || !labels.length || lang() === 'en') return '';
    return t('eat.result.slot', '{a} · {b} · {c}')
      .replace('{a}', labels[0] || '')
      .replace('{b}', labels[1] || '')
      .replace('{c}', labels[2] || '');
  }

  function reasons(row) {
    var list = (row.chips || []).map(function (chip) {
      return t('eat.reason.' + chip, '');
    }).filter(Boolean);
    return list.length ? list : [t('eat.reason.default', '배고픈 정도와 지금 시간을 기준으로 골랐어요')];
  }

  function renderResult(focusResult) {
    setView('result');
    var rec = state.result;
    if (!rec || !rec.picks.length) {
      panel.innerHTML = navRow() + '<p class="eat-empty">' + escapeHtml(t('eat.empty', '지금은 맞는 메뉴가 없어요. 배고픔만 바꿔 다시 돌려볼까요.')) + '</p>';
      return;
    }
    var top = rec.picks[0];
    var rest = rec.picks.slice(1);
    var line = resultLine(top);
    var html = navRow();
    html += '<p class="eat-kicker">' + escapeHtml(t('eat.result.kicker', '오늘의 밥도둑 PICK')) + '</p>';
    html += '<article class="eat-hero eat-hero--slot">';
    html += '<span class="eat-num">01</span>';
    html += '<h3 tabindex="-1">' + escapeHtml(foodName(top.food)) + '</h3>';
    if (line) html += '<p class="eat-whyline">' + escapeHtml(line) + '</p>';
    html += '<p class="eat-reasons-label">' + escapeHtml(t('eat.reasons', '추천 이유')) + '</p><ul class="eat-reasons">';
    reasons(top).forEach(function (text) {
      html += '<li>' + escapeHtml(text) + '</li>';
    });
    html += '</ul>';
    html += '<p class="eat-scope">' + escapeHtml(t('eat.scope', '음식 아이디어 추천이에요. 판매 여부·가격·알레르기는 가게에서 확인해 주세요.')) + '</p>';
    html += '<div class="eat-cta">';
    html += '<button type="button" class="eat-btn eat-btn--main" data-eat="take" data-id="' + top.food.id + '">' + escapeHtml(t('eat.take', '이걸로 할래')) + '</button>';
    html += '<button type="button" class="eat-btn" data-eat="more">' + escapeHtml(t('eat.more', '다시 돌리기')) + '</button>';
    html += '</div>';
    html += '<div class="eat-feedback" role="group" aria-label="' + escapeHtml(t('eat.fb.aria', '이 추천은 어땠나요')) + '">';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="like" data-id="' + top.food.id + '" aria-pressed="false">' + escapeHtml(t('eat.fb.like', '좋아요')) + '</button>';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="dislike" data-id="' + top.food.id + '" aria-pressed="false">' + escapeHtml(t('eat.fb.dislike', '별로예요')) + '</button>';
    html += '<button type="button" class="eat-fb" data-eat="fb" data-kind="eaten" data-id="' + top.food.id + '" aria-pressed="false">' + escapeHtml(t('eat.fb.eaten', '먹었어요')) + '</button>';
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
    announce(t('eat.announce', '추천 메뉴: {dish}').replace('{dish}', foodName(top.food)));
    if (focusResult) {
      var heading = panel.querySelector('.eat-hero h3');
      if (heading) heading.focus();
    }
  }

  function goHome(opts) {
    opts = opts || {};
    announce('');
    destroySlot();
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
      slot: null,
      closed: false,
      pendingRec: null,
      pendingFood: null
    };
    renderHome(true);
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
    renderResult(true);
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
      var chosen = panel.querySelector('[data-eat="hunger"][data-id="' + state.hunger + '"]');
      if (chosen) chosen.focus();
      return;
    }
    if (act === 'spin') startSpin();
    if (act === 'back') goHome({ keepHunger: true });
    if (act === 'reset') goHome({});
    if (act === 'more') {
      markSeen();
      goHome({ keepHunger: true, keepSeen: true });
    }
    if (act === 'take') {
      window.BabdodukFoods.prefs.feedback(btn.getAttribute('data-id'), 'like');
      btn.textContent = t('eat.taken', '좋아요, 이걸로 골랐어요.');
      btn.setAttribute('aria-disabled', 'true');
      btn.removeAttribute('data-eat');
      announce(t('eat.taken', '좋아요, 이걸로 골랐어요.'));
    }
    if (act === 'fb') {
      var kind = btn.getAttribute('data-kind');
      window.BabdodukFoods.prefs.feedback(btn.getAttribute('data-id'), kind);
      btn.classList.add('is-on');
      btn.setAttribute('aria-pressed', 'true');
      Array.prototype.forEach.call(panel.querySelectorAll('.eat-fb'), function (el) {
        if (el !== btn) {
          el.classList.remove('is-on');
          el.setAttribute('aria-pressed', 'false');
        }
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
  document.addEventListener('babdoduk-lang', function () { render(); });

  window.BabdodukFoods.load().then(function () {
    state.ready = true;
    renderHome();
  }).catch(function () {
    panel.innerHTML = '<p class="eat-empty">' + escapeHtml(t('eat.loadFail', '메뉴 데이터를 아직 못 읽었어요.')) + '</p>';
  });
})();
