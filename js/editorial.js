/* Lab-only publishing UI. Credentials live only in encrypted HttpOnly server cookies. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var queue = { schemaVersion: 1, items: [] }, receipts = [], sha = null, csrf = '', active = null;
  var demo = false, dirty = false, busy = false, login = '', disabledBefore = new Map();
  var fields = ['title', 'text', 'summary', 'duration', 'prizes', 'participation', 'place'];
  function tr(key) { return (window.BABDODUK_STR[window.babdodukGetLang()] || {})['editor.' + key] || key; }
  function status(key, error) { $('editorStatus').removeAttribute('data-i18n'); $('editorStatus').textContent = tr(key); $('editorStatus').toggleAttribute('data-error', !!error); }
  function node(tag, text) { var el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; }
  function kstDay() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); }
  function published(id) { return receipts.some(function (r) { return r.id === id; }); }
  function setBusy(value) {
    busy = value;
    $('editorForm').querySelectorAll('input,textarea,select').forEach(function (el) {
      if (value) { disabledBefore.set(el, el.disabled); el.disabled = true; }
      else if (disabledBefore.has(el)) { el.disabled = disabledBefore.get(el); disabledBefore.delete(el); }
    });
    ['editorSave', 'editorSchedule', 'editorCancel', 'editorDelete', 'editorReload', 'editorNew'].forEach(function (id) { $(id).disabled = value || demo; });
  }
  async function api(action, method, body) {
    var response = await fetch('/api/editorial?action=' + action, { method: method || 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Editorial-CSRF': csrf }, body: body ? JSON.stringify(body) : undefined });
    var data;
    try { data = await response.json(); } catch (_) { throw new Error('unavailable'); }
    if (!response.ok) throw new Error(response.status === 409 ? 'conflict' : response.status === 401 || response.status === 403 ? 'denied' : 'failed');
    return data;
  }
  function updateKind() {
    var kind = $('editorKind').value;
    document.querySelectorAll('[data-kind]').forEach(function (el) {
      var hidden = el.getAttribute('data-kind') !== kind; el.hidden = hidden;
      el.querySelectorAll('input,textarea,select').forEach(function (input) { input.disabled = hidden; });
    });
    $('editorDate').required = kind === 'notice';
    ['editorStart', 'editorEnd', 'editorLink'].forEach(function (id) { $(id).required = kind === 'activity'; });
    ['ko', 'en'].forEach(function (lang) { $('text-' + lang).required = kind === 'notice'; $('summary-' + lang).required = kind === 'activity'; });
  }
  function readForm(state) {
    var pair = function (name) { return { ko: $(name + '-ko').value.trim(), en: $(name + '-en').value.trim() }; };
    var kind = $('editorKind').value, content = { title: pair('title') };
    if (kind === 'notice') { content.date = $('editorDate').value; content.text = pair('text'); }
    else {
      Object.assign(content, { start: $('editorStart').value, end: $('editorEnd').value, confirmation: $('editorConfirmation').value,
        link: $('editorLink').value.trim(), details: { summary: pair('summary') } });
      ['duration', 'prizes', 'participation'].forEach(function (name) { var value = pair(name); if (value.ko || value.en) content.details[name] = value; });
      var place = pair('place'); if (place.ko || place.en) content.place = place;
    }
    return { id: active || crypto.randomUUID(), kind: kind, status: state || 'draft',
      publishAt: $('editorPublishAt').value ? $('editorPublishAt').value + ':00+09:00' : null, content: content };
  }
  function rich(el, value) {
    // Preview the only allowed markup without ever assigning authored HTML to innerHTML.
    var strong = false;
    value.split(/(<\/?strong>)/).forEach(function (part) {
      if (part === '<strong>') strong = true;
      else if (part === '</strong>') strong = false;
      else if (part) el.append(strong ? node('strong', part) : document.createTextNode(part));
    });
  }
  function preview() {
    var entry = readForm(), c = entry.content, lang = window.babdodukGetLang(), box = $('editorPreview'); box.replaceChildren();
    box.append(node('small', entry.kind === 'notice' ? c.date : c.start + ' — ' + c.end), node('h3', c.title[lang] || tr('untitled')));
    if (entry.kind === 'notice') box.append(node('p', c.text[lang]));
    else {
      box.append(node('p', tr(c.confirmation) + (c.place ? ' · ' + c.place[lang] : '')));
      var dl = node('dl');
      ['summary', 'duration', 'prizes', 'participation'].forEach(function (key) { if (c.details[key]) { var dd = node('dd'); rich(dd, c.details[key][lang]); dl.append(node('dt', tr('field.' + key)), dd); } });
      box.append(dl);
      if (/^https:\/\//.test(c.link)) { var link = node('a', c.link); link.href = c.link; link.target = '_blank'; link.rel = 'noopener noreferrer'; box.append(link); }
    }
  }
  function renderList() {
    var list = $('editorList'); list.replaceChildren();
    if (!queue.items.length) list.append(node('li', tr('empty')));
    queue.items.forEach(function (entry) {
      var row = node('li'), button = node('button'), lang = window.babdodukGetLang(); button.type = 'button';
      if (entry.id === active) button.setAttribute('aria-current', 'true');
      button.append(node('strong', entry.content.title[lang]), node('small', published(entry.id) ? tr('published') : tr(entry.status)));
      if (entry.publishAt) button.append(node('small', entry.publishAt.slice(0, 16).replace('T', ' ') + ' KST'));
      button.addEventListener('click', function () { if (!busy && discard()) edit(entry); });
      row.append(button); list.append(row);
    });
  }
  function discard() { return !dirty || window.confirm(tr('discard')); }
  function edit(entry) {
    active = entry ? entry.id : null; $('editorForm').reset();
    $('editorForm').querySelectorAll('input,textarea,select').forEach(function (el) { el.disabled = false; });
    fields.forEach(function (name) { ['ko', 'en'].forEach(function (lang) { $(name + '-' + lang).value = ''; }); });
    $('editorKind').value = entry ? entry.kind : 'notice';
    $('editorDate').value = $('editorStart').value = $('editorEnd').value = kstDay();
    if (entry) {
      var c = entry.content; $('editorDate').value = c.date || ''; $('editorStart').value = c.start || ''; $('editorEnd').value = c.end || '';
      $('editorLink').value = c.link || ''; $('editorConfirmation').value = c.confirmation || 'announced';
      fields.forEach(function (name) { var pair = c[name] || (c.details || {})[name]; ['ko', 'en'].forEach(function (lang) { $(name + '-' + lang).value = pair ? pair[lang] : ''; }); });
      $('editorPublishAt').value = (entry.publishAt || '').slice(0, 16);
    }
    var locked = !!entry && published(entry.id);
    updateKind(); $('editorForm').querySelectorAll('input,textarea,select').forEach(function (el) { if (locked) el.disabled = true; });
    ['editorSave', 'editorSchedule', 'editorDelete'].forEach(function (id) { $(id).disabled = demo || locked; });
    $('editorCancel').disabled = demo || locked || !entry || entry.status !== 'scheduled';
    dirty = false; preview(); renderList();
  }
  async function reload() {
    setBusy(true);
    var loaded = false;
    try { var data = await api('queue'); queue = data.queue; sha = data.sha; receipts = data.receipts.items; loaded = true; status('loaded'); }
    catch (e) { status(e.message, true); }
    finally { setBusy(false); if (loaded) edit(null); }
  }
  async function persist(next, id) {
    if (demo || busy) return;
    setBusy(true); status('saving');
    try {
      var result = await api('queue', 'POST', { queue: next, sha: sha });
      queue = next; sha = result.sha; dirty = false; active = id;
      status(next.items.some(function (i) { return i.id === id && i.status === 'scheduled'; }) ? 'scheduledOk' : 'saved');
    } catch (e) { status(e.message, true); }
    finally {
      setBusy(false);
      var selected = queue.items.find(function (i) { return i.id === active; });
      if (!dirty) edit(selected || null);
    }
  }
  function save(state) {
    if (!$('editorForm').reportValidity()) return;
    var entry = readForm(state);
    if (state === 'scheduled') {
      if (!entry.publishAt || Date.parse(entry.publishAt) <= Date.now()) { status('future', true); return; }
      if (!window.confirm(tr('confirmSchedule'))) return;
    }
    var next = { schemaVersion: 1, items: queue.items.filter(function (i) { return i.id !== entry.id; }).concat([entry]) };
    persist(next, entry.id);
  }
  $('editorForm').addEventListener('input', function () { dirty = true; updateKind(); preview(); });
  $('editorForm').addEventListener('submit', function (event) { event.preventDefault(); save('draft'); });
  $('editorSchedule').addEventListener('click', function () { save('scheduled'); });
  $('editorCancel').addEventListener('click', function () {
    if (!active || !window.confirm(tr('confirmCancel'))) return;
    var next = structuredClone(queue), entry = next.items.find(function (i) { return i.id === active; }); entry.status = 'draft'; entry.publishAt = null; persist(next, active);
  });
  $('editorDelete').addEventListener('click', function () {
    if (!active || !window.confirm(tr('confirmDelete'))) return;
    persist({ schemaVersion: 1, items: queue.items.filter(function (i) { return i.id !== active; }) }, null);
  });
  $('editorNew').addEventListener('click', function () { if (discard()) edit(null); });
  $('editorReload').addEventListener('click', function () { if (discard()) reload(); });
  $('editorLogout').addEventListener('click', async function () {
    if (!discard()) return;
    try { await api('logout', 'POST'); location.reload(); } catch (e) { status(e.message, true); }
  });
  $('editorTry').addEventListener('click', function () {
    demo = true; $('editorAuth').hidden = true; $('editorWorkspace').hidden = false;
    $('editorIdentity').textContent = tr('demo'); $('editorLogout').hidden = true;
    setBusy(false); edit(null); status('demo');
  });
  document.addEventListener('babdoduk-lang', function () { renderList(); preview(); $('editorIdentity').textContent = demo ? tr('demo') : login; });
  window.addEventListener('beforeunload', function (event) { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  (async function () {
    try {
      var data = await api('session');
      if (!data.configured) { $('editorLogin').hidden = true; $('editorAuthHint').removeAttribute('data-i18n'); $('editorAuthHint').textContent = tr('setup'); status('setup'); }
      if (data.authenticated) {
        csrf = data.csrf; login = data.login; $('editorIdentity').textContent = login;
        $('editorWorkspace').hidden = false; await reload(); return;
      }
      $('editorAuth').hidden = false;
    } catch (e) { $('editorAuth').hidden = false; status(e.message, true); }
    updateKind();
  }());
}());
