(function () {
  'use strict';

  var DATA = 'data/panel/latest.json';
  var root = document.getElementById('pnApp');
  if (!root) return;
  var report = null, state = 'loading';
  var filter = { member: '', verdict: 'accept' };
  var VERDICTS = ['accept', 'question', 'reject', 'all'];
  var KINDS = { finding: 1, question: 1, reply: 1, comment: 1, verdict: 1, note: 1 };

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
  function stamp(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) return '';
    return new Intl.DateTimeFormat(lang() === 'en' ? 'en-US' : 'ko-KR', {
      timeZone: 'Asia/Seoul', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false
    }).format(when);
  }
  function str(value, max) { return typeof value === 'string' ? value.slice(0, max || 2000) : ''; }
  function shotOk(src) { return typeof src === 'string' && /^data\/panel\/shots\/[a-z0-9-]+\.(webp|jpg)$/.test(src); }

  function valid(data) {
    return data && data.run && Array.isArray(data.members) && Array.isArray(data.threads)
      && data.members.every(function (m) { return m && /^[a-z]+$/.test(m.id) && typeof m.name === 'string'; })
      && data.threads.every(function (th) { return th && typeof th.id === 'string' && Array.isArray(th.messages); });
  }

  function member(id) {
    for (var i = 0; i < report.members.length; i++) if (report.members[i].id === id) return report.members[i];
    return { id: id, name: id, emoji: '' };
  }

  function severity(n) {
    var level = Math.max(0, Math.min(4, Number(n) || 0));
    var badge = el('span', 'pn-sev pn-sev--' + level, t('panel.sev.' + level));
    badge.setAttribute('data-level', String(level));
    return badge;
  }
  function verdictBadge(v) {
    return el('span', 'pn-verdict pn-verdict--' + v, t('panel.verdict.' + v));
  }

  function chip(label, pressed, onClick) {
    var b = el('button', 'pn-chip', label);
    b.type = 'button';
    b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    b.addEventListener('click', onClick);
    return b;
  }

  function header() {
    var box = el('section', 'pn-head');
    box.setAttribute('aria-labelledby', 'pnTitle');
    var counts = { accept: 0, question: 0, reject: 0 };
    report.threads.forEach(function (th) { if (counts[th.verdict] !== undefined) counts[th.verdict] += 1; });
    box.appendChild(el('p', 'pn-meta', t('panel.meta', {
      at: stamp(report.run.at), pages: report.run.pages || 0, views: report.run.views || 0,
      total: report.threads.length, accept: counts.accept, reject: counts.reject
    })));
    if (report.overall) box.appendChild(el('p', 'pn-overall', str(report.overall, 600)));
    return box;
  }

  function members() {
    var wrap = el('section', 'pn-members');
    wrap.setAttribute('aria-labelledby', 'pnMembersTitle');
    var h = el('h2', 'page-section-title', t('panel.members'));
    h.id = 'pnMembersTitle';
    wrap.appendChild(h);
    var list = el('ul', 'pn-member-list');
    report.members.forEach(function (m) {
      var li = el('li', 'pn-member');
      var face = el('span', 'pn-face', m.emoji || '');
      face.setAttribute('aria-hidden', 'true');
      li.appendChild(face);
      var body = el('div', 'pn-member-body');
      body.appendChild(el('b', null, m.name));
      if (m.role) body.appendChild(el('span', null, str(m.role, 120)));
      if (report.summary && report.summary[m.id]) body.appendChild(el('p', 'pn-member-say', str(report.summary[m.id], 400)));
      li.appendChild(body);
      list.appendChild(li);
    });
    wrap.appendChild(list);
    return wrap;
  }

  function top() {
    var ids = Array.isArray(report.top) ? report.top : [];
    var byId = {};
    report.threads.forEach(function (th) { byId[th.id] = th; });
    var picked = ids.map(function (id) { return byId[id]; }).filter(Boolean).slice(0, 10);
    var wrap = el('section', 'pn-top');
    wrap.setAttribute('aria-labelledby', 'pnTopTitle');
    var h = el('h2', 'page-section-title', t('panel.top'));
    h.id = 'pnTopTitle';
    wrap.appendChild(h);
    if (!picked.length) { wrap.appendChild(el('p', 'pn-state', t('panel.topEmpty'))); return wrap; }
    var list = el('ol', 'pn-top-list');
    picked.forEach(function (th) {
      var li = el('li', 'pn-top-item');
      var row = el('div', 'pn-top-row');
      row.appendChild(severity(th.severity));
      var link = el('a', 'pn-top-link', str(th.title, 200));
      link.href = '#' + th.id;
      link.addEventListener('click', function () {
        var target = document.getElementById(th.id);
        if (target && target.tagName === 'DETAILS') target.open = true;
      });
      row.appendChild(link);
      li.appendChild(row);
      var by = (th.by || []).map(function (id) { return member(id).name; }).join(', ');
      if (by) li.appendChild(el('p', 'pn-by', t('panel.by', { names: by })));
      if (th.decision) li.appendChild(el('p', 'pn-fix', t('panel.decision', { text: str(th.decision, 500) })));
      else if (th.fix) li.appendChild(el('p', 'pn-fix', t('panel.fix', { fix: str(th.fix, 400) })));
      list.appendChild(li);
    });
    wrap.appendChild(list);
    return wrap;
  }

  function filters() {
    var bar = el('div', 'pn-filters');
    var who = el('div', 'pn-filter-row');
    who.setAttribute('role', 'group');
    who.setAttribute('aria-label', t('panel.filterWho'));
    who.appendChild(chip(t('panel.everyone'), !filter.member, function () { filter.member = ''; render(); focusChip('m-'); }));
    report.members.forEach(function (m) {
      var c = chip((m.emoji ? m.emoji + ' ' : '') + m.name, filter.member === m.id, function () {
        filter.member = m.id; render(); focusChip('m-' + m.id);
      });
      c.setAttribute('data-key', 'm-' + m.id);
      who.appendChild(c);
    });
    who.firstChild.setAttribute('data-key', 'm-');
    var what = el('div', 'pn-filter-row');
    what.setAttribute('role', 'group');
    what.setAttribute('aria-label', t('panel.filterVerdict'));
    VERDICTS.forEach(function (v) {
      var c = chip(t('panel.show.' + v), filter.verdict === v, function () { filter.verdict = v; render(); focusChip('v-' + v); });
      c.setAttribute('data-key', 'v-' + v);
      what.appendChild(c);
    });
    bar.appendChild(who);
    bar.appendChild(what);
    return bar;
  }
  function focusChip(key) {
    var c = root.querySelector('.pn-chip[data-key="' + key + '"]');
    if (c) c.focus();
  }

  function bubble(msg) {
    var m = member(msg.from);
    var kind = KINDS[msg.kind] ? msg.kind : 'note';
    var li = el('li', 'pn-msg pn-msg--' + kind + (msg.from === 'critic' ? ' pn-msg--critic' : ''));
    var face = el('span', 'pn-face', m.emoji || '');
    face.setAttribute('aria-hidden', 'true');
    li.appendChild(face);
    var body = el('div', 'pn-bubble');
    var who = el('p', 'pn-who');
    who.appendChild(el('b', null, m.name));
    who.appendChild(el('span', 'pn-kind', t('panel.kind.' + kind)));
    body.appendChild(who);
    str(msg.text, 3000).split(/\n{2,}/).forEach(function (para) { body.appendChild(el('p', 'pn-text', para)); });
    li.appendChild(body);
    return li;
  }

  function thread(th) {
    var box = el('details', 'pn-thread');
    box.id = th.id;
    var sum = el('summary', 'pn-thread-head');
    sum.appendChild(severity(th.severity));
    sum.appendChild(verdictBadge(th.verdict));
    sum.appendChild(el('span', 'pn-thread-title', str(th.title, 200)));
    box.appendChild(sum);
    var where = [th.page, th.device ? t('panel.device.' + th.device) : ''].filter(Boolean).join(' · ');
    if (where) box.appendChild(el('p', 'pn-where', where));
    var list = el('ol', 'pn-chat');
    th.messages.forEach(function (msg) { list.appendChild(bubble(msg)); });
    box.appendChild(list);
    if (shotOk(th.shot)) {
      var a = el('a', 'pn-shot');
      a.href = th.shot;
      a.target = '_blank';
      a.rel = 'noopener';
      a.setAttribute('aria-label', t('panel.shot', { page: th.page || '' }));
      var img = el('img');
      img.src = th.shot;
      img.alt = '';
      img.loading = 'lazy';
      img.width = 240;
      a.appendChild(img);
      box.appendChild(a);
    }
    if (th.ask) box.appendChild(el('p', 'pn-ask', t('panel.ask', { q: str(th.ask, 300) })));
    return box;
  }

  function threads() {
    var wrap = el('section', 'pn-threads');
    wrap.setAttribute('aria-labelledby', 'pnThreadsTitle');
    var h = el('h2', 'page-section-title', t('panel.threads'));
    h.id = 'pnThreadsTitle';
    wrap.appendChild(h);
    wrap.appendChild(filters());
    var shown = report.threads.filter(function (th) {
      return (filter.verdict === 'all' || th.verdict === filter.verdict)
        && (!filter.member || (th.by || []).indexOf(filter.member) >= 0
            || th.messages.some(function (m) { return m.from === filter.member; }));
    });
    var count = el('p', 'pn-count', t('panel.count', { n: shown.length }));
    count.setAttribute('role', 'status');
    wrap.appendChild(count);
    shown.forEach(function (th) { wrap.appendChild(thread(th)); });
    if (!shown.length) wrap.appendChild(el('p', 'pn-state', t('panel.none')));
    return wrap;
  }

  function render() {
    root.textContent = '';
    root.setAttribute('data-state', state);
    if (state !== 'ready') {
      root.appendChild(el('p', 'pn-state', t('panel.' + state)));
      return;
    }
    root.appendChild(header());
    root.appendChild(top());
    root.appendChild(members());
    root.appendChild(threads());
  }

  document.addEventListener('babdoduk-lang', render);
  var refreshTimer = null;
  document.addEventListener('babdoduk-panel-complete', function () {
    clearTimeout(refreshTimer);
    var previousAt = report && report.run.at;
    var attempts = 0;
    function refresh() {
      fetch(DATA, { cache: 'no-store', signal: AbortSignal.timeout(8000) }).then(function (res) {
        if (!res.ok) throw new Error('unavailable');
        return res.json();
      }).then(function (data) {
        if (!valid(data)) throw new Error('invalid');
        if (data.run.at !== previousAt) {
          report = data; state = 'ready'; render(); return;
        }
        if (++attempts < 30) refreshTimer = setTimeout(refresh, 10000);
      }).catch(function () {
        if (++attempts < 30) refreshTimer = setTimeout(refresh, 10000);
      });
    }
    refresh();
  });
  fetch(DATA, { cache: 'no-cache' }).then(function (res) {
    if (!res.ok) throw new Error('unavailable');
    return res.json();
  }).then(function (data) {
    if (!valid(data)) throw new Error('invalid');
    report = data;
    state = data.threads.length ? 'ready' : 'empty';
  }).catch(function () {
    state = 'off';
  }).then(render);
  render();
}());
