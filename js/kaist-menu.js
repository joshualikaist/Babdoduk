(function () {
  var root = document.getElementById('kaistToday');
  if (!root) return;

  var state = { data: null, resto: '', meal: 'lunch' };

  function t(key, fallback) {
    var lang = window.babdodukGetLang ? window.babdodukGetLang() : 'ko';
    var pack = window.BABDODUK_STR && window.BABDODUK_STR[lang];
    if (pack && pack[key] != null) return pack[key];
    return fallback || key;
  }

  function mealNow() {
    var h = new Date().getHours();
    if (h < 10) return 'breakfast';
    if (h < 16) return 'lunch';
    return 'dinner';
  }

  function findResto() {
    var list = (state.data && state.data.restaurants) || [];
    return list.filter(function (row) { return row.id === state.resto; })[0] || list[0];
  }

  function render() {
    if (!state.data) {
      root.innerHTML = '<p class="kaist-empty">' + t('kaist.empty', '오늘 학식 정보를 아직 못 읽었어요.') + '</p>';
      return;
    }
    var restos = state.data.restaurants || [];
    if (!restos.length) {
      root.innerHTML = '<p class="kaist-empty">' + t('kaist.empty', '오늘 학식 정보를 아직 못 읽었어요.') + '</p>';
      return;
    }
    if (!state.resto) state.resto = restos[0].id;
    var resto = findResto();
    var meal = (resto && resto[state.meal]) || {};
    var html = '<header class="kaist-head"><h2 id="kaistTitle">' + t('kaist.title', '오늘 KAIST에서 뭐 먹지?') + '</h2>';
    html += '<p class="kaist-date">' + (state.data.dateLabel || state.data.date || '') + '</p></header>';
    html += '<div class="kaist-restos" role="tablist">';
    restos.forEach(function (row) {
      html += '<button type="button" class="kaist-resto' + (row.id === state.resto ? ' is-on' : '') + '" data-kaist-resto="' + row.id + '">' + (row.name || row.id) + '</button>';
    });
    html += '</div><div class="kaist-meals">';
    ['breakfast', 'lunch', 'dinner'].forEach(function (key) {
      html += '<button type="button" class="kaist-meal' + (state.meal === key ? ' is-on' : '') + '" data-kaist-meal="' + key + '">' + t('kaist.' + key, key) + '</button>';
    });
    html += '</div>';
    var items = meal.items || [];
    if (!items.length) {
      html += '<p class="kaist-empty">' + t('kaist.nomenu', '이 시간대 메뉴가 없어요.') + '</p>';
    } else {
      html += '<div class="kaist-card"><ul>';
      items.slice(0, 10).forEach(function (item) {
        html += '<li>' + String(item).replace(/[&<>]/g, function (ch) {
          return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[ch];
        }) + '</li>';
      });
      html += '</ul><p class="kaist-meta">';
      if (meal.price) html += meal.price + ' · ';
      if (meal.kcal) html += meal.kcal;
      html += '</p></div>';
    }
    html += '<a class="kaist-to-slot" href="#what">' + t('kaist.toSlot', '오늘 학식이 당기지 않는다면') + '</a>';
    root.innerHTML = html;
  }

  root.addEventListener('click', function (e) {
    var resto = e.target.closest && e.target.closest('[data-kaist-resto]');
    var meal = e.target.closest && e.target.closest('[data-kaist-meal]');
    if (resto) {
      state.resto = resto.getAttribute('data-kaist-resto');
      render();
    }
    if (meal) {
      state.meal = meal.getAttribute('data-kaist-meal');
      render();
    }
  });

  state.meal = mealNow();
  fetch('data/kaist-menu/latest.json', { cache: 'no-store' }).then(function (res) {
    if (!res.ok) throw new Error('missing');
    return res.json();
  }).then(function (data) {
    state.data = data;
    render();
  }).catch(function () {
    state.data = null;
    render();
  });
})();
