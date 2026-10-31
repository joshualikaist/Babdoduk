/* 꽁밥 제보 (tip.html, lab only; docs/GGONGBAB_TIPS.md).

   A visitor writes what they saw in their own words, with up to three photos (owner 2026-11-01: "사용자는
   제보하는거고, 우리는 그거를 분류하는 사람이 되어야"), and sends it through the checking function
   ggongbab_submit_report (supabase/migrations/009_ggongbab_tip_reports.sql), which returns the tip's
   id; the photos then go to the private bucket under that id. The operations PC sorts the report into
   an event and the owner confirms it; the board lists only the confirmed tips (ggongbab_tip_board:
   title, place, date, time and food). Nothing is read back from the tips or the photos.

   The public URL and publishable key come from js/ggongbab-public-config.js, as for the public feed
   and the world cup. With an empty configuration the page makes no request: the form says tips are
   closed and the board that it cannot load. The Supabase client is the public feed's pinned build. */
(function () {
  'use strict';

  var SDK_URL = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.116.0/dist/umd/supabase.js';
  var SDK_INTEGRITY = 'sha384-iLddHTLokph6Omwoyid4XKxHaWa6w41BnoEj0q5oOrzmYPpHIKt1wyjReA7s//pP';
  var SUBMIT = 'ggongbab_submit_report';
  var BOARD = 'ggongbab_tip_board';
  var BOARD_COLUMNS = 'id,title,place,event_date,time_text,food,accepted_at';
  var BUCKET = 'ggongbab-tip-images';
  var PAST_DAYS = 14;
  var MAX_PHOTOS = 3;
  var MAX_BYTES = 5 * 1024 * 1024;
  var MAX_SIDE = 2000;
  var TYPES = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp' };
  // Characters after trimming; the function checks the same: words (at least MIN_TEXT) or a photo.
  var MIN_TEXT = 2;
  var MAX_TEXT = 1000;

  var $ = function (id) { return document.getElementById(id); };
  var form = $('tipForm');
  if (!form) return;
  var client = null, clientPromise = null, photos = [], board = { state: 'loading', rows: [] };
  var statusKey = '', statusTone = '', doneWarnKey = '', checked = false;

  function lang() { return document.documentElement.lang === 'en' ? 'en' : 'ko'; }
  function t(key, vars) {
    var table = (window.BABDODUK_STR || {})[lang()] || {};
    var text = table[key] !== undefined ? table[key] : key;
    Object.keys(vars || {}).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }

  // ---- dates (Korea time) ----------------------------------------------------------------------
  function todayKst() {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
      .format(new Date());
  }
  function addDays(iso, days) {
    var p = iso.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + days)).toISOString().slice(0, 10);
  }
  function validDate(iso) { return /^\d{4}-\d{2}-\d{2}$/.test(iso) && !isNaN(Date.parse(iso + 'T00:00:00Z')); }

  // ---- configuration and client ----------------------------------------------------------------
  function publicConfig(config) {
    try {
      var url = new URL(config.SUPABASE_URL);
      var key = config.SUPABASE_PUBLISHABLE_KEY;
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') return null;
      if (typeof key !== 'string') return null;
      if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) {
        var parts = key.split('.');
        if (parts.length !== 3 || JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))).role !== 'anon') return null;
      }
      return { url: url.origin, key: key };
    } catch (e) { return null; }
  }
  function loadSdk() {
    if (window.supabase && window.supabase.createClient) return Promise.resolve(window.supabase);
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      var timeout = setTimeout(failed, 8000);
      function failed() { clearTimeout(timeout); script.remove(); reject(new Error('client unavailable')); }
      script.src = SDK_URL;
      script.integrity = SDK_INTEGRITY;
      script.crossOrigin = 'anonymous';
      script.referrerPolicy = 'no-referrer';
      script.onload = function () {
        clearTimeout(timeout);
        if (window.supabase && window.supabase.createClient) resolve(window.supabase);
        else failed();
      };
      script.onerror = failed;
      document.head.appendChild(script);
    });
  }
  function getClient() {
    if (clientPromise) return clientPromise;
    var config = publicConfig(window.BABDODUK_PUBLIC_FEED_CONFIG || {});
    clientPromise = config ? loadSdk().then(function (sdk) {
      client = sdk.createClient(config.url, config.key, {
        auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false }
      });
      return client;
    }) : Promise.reject(new Error('no configuration'));
    return clientPromise;
  }

  // ---- status and text ---------------------------------------------------------------------------
  function setStatus(key, tone) {
    statusKey = key || ''; statusTone = tone || '';
    var el = $('tipStatus');
    el.textContent = statusKey ? t(statusKey) : '';
    if (statusTone) el.setAttribute('data-tone', statusTone); else el.removeAttribute('data-tone');
  }
  function placeholders() {
    document.querySelectorAll('[data-tip-ph]').forEach(function (el) {
      el.setAttribute('placeholder', t(el.getAttribute('data-tip-ph')));
    });
  }
  function counter() {
    var value = $('tipTextInput').value, el = $('tipTextCount');
    el.textContent = t('tip.f.count', { n: value.trim().length, max: MAX_TEXT });
    el.setAttribute('data-over', String(value.trim().length > MAX_TEXT));
  }

  // ---- validation --------------------------------------------------------------------------------
  function showError(input, error, key) {
    var el = $(error);
    el.textContent = key ? t(key) : '';
    el.hidden = !key;
    el.setAttribute('data-key', key || '');
    if (input) {
      if (key) $(input).setAttribute('aria-invalid', 'true'); else $(input).removeAttribute('aria-invalid');
    }
  }
  function values() {
    return { text: $('tipTextInput').value.trim(), hp: $('tipHp').value };
  }
  // The id of the field to fix, or null.
  function validate(v) {
    var n = v.text.length;
    var key = n > MAX_TEXT ? 'tip.err.text' : n < MIN_TEXT && !photos.length ? 'tip.err.empty' : '';
    showError('tipTextInput', 'tipTextError', key);
    return key ? 'tipTextInput' : null;
  }

  // ---- photos --------------------------------------------------------------------------------------
  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file), img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('unreadable')); };
      img.src = url;
    });
  }
  // A large photo is scaled down to 2000px on its long side as a JPEG; a small one is sent as it is.
  function prepare(file) {
    if (!TYPES[file.type]) return Promise.reject(new Error('tip.err.photoType'));
    return loadImage(file).then(function (img) {
      var w = img.naturalWidth, h = img.naturalHeight, side = Math.max(w, h);
      if (side <= MAX_SIDE && file.size <= MAX_BYTES) return { blob: file, type: file.type };
      var scale = Math.min(1, MAX_SIDE / side), canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (blob) {
          if (!blob || blob.size > MAX_BYTES) reject(new Error('tip.err.photoSize'));
          else resolve({ blob: blob, type: 'image/jpeg' });
        }, 'image/jpeg', 0.85);
      });
    }, function () {
      if (file.size > MAX_BYTES) throw new Error('tip.err.photoSize');
      throw new Error('tip.err.photoType');
    });
  }
  function renderPhotos() {
    var list = $('tipPreviews');
    list.textContent = '';
    photos.forEach(function (photo, index) {
      var item = document.createElement('li');
      item.className = 'tip-preview';
      var img = document.createElement('img');
      img.src = photo.url;
      img.alt = t('tip.f.photoAlt', { n: index + 1 });
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'tip-preview-remove';
      remove.setAttribute('aria-label', t('tip.f.photoRemove', { n: index + 1 }));
      remove.setAttribute('data-photo', String(index));
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        URL.revokeObjectURL(photo.url);
        photos.splice(index, 1);
        renderPhotos();
        var next = list.querySelector('.tip-preview-remove') || $('tipPhotos');
        next.focus();
      });
      item.appendChild(img);
      item.appendChild(remove);
      list.appendChild(item);
    });
    list.hidden = !photos.length;
    var full = photos.length >= MAX_PHOTOS;
    $('tipDrop').setAttribute('data-full', String(full));
    $('tipPhotos').disabled = full || $('tipFieldset').disabled;
  }
  function addPhotos(files) {
    showError(null, 'tipPhotosError', '');
    var room = MAX_PHOTOS - photos.length, chosen = Array.prototype.slice.call(files || []);
    if (!chosen.length) return Promise.resolve();
    if (chosen.length > room) showError(null, 'tipPhotosError', 'tip.err.photoMax');
    return chosen.slice(0, Math.max(room, 0)).reduce(function (chain, file) {
      return chain.then(function () {
        return prepare(file).then(function (ready) {
          if (photos.length >= MAX_PHOTOS) return;
          photos.push({ blob: ready.blob, type: ready.type, url: URL.createObjectURL(ready.blob) });
        }, function (err) { showError(null, 'tipPhotosError', err.message); });
      });
    }, Promise.resolve()).then(renderPhotos);
  }
  function uploadPhotos(id) {
    var failed = 0;
    return photos.reduce(function (chain, photo, index) {
      return chain.then(function () {
        var path = id + '/' + (index + 1) + '.' + TYPES[photo.type];
        return client.storage.from(BUCKET).upload(path, photo.blob, { contentType: photo.type, upsert: false, cacheControl: '0' })
          .then(function (res) { if (!res || res.error) failed++; }, function () { failed++; });
      });
    }, Promise.resolve()).then(function () { return failed; });
  }

  // ---- sending -------------------------------------------------------------------------------------
  function busy(on) {
    var button = $('tipSubmit');
    button.disabled = on;
    button.setAttribute('aria-busy', String(on));
    button.textContent = t(on ? 'tip.sending' : 'tip.submit');
  }
  function errorKey(error) {
    var text = String((error && (error.message || error.details || error.hint)) || '');
    if (text.indexOf('TIP_RATE_LIMITED') !== -1) return 'tip.status.rate';
    if (text.indexOf('TIP_INVALID') !== -1) return 'tip.status.invalid';
    return 'tip.status.failed';
  }
  function showDone(failedPhotos, total, words) {
    form.hidden = true;
    doneWarnKey = !failedPhotos ? '' : failedPhotos < total ? 'tip.done.somePhotosFailed'
      : words ? 'tip.done.photosFailed' : 'tip.done.emptyFailed';
    $('tipDoneWarn').textContent = doneWarnKey ? t(doneWarnKey) : '';
    $('tipDoneWarn').hidden = !doneWarnKey;
    $('tipDone').hidden = false;
    setStatus('', '');
    $('tipDoneTitle').focus();
  }
  function reset() {
    form.reset();
    photos.forEach(function (photo) { URL.revokeObjectURL(photo.url); });
    photos = [];
    renderPhotos();
    showError('tipTextInput', 'tipTextError', '');
    showError(null, 'tipPhotosError', '');
    counter();
    doneWarnKey = '';
    checked = false;
    $('tipDone').hidden = true;
    form.hidden = false;
    setStatus('', '');
    $('tipTextInput').focus();
  }
  function submit(event) {
    event.preventDefault();
    if ($('tipSubmit').disabled) return;
    var v = values(), first = validate(v);
    checked = true;
    if (first) {
      setStatus('tip.status.invalid', 'error');
      $(first).focus();
      return;
    }
    busy(true);
    setStatus('tip.status.sending', 'info');
    getClient().then(function (c) {
      return c.rpc(SUBMIT, { p_text: v.text, p_photos: photos.length, p_hp: v.hp });
    }).then(function (res) {
      if (!res || res.error || typeof res.data !== 'string') {
        busy(false);
        setStatus(errorKey(res && res.error), 'error');
        return;
      }
      var total = photos.length;
      return (total ? uploadPhotos(res.data) : Promise.resolve(0)).then(function (failed) {
        busy(false);
        showDone(failed, total, v.text.length >= MIN_TEXT);
      });
    }).catch(function () {
      busy(false);
      setStatus(client ? 'tip.status.failed' : 'tip.status.off', 'error');
    });
  }

  // ---- board ---------------------------------------------------------------------------------------
  function dateParts(iso) {
    var p = iso.split('-').map(Number), when = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
    var locale = lang() === 'en' ? 'en-US' : 'ko-KR';
    return {
      month: lang() === 'en' ? new Intl.DateTimeFormat('en-US', { month: 'short', timeZone: 'UTC' }).format(when).toUpperCase()
                             : p[1] + '월',
      day: String(p[2]),
      week: new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(when)
    };
  }
  function fact(list, icon, labelKey, value) {
    if (!value) return;
    var row = document.createElement('div');
    var dt = document.createElement('dt');
    var mark = document.createElement('span');
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = icon;
    var name = document.createElement('span');
    name.className = 'tip-sr';
    name.textContent = t(labelKey);
    dt.appendChild(mark);
    dt.appendChild(name);
    var dd = document.createElement('dd');
    dd.textContent = value;
    row.appendChild(dt);
    row.appendChild(dd);
    list.appendChild(row);
  }
  function item(row, today) {
    var li = document.createElement('li');
    li.className = 'tip-item' + (row.event_date === today ? ' is-today' : '');
    var parts = dateParts(row.event_date);
    var stamp = document.createElement('time');
    stamp.className = 'tip-date';
    stamp.setAttribute('datetime', row.event_date);
    [['tip-date-month', parts.month], ['tip-date-day', parts.day], ['tip-date-week', parts.week]].forEach(function (pair) {
      var span = document.createElement('span');
      span.className = pair[0];
      span.textContent = pair[1];
      stamp.appendChild(span);
    });
    var body = document.createElement('div');
    body.className = 'tip-item-body';
    var title = document.createElement('h3');
    title.className = 'tip-item-title';
    if (row.event_date === today) {
      var badge = document.createElement('span');
      badge.className = 'tip-today';
      badge.textContent = t('tip.board.today');
      title.appendChild(badge);
    }
    title.appendChild(document.createTextNode(row.title));
    var facts = document.createElement('dl');
    facts.className = 'tip-facts';
    fact(facts, '📍', 'tip.board.place', row.place);
    fact(facts, '🕒', 'tip.board.time', row.time_text);
    fact(facts, '🍙', 'tip.board.food', row.food);
    body.appendChild(title);
    body.appendChild(facts);
    li.appendChild(stamp);
    li.appendChild(body);
    return li;
  }
  function group(name, titleKey, rows, today) {
    var section = document.createElement('div');
    section.className = 'tip-group tip-group--' + name;
    var title = document.createElement('h3');
    title.className = 'tip-group-title';
    title.textContent = t(titleKey);
    var list = document.createElement('ul');
    list.className = 'tip-list';
    rows.forEach(function (row) { list.appendChild(item(row, today)); });
    section.appendChild(title);
    section.appendChild(list);
    return section;
  }
  function state(key) {
    var p = document.createElement('p');
    p.className = 'tip-board-state';
    p.textContent = t(key);
    return p;
  }
  function renderBoard() {
    var root = $('tipBoard');
    root.textContent = '';
    root.setAttribute('data-state', board.state);
    if (board.state !== 'ready') {
      root.appendChild(state(board.state === 'loading' ? 'tip.board.loading' : 'tip.board.off'));
      return;
    }
    var today = todayKst(), from = addDays(today, -PAST_DAYS);
    var rows = board.rows.filter(function (row) {
      return row && typeof row.title === 'string' && typeof row.place === 'string'
        && validDate(String(row.event_date)) && row.event_date >= from;
    });
    var upcoming = rows.filter(function (row) { return row.event_date >= today; })
      .sort(function (a, b) { return a.event_date < b.event_date ? -1 : a.event_date > b.event_date ? 1 : 0; });
    var past = rows.filter(function (row) { return row.event_date < today; })
      .sort(function (a, b) { return a.event_date < b.event_date ? 1 : a.event_date > b.event_date ? -1 : 0; });
    if (!upcoming.length && !past.length) {
      root.setAttribute('data-state', 'empty');
      root.appendChild(state('tip.board.empty'));
      return;
    }
    if (upcoming.length) root.appendChild(group('upcoming', 'tip.board.upcoming', upcoming, today));
    if (past.length) root.appendChild(group('past', 'tip.board.past', past, today));
  }
  function loadBoard() {
    var from = addDays(todayKst(), -PAST_DAYS);
    getClient().then(function (c) {
      return c.from(BOARD).select(BOARD_COLUMNS).gte('event_date', from).order('event_date', { ascending: true }).limit(100);
    }).then(function (res) {
      if (!res || res.error || !Array.isArray(res.data)) throw new Error('unavailable');
      board = { state: 'ready', rows: res.data };
    }).catch(function () {
      board = { state: 'off', rows: [] };
    }).then(renderBoard);
  }

  // ---- start ---------------------------------------------------------------------------------------
  function closed() {
    $('tipFieldset').disabled = true;
    renderPhotos();
    setStatus('tip.status.off', 'error');
  }
  function relabel() {
    placeholders();
    counter();
    if (statusKey) setStatus(statusKey, statusTone);
    if (doneWarnKey) $('tipDoneWarn').textContent = t(doneWarnKey);
    if (!$('tipSubmit').disabled) $('tipSubmit').textContent = t('tip.submit');
    ['tipTextError', 'tipPhotosError'].forEach(function (id) {
      var key = $(id).getAttribute('data-key');
      if (key) $(id).textContent = t(key);
    });
    renderPhotos();
    renderBoard();
  }

  placeholders();
  counter();
  form.addEventListener('submit', submit);
  // After a first try, each correction (words or a photo) updates the mark at once.
  function recheck() {
    if (!checked) return;
    if (!validate(values()) && statusKey === 'tip.status.invalid') setStatus('', '');
  }
  form.addEventListener('input', recheck);
  $('tipAgain').addEventListener('click', reset);
  $('tipTextInput').addEventListener('input', counter);
  $('tipPhotos').addEventListener('change', function (event) {
    var input = event.target;
    addPhotos(input.files).then(function () { input.value = ''; recheck(); });
  });
  var drop = $('tipDrop');
  ['dragenter', 'dragover'].forEach(function (name) {
    drop.addEventListener(name, function () { drop.classList.add('is-over'); });
  });
  ['dragleave', 'drop'].forEach(function (name) {
    drop.addEventListener(name, function () { drop.classList.remove('is-over'); });
  });
  document.addEventListener('babdoduk-lang', relabel);

  if (!publicConfig(window.BABDODUK_PUBLIC_FEED_CONFIG || {})) {
    closed();
    board = { state: 'off', rows: [] };
    renderBoard();
    return;
  }
  getClient().catch(closed);
  loadBoard();
}());
