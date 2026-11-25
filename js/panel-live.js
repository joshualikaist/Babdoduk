(function () {
  'use strict';

  var root = document.getElementById('pnLive');
  if (!root) return;
  var LOCAL = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  var KINDS = { step: 1, say: 1, finding: 1, comment: 1, start: 1, done: 1 };
  var SPEEDS = [1, 10, 60];
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var data = null, live = false, speed = 10, clock = 0, playing = false, shown = 0, timer = null, last = 0;
  var panes = {}, phaseLine = null, clockLine = null, playBtn = null;

  function lang() { return document.documentElement.lang === 'en' ? 'en' : 'ko'; }
  function t(key, vars) {
    var table = (window.BABDODUK_STR || {})[lang()] || {};
    var text = table[key] !== undefined ? table[key] : key;
    Object.keys(vars || {}).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = String(text);
    return node;
  }
  function valid(d) {
    return d && Array.isArray(d.panes) && Array.isArray(d.events) && d.panes.length <= 12
      && d.panes.every(function (p) { return p && /^[a-z0-9]+$/.test(p.id) && typeof p.name === 'string'; })
      && d.events.every(function (e) { return e && typeof e.t === 'number' && typeof e.pane === 'string' && typeof e.text === 'string'; });
  }
  function minutes(s) {
    s = Math.max(0, Math.round(s));
    return t('panel.live.clock', { m: Math.floor(s / 60), s: s % 60 });
  }

  function button(label, onClick, pressed) {
    var b = el('button', 'pn-chip', label);
    b.type = 'button';
    if (pressed != null) b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    b.addEventListener('click', onClick);
    return b;
  }

  function build() {
    root.textContent = '';
    root.hidden = false;
    var head = el('div', 'pn-live-head');
    var h = el('h2', 'page-section-title', t('panel.live.title'));
    h.id = 'pnLiveTitle';
    head.appendChild(h);
    head.appendChild(el('span', 'pn-live-badge' + (live ? ' pn-live-badge--on' : ''), t(live ? 'panel.live.on' : 'panel.live.replay')));
    root.appendChild(head);
    root.appendChild(el('p', 'pn-live-lead', t(live ? 'panel.live.leadLive' : 'panel.live.leadReplay')));
    var bar = el('div', 'pn-live-bar');
    phaseLine = el('p', 'pn-live-phase');
    phaseLine.setAttribute('role', 'status');
    bar.appendChild(phaseLine);
    clockLine = el('p', 'pn-live-clock');
    bar.appendChild(clockLine);
    if (!live) {
      var controls = el('div', 'pn-filter-row');
      controls.setAttribute('role', 'group');
      controls.setAttribute('aria-label', t('panel.live.controls'));
      playBtn = button('', function () { playing ? pause() : play(); });
      controls.appendChild(playBtn);
      controls.appendChild(button(t('panel.live.restart'), function () { reset(); play(); }));
      SPEEDS.forEach(function (n) {
        var b = button(t('panel.live.speed', { n: n }), function () {
          speed = n;
          controls.querySelectorAll('[data-speed]').forEach(function (x) {
            x.setAttribute('aria-pressed', x.getAttribute('data-speed') === String(n) ? 'true' : 'false');
          });
        }, speed === n);
        b.setAttribute('data-speed', String(n));
        controls.appendChild(b);
      });
      controls.appendChild(button(t('panel.live.end'), function () { pause(); seek(data.end); }));
      bar.appendChild(controls);
    }
    root.appendChild(bar);
    var grid = el('div', 'pn-term-grid');
    panes = {};
    data.panes.forEach(function (p) {
      var box = el('section', 'pn-term pn-term--' + p.id);
      box.setAttribute('aria-label', p.name);
      var top = el('div', 'pn-term-top');
      var face = el('span', 'pn-term-face', p.emoji || '');
      face.setAttribute('aria-hidden', 'true');
      top.appendChild(face);
      top.appendChild(el('b', 'pn-term-name', p.name));
      var status = el('span', 'pn-term-status', t('panel.live.wait'));
      status.setAttribute('data-status', 'wait');
      top.appendChild(status);
      box.appendChild(top);
      var body = el('ol', 'pn-term-body');
      body.tabIndex = 0;
      body.setAttribute('aria-label', t('panel.live.log', { name: p.name }));
      box.appendChild(body);
      grid.appendChild(box);
      panes[p.id] = { body: body, status: status, stick: true };
      body.addEventListener('scroll', function () {
        panes[p.id].stick = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
      });
    });
    root.appendChild(grid);
  }

  function setStatus(pane, status) {
    pane.status.setAttribute('data-status', status);
    pane.status.textContent = t('panel.live.' + status);
  }

  function append(e) {
    var pane = panes[e.pane];
    if (!pane) return;
    var kind = KINDS[e.kind] ? e.kind : 'step';
    if (kind === 'start') {
      pane.body.appendChild(el('li', 'pn-line pn-line--start', '── ' + e.text.slice(0, 40) + ' ──'));
      setStatus(pane, 'work');
    } else if (kind === 'done') {
      pane.body.appendChild(el('li', 'pn-line pn-line--done', t('panel.live.doneLine')));
      setStatus(pane, 'done');
    } else {
      pane.body.appendChild(el('li', 'pn-line pn-line--' + kind, e.text.slice(0, 600)));
    }
  }

  function scroll() {
    Object.keys(panes).forEach(function (id) {
      var p = panes[id];
      if (p.stick) p.body.scrollTop = p.body.scrollHeight;
    });
  }

  function phaseAt(time) {
    var name = '';
    (data.phases || []).forEach(function (p) { if (p.t <= time) name = p.title; });
    return name;
  }

  function paint() {
    while (shown < data.events.length && data.events[shown].t <= clock) append(data.events[shown++]);
    scroll();
    var name = phaseAt(clock);
    var text = name ? t('panel.live.phase', { name: name }) : t('panel.live.ready');
    if (!live && shown >= data.events.length) text = t('panel.live.finished');
    if (phaseLine.textContent !== text) phaseLine.textContent = text;
    clockLine.textContent = live ? minutes(data.end) : minutes(clock) + ' / ' + minutes(data.end);
    if (playBtn) playBtn.textContent = t(playing ? 'panel.live.pause' : 'panel.live.play');
  }

  function reset() {
    Object.keys(panes).forEach(function (id) {
      panes[id].body.textContent = '';
      panes[id].stick = true;
      setStatus(panes[id], 'wait');
    });
    shown = 0;
    clock = 0;
  }
  function seek(time) {
    clock = Math.min(time, data.end);
    paint();
  }
  function tick(now) {
    if (!playing) return;
    clock += Math.min(1, (now - last) / 1000) * speed;
    last = now;
    if (clock >= data.end) { clock = data.end; playing = false; }
    paint();
    if (playing) timer = requestAnimationFrame(tick);
  }
  function play() {
    if (shown >= data.events.length) reset();
    playing = true;
    last = performance.now();
    cancelAnimationFrame(timer);
    timer = requestAnimationFrame(tick);
    paint();
  }
  function pause() {
    playing = false;
    cancelAnimationFrame(timer);
    paint();
  }

  function poll() {
    fetch('data/panel/live.json', { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('off');
      return res.json();
    }).then(function (next) {
      if (!valid(next)) return;
      if (next.run !== data.run) { data = next; build(); reset(); }
      data = next;
      clock = data.end;
      paint();
      Object.keys(next.state || {}).forEach(function (id) {
        if (panes[id] && next.state[id] === 'working') setStatus(panes[id], 'work');
      });
    }).catch(function () {}).then(function () { setTimeout(poll, 2000); });
  }

  function start(d, isLive) {
    data = d;
    live = isLive;
    root.setAttribute('data-mode', live ? 'live' : 'replay');
    build();
    reset();
    if (live) { clock = data.end; paint(); setTimeout(poll, 2000); }
    else if (reduce) seek(data.end);
    else play();
  }

  function load(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (res) {
      if (!res.ok) throw new Error('unavailable');
      return res.json();
    }).then(function (d) {
      if (!valid(d)) throw new Error('invalid');
      return d;
    });
  }

  document.addEventListener('babdoduk-lang', function () {
    if (!data) return;
    var at = clock, wasPlaying = playing;
    pause();
    build();
    reset();
    seek(at);
    if (wasPlaying) play();
  });
  (LOCAL ? load('data/panel/live.json').then(function (d) { return [d, true]; }) : Promise.reject())
    .catch(function () { return load('data/panel/timeline.json').then(function (d) { return [d, false]; }); })
    .then(function (pair) { start(pair[0], pair[1]); })
    .catch(function () { root.hidden = true; });
}());
