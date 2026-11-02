/* 꽁밥 카드뉴스 (cardnews.html, lab only; docs/CARDNEWS.md).

   Shows the newest week of data/cardnews/index.json, written by scripts/render_cardnews.py: a cover
   and one card per weekday, the same images that go to Telegram and Instagram. Each card opens at
   full size. The cards themselves are Korean; the page around them follows the language switch. */
(function () {
  'use strict';

  var INDEX = 'data/cardnews/index.json';
  var grid = document.getElementById('cnGrid');
  if (!grid) return;
  var meta = document.getElementById('cnMeta');
  var week = null, state = 'loading';

  function lang() { return document.documentElement.lang === 'en' ? 'en' : 'ko'; }
  function t(key, vars) {
    var table = (window.BABDODUK_STR || {})[lang()] || {};
    var text = table[key] !== undefined ? table[key] : key;
    Object.keys(vars || {}).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function day(iso, offset) {
    var p = iso.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + (offset || 0)));
  }
  function format(when, options) {
    return new Intl.DateTimeFormat(lang() === 'en' ? 'en-US' : 'ko-KR', Object.assign({ timeZone: 'UTC' }, options)).format(when);
  }
  function range(iso) {
    var opts = { month: 'short', day: 'numeric', weekday: 'short' };
    return format(day(iso), opts) + ' – ' + format(day(iso, 4), opts);
  }
  function stamp(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) return '';
    return new Intl.DateTimeFormat(lang() === 'en' ? 'en-US' : 'ko-KR', {
      timeZone: 'Asia/Seoul', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false
    }).format(when);
  }
  function valid(item) {
    return item && /^\d{4}-\d{2}-\d{2}$/.test(item.week) && Array.isArray(item.images) && item.images.length === 6
      && Array.isArray(item.counts) && item.counts.length === 5
      && item.images.every(function (src) { return /^data\/cardnews\/\d{4}-\d{2}-\d{2}\/[1-6]\.png$/.test(src); });
  }

  function figure(src, number, caption, alt) {
    var fig = document.createElement('figure');
    fig.className = 'cn-card';
    var link = document.createElement('a');
    link.href = src;
    link.target = '_blank';
    link.rel = 'noopener';
    // The link carries the card's description; the image inside it adds nothing of its own.
    link.setAttribute('aria-label', t('cardnews.open', { label: alt }));
    var img = document.createElement('img');
    img.src = src;
    img.alt = '';
    img.width = 1080;
    img.height = 1350;
    img.loading = number > 3 ? 'lazy' : 'eager';
    link.appendChild(img);
    var cap = document.createElement('figcaption');
    var num = document.createElement('b');
    num.textContent = String(number);
    cap.appendChild(num);
    cap.appendChild(document.createTextNode(caption));
    fig.appendChild(link);
    fig.appendChild(cap);
    return fig;
  }

  function render() {
    grid.textContent = '';
    grid.setAttribute('data-state', state);
    meta.textContent = '';
    if (state !== 'ready') {
      var p = document.createElement('p');
      p.className = 'cn-state';
      p.textContent = t(state === 'loading' ? 'cardnews.loading' : state === 'empty' ? 'cardnews.empty' : 'cardnews.off');
      grid.appendChild(p);
      return;
    }
    meta.textContent = t('cardnews.meta', { range: range(week.week), total: week.total, updated: stamp(week.feedGeneratedAt) });
    grid.appendChild(figure(week.images[0], 1, t('cardnews.cap.cover'),
      t('cardnews.alt.cover', { range: range(week.week), total: week.total })));
    for (var i = 0; i < 5; i++) {
      var name = t('cardnews.day.' + i);
      var date = format(day(week.week, i), { month: 'short', day: 'numeric' });
      grid.appendChild(figure(week.images[i + 1], i + 2, name,
        t(week.counts[i] ? 'cardnews.alt.day' : 'cardnews.alt.none', { day: name, date: date, n: week.counts[i] })));
    }
  }

  document.addEventListener('babdoduk-lang', render);
  fetch(INDEX, { cache: 'no-cache' }).then(function (res) {
    if (!res.ok) throw new Error('unavailable');
    return res.json();
  }).then(function (data) {
    var weeks = (data && Array.isArray(data.weeks) ? data.weeks : []).filter(valid);
    week = weeks[0] || null;
    state = week ? 'ready' : 'empty';
  }).catch(function () {
    state = 'off';
  }).then(render);
  render();
}());
