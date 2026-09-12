(function () {
  var app = document.getElementById('eatApp');
  var panel = document.getElementById('eatPanel');
  if (!app || !panel || !window.BabdodukFoods) return;

  var ROW = 56;
  var VISIBLE = 5;
  var CENTER = 2;
  var COPIES = 5;

  var state = {
    view: 'home',
    hunger: 'any',
    answers: {},
    seenIds: [],
    result: null,
    idlePool: [],
    spinning: false,
    spinTimer: null,
    ready: false
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

  function idleFoods() {
    if (state.idlePool.length >= 12) return state.idlePool;
    var all = window.BabdodukFoods.all() || [];
    state.idlePool = shuffle(all).slice(0, 12);
    if (!state.idlePool.length) state.idlePool = all.slice(0, 12);
    return state.idlePool;
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

  function reelMarkup(foods, activeIndex) {
    var html = '<div class="eat-reel" aria-hidden="true">';
    html += '<div class="eat-reel-window">';
    html += '<div class="eat-reel-aim"></div>';
    html += '<div class="eat-reel-band" id="eatReelBand">';
    foods.forEach(function (food, idx) {
      html += '<div class="eat-reel-item' + (idx === activeIndex ? ' is-on' : '') + '">' + escapeHtml(foodName(food)) + '</div>';
    });
    html += '</div></div></div>';
    return html;
  }

  function repeatFoods(pool, copies) {
    var items = [];
    var c;
    for (c = 0; c < copies; c += 1) {
      pool.forEach(function (food) { items.push(food); });
    }
    return items;
  }

  function indexOfFood(list, food) {
    var i;
    for (i = 0; i < list.length; i += 1) {
      if (list[i] && food && list[i].id === food.id) return i;
    }
    return -1;
  }

  function renderHome() {
    setView('home');
    var pool = idleFoods();
    var items = state.spinning ? [] : repeatFoods(pool, 2);
    var active = CENTER;
    var html = '<div class="eat-home">';
    html += hungerRow();
    html += reelMarkup(items, items.length ? active : -1);
    html += '<button type="button" class="eat-spinbtn" data-eat="spin"' + (state.spinning ? ' disabled' : '') + '>';
    html += escapeHtml(state.spinning ? t('eat.spinning', '고르는 중') : t('eat.spin', '돌려보기'));
    html += '</button>';
    html += '</div>';
    panel.innerHTML = html;
    var band = document.getElementById('eatReelBand');
    if (band) {
      band.style.transition = 'none';
      band.style.transform = 'translateY(0px)';
    }
    markCenter(items, 0);
  }

  function markCenter(items, offsetY) {
    var band = document.getElementById('eatReelBand');
    if (!band) return;
    var idx = Math.round((-offsetY) / ROW) + CENTER;
    var nodes = band.children;
    var i;
    for (i = 0; i < nodes.length; i += 1) {
      if (i === idx) nodes[i].classList.add('is-on');
      else nodes[i].classList.remove('is-on');
    }
  }

  function startSpin() {
    if (state.spinning || !state.ready) return;
    var answers = answersFromHunger(state.hunger);
    var pick = window.BabdodukFoods.quickPick({ answers: answers, excludeIds: state.seenIds });
    if (!pick || !pick.food) {
      panel.innerHTML = '<p class="eat-empty">' + escapeHtml(t('eat.empty', '지금은 맞는 메뉴가 없어요. 배고픔만 바꿔 다시 돌려볼까요.')) + '</p>';
      return;
    }
    state.answers = pick.answers || answers;
    state.spinning = true;
    if (state.view !== 'home') renderHome();
    else {
      var btn = panel.querySelector('[data-eat="spin"]');
      if (btn) {
        btn.disabled = true;
        btn.textContent = t('eat.spinning', '고르는 중');
      }
      Array.prototype.forEach.call(panel.querySelectorAll('.eat-hchip'), function (el) {
        el.disabled = true;
      });
    }
    app.classList.add('eat--spin');

    var pool = (pick.rolling && pick.rolling.length ? pick.rolling.slice() : []).concat(idleFoods());
    var seen = {};
    var unique = [];
    pool.forEach(function (food) {
      if (!food || seen[food.id]) return;
      seen[food.id] = true;
      unique.push(food);
    });
    unique = shuffle(unique).slice(0, 12);
    if (indexOfFood(unique, pick.food) === -1) unique[Math.floor(unique.length / 2)] = pick.food;
    var cycle = unique.length;
    var items = repeatFoods(unique, COPIES);
    var winnerInPool = indexOfFood(unique, pick.food);
    var target = (COPIES - 1) * cycle + winnerInPool;
    var endY = -((target - CENTER) * ROW);
    var startY = 0;

    var band = document.getElementById('eatReelBand');
    if (!band) {
      finishSpin(pick.food);
      return;
    }
    band.innerHTML = items.map(function (food) {
      return '<div class="eat-reel-item">' + escapeHtml(foodName(food)) + '</div>';
    }).join('');
    band.style.transition = 'none';
    band.style.transform = 'translateY(' + startY + 'px)';
    markCenter(items, startY);

    if (reduceMotion()) {
      band.style.transform = 'translateY(' + endY + 'px)';
      markCenter(items, endY);
      finishSpin(pick.food);
      return;
    }

    var done = false;
    function settle() {
      if (done) return;
      done = true;
      if (state.spinTimer) {
        clearTimeout(state.spinTimer);
        state.spinTimer = null;
      }
      band.removeEventListener('transitionend', onEnd);
      markCenter(items, endY);
      state.spinTimer = setTimeout(function () {
        finishSpin(pick.food);
      }, 280);
    }
    function onEnd(e) {
      if (e && e.propertyName && e.propertyName !== 'transform') return;
      settle();
    }

    band.offsetHeight;
    band.addEventListener('transitionend', onEnd);
    band.style.transition = 'transform 1.42s cubic-bezier(0.12, 0.82, 0.08, 1)';
    band.style.transform = 'translateY(' + endY + 'px)';
    if (state.spinTimer) clearTimeout(state.spinTimer);
    state.spinTimer = setTimeout(settle, 1700);
  }

  function finishSpin(food) {
    state.spinning = false;
    app.classList.remove('eat--spin');
    var rec = window.BabdodukFoods.recommend(state.answers, { limit: 3, excludeIds: state.seenIds });
    var ranked = rec.ranked.filter(function (row) { return row.food.id === food.id; });
    if (ranked[0]) {
      rec.picks = [ranked[0]].concat(rec.picks.filter(function (row) { return row.food.id !== food.id; })).slice(0, 3);
    } else if (food) {
      rec.picks = [{ food: food, score: 80, parts: {}, chips: [] }].concat(rec.picks).slice(0, 3);
    }
    state.result = rec;
    renderResult();
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
    html += '<p class="eat-whyline">' + escapeHtml(t('eat.result.blurb', '지금 시간과 한 끼의 크기에 맞춰 골랐어요.')) + '</p>';
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
    var labels = (row.chips || []).map(chipLabel);
    if (!labels.length) return t('eat.why.body', '지금 시간과 배고픔에 잘 맞아요.');
    return labels.join(' + ') + '\n' + t('eat.why.tail', '그 조건으로 골랐어요.');
  }

  function goHome(keepHunger) {
    if (state.spinTimer) clearTimeout(state.spinTimer);
    var hunger = keepHunger ? state.hunger : 'any';
    state = {
      view: 'home',
      hunger: hunger,
      answers: {},
      seenIds: [],
      result: null,
      idlePool: keepHunger ? state.idlePool : [],
      spinning: false,
      spinTimer: null,
      ready: state.ready
    };
    renderHome();
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
    if (act === 'spin') startSpin();
    if (act === 'back' || act === 'reset') goHome(act === 'back');
    if (act === 'more') {
      (state.result && state.result.picks || []).forEach(function (row) {
        if (state.seenIds.indexOf(row.food.id) === -1) state.seenIds.push(row.food.id);
      });
      startSpin();
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
        startSpin();
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
