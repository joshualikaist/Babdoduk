/* 밥약 메이커 (bobyak.html, lab only; docs/BOBYAK.md): restaurant roulette, place card, 먹킷리스트 and bill split.
   Reads data/places/latest.json and nothing else; no account, no server writes, no analytics.
   Needs js/bob-places.js (BabdodukPlaces), js/bob-settle.js (BabdodukSettle) and, for sharing,
   js/ggongbab-live.js (BabdodukLive.share: share sheet, then clipboard, then text to copy by hand). */
(function () {
  var P = window.BabdodukPlaces;
  var S = window.BabdodukSettle;
  var Live = window.BabdodukLive;
  if (!P || !S) return;
  var DATA_URL = 'data/places/latest.json';

  var store = P.createStore();
  var state = {
    load: 'loading',          // loading | ready | error
    feed: null,
    places: [],
    filters: { area: 'all', cuisine: 'all', budget: 'all' },
    savedOnly: false,
    consent: false,           // the visitor agreed to unchecked candidates (this visit only)
    filtersOpen: false,
    shown: null,              // {id, from: 'pick'|'list'|'link', pool}
    last: null,
    settle: { total: '', mode: 'split', unit: 1, payer: 0,
              people: [{ name: '', excluded: false, fixed: '' }, { name: '', excluded: false, fixed: '' }] }
  };

  function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
  function T(key, vars) {
    var table = (window.BABDODUK_STR || {})[lang()] || {};
    var text = table[key];
    if (text === undefined) text = ((window.BABDODUK_STR || {}).ko || {})[key];
    if (text === undefined) text = key;
    if (vars) Object.keys(vars).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function $(id) { return document.getElementById(id); }
  function byId(id) {
    for (var i = 0; i < state.places.length; i++) if (state.places[i].id === id) return state.places[i];
    return null;
  }
  function placeName(place) { return place.branch ? place.name + ' ' + place.branch : place.name; }
  function won(amount) { return S.formatWon(amount, lang()); }

  // ---------- Toast and manual copy ----------
  var toastTimer = null;
  function announce(text) {
    var toast = $('bobToast');
    toast.textContent = text;
    toast.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove('is-on'); }, 3200);
  }
  function showCopy(text) {
    var box = $('bobCopy');
    box.innerHTML = '<p class="bob-copy-note">' + esc(T('bob.share.manual')) + '</p>'
      + '<textarea class="bob-copy-text" id="bobCopyText" readonly rows="5" aria-label="' + esc(T('bob.share.manualAria')) + '">' + esc(text) + '</textarea>'
      + '<button type="button" class="bob-btn" data-bob="copy-close">' + esc(T('bob.share.close')) + '</button>';
    box.hidden = false;
    var area = $('bobCopyText');
    area.focus();
    area.select();
  }
  function shareOut(payload, copiedKey) {
    if (!Live || !Live.share) {
      showCopy(payload.text ? payload.text + '\n' + payload.url : payload.url);
      return;
    }
    Live.share(payload).then(function (outcome) {
      if (outcome === 'copied') announce(T(copiedKey || 'bob.share.copied'));
      else if (outcome === 'manual') showCopy(payload.text ? payload.text + '\n' + payload.url : payload.url);
    });
  }
  function pageUrl() { return location.href.split('#')[0].split('?')[0]; }

  // ---------- Data ----------
  function loadData() {
    state.load = 'loading';
    renderPick();
    fetch(DATA_URL, { cache: 'no-cache' }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (feed) {
      if (!feed || !Array.isArray(feed.places)) throw new Error('shape');
      state.feed = feed;
      state.places = feed.places.filter(function (place) { return place && P.ID_RE.test(String(place.id || '')); });
      state.load = 'ready';
      var linked = P.idFromQuery(location.search);
      if (linked) state.shown = { id: linked, from: 'link' };
      renderAll();
      if (linked) focusCard();
    }).catch(function () {
      state.load = 'error';
      renderAll();
    });
  }

  // ---------- Roulette ----------
  function activeFilters() {
    var n = 0;
    ['area', 'cuisine', 'budget'].forEach(function (key) { if (state.filters[key] !== 'all') n += 1; });
    return n + (state.savedOnly ? 1 : 0);
  }
  function dataNote() {
    if (state.load === 'loading') return T('bob.pick.loading');
    if (state.load === 'error') return T('bob.pick.loadError');
    var c = P.counts(state.places);
    var vars = { verified: c.verified, candidate: c.candidate, date: state.feed.updatedAt || '' };
    return state.feed.updatedAt ? T('bob.pick.dataNote', vars) : T('bob.pick.dataNoteNoDate', vars);
  }
  function chip(group, value, label, on) {
    return '<button type="button" class="bob-chip" data-bob="filter" data-group="' + group + '" data-value="' + esc(value)
      + '" aria-pressed="' + (on ? 'true' : 'false') + '">' + esc(label) + '</button>';
  }
  function filterGroup(group, title, options) {
    return '<div class="bob-filter-group" role="group" aria-label="' + esc(T('bob.filter.groupAria', { name: title })) + '">'
      + '<p class="bob-filter-title">' + esc(title) + '</p><div class="bob-chips">'
      + chip(group, 'all', T('bob.filter.all'), state.filters[group] === 'all')
      + options.map(function (value) { return chip(group, value, T('bob.' + group + '.' + value), state.filters[group] === value); }).join('')
      + '</div></div>';
  }
  function filtersHtml() {
    var present = {};
    state.places.forEach(function (place) {
      if (place.status === 'verified' || place.status === 'candidate') present[place.cuisine] = true;
    });
    var cuisines = P.CUISINES.filter(function (value) { return present[value] || state.filters.cuisine === value; });
    return filterGroup('area', T('bob.filter.area'), P.AREAS)
      + filterGroup('cuisine', T('bob.filter.cuisine'), cuisines)
      + filterGroup('budget', T('bob.filter.budget'), P.BUDGETS)
      + '<div class="bob-filter-foot">'
      + '<button type="button" class="bob-chip" data-bob="saved-only" aria-pressed="' + (state.savedOnly ? 'true' : 'false') + '">'
      + esc(T('bob.filter.saved')) + '</button>'
      + (activeFilters() ? '<button type="button" class="bob-link-btn" data-bob="reset">' + esc(T('bob.pick.reset')) + '</button>' : '')
      + '</div>';
  }
  function renderPick() {
    $('bobDataNote').textContent = dataNote();
    var toggle = $('bobFiltersToggle');
    var n = activeFilters();
    toggle.textContent = n ? T('bob.pick.filtersOn', { n: n }) : T('bob.pick.filters');
    toggle.setAttribute('aria-expanded', state.filtersOpen ? 'true' : 'false');
    var panel = $('bobFilters');
    panel.hidden = !state.filtersOpen;
    panel.innerHTML = state.filtersOpen ? filtersHtml() : '';
    $('bobSpin').disabled = state.load !== 'ready';
    renderResult();
  }
  function spin() {
    var result = P.pick(state.places, {
      area: state.filters.area, cuisine: state.filters.cuisine, budget: state.filters.budget,
      consent: state.consent, savedIds: state.savedOnly ? store.ids() : null, avoid: state.last
    });
    if (result.status === 'ok') {
      state.last = result.place.id;
      state.shown = { id: result.place.id, from: 'pick', pool: result.pool };
    } else {
      state.shown = { result: result };
    }
    renderResult();
    focusCard();
  }
  function emptyHtml(reason) {
    var key = reason === 'saved' ? 'bob.pick.emptySaved' : (reason === 'filters' ? 'bob.pick.emptyFilters' : 'bob.pick.emptyData');
    return '<div class="bob-state" tabindex="-1" data-bob-focus><p>' + esc(T(key)) + '</p>'
      + (reason === 'filters' ? '<button type="button" class="bob-btn" data-bob="reset">' + esc(T('bob.pick.reset')) + '</button>' : '')
      + '</div>';
  }
  function consentHtml(count) {
    return '<div class="bob-consent" tabindex="-1" data-bob-focus role="group" aria-labelledby="bobConsentTitle">'
      + '<p class="bob-consent-title" id="bobConsentTitle">' + esc(T('bob.pick.consentTitle')) + '</p>'
      + '<p>' + esc(T('bob.pick.consentBody', { n: count })) + '</p>'
      + '<div class="bob-actions">'
      + '<button type="button" class="bob-btn bob-btn--primary" data-bob="consent">' + esc(T('bob.pick.consentYes')) + '</button>'
      + '<button type="button" class="bob-btn" data-bob="open-filters">' + esc(T('bob.pick.consentNo')) + '</button>'
      + '</div></div>';
  }
  function renderResult() {
    var box = $('bobResult');
    var html = '';
    if (state.load === 'error') {
      html = '<div class="bob-state" data-state="error"><p>' + esc(T('bob.pick.loadError')) + '</p>'
        + '<button type="button" class="bob-btn" data-bob="retry">' + esc(T('bob.pick.retry')) + '</button></div>';
    } else if (state.load === 'ready' && !state.places.length && !state.shown) {
      html = '<div class="bob-state" data-state="empty"><p>' + esc(T('bob.pick.emptyData')) + '</p></div>';
    } else if (state.shown && state.shown.result) {
      var r = state.shown.result;
      html = r.status === 'consent' ? consentHtml(r.count) : emptyHtml(r.reason);
    } else if (state.shown && state.load === 'ready') {
      var place = byId(state.shown.id);
      html = place ? cardHtml(place, state.shown)
        : '<div class="bob-state" tabindex="-1" data-bob-focus data-state="missing"><p>' + esc(T('bob.card.notFound')) + '</p></div>';
    }
    if (state.consent && state.load === 'ready') {
      html = '<p class="bob-consent-on">' + esc(T('bob.pick.consentOn'))
        + ' <button type="button" class="bob-link-btn" data-bob="consent-off">' + esc(T('bob.pick.consentOff')) + '</button></p>' + html;
    }
    box.innerHTML = html;
  }
  function focusCard() {
    var target = $('bobResult').querySelector('[data-bob-focus]');
    if (!target) return;
    try { target.focus({ preventScroll: true }); } catch (err) { target.focus(); }
    if (target.scrollIntoView) target.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
  }
  function reducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // ---------- Place card ----------
  var SHOWN_FACTS = ['budget', 'menu', 'hours'];
  function factRow(fact) {
    var text = lang() === 'en' && fact.textEn ? fact.textEn : fact.text;
    if (fact.kind === 'budget' && fact.band) text = T('bob.budget.' + fact.band) + (text ? ' · ' + text : '');
    var meta = T('bob.factMeta', { source: T('bob.factSource.' + fact.source), date: fact.checkedAt });
    return '<div class="bob-fact"><dt>' + esc(T('bob.fact.' + fact.kind)) + '</dt><dd>' + esc(text)
      + ' <span class="bob-fact-meta">' + esc(meta) + '</span></dd></div>';
  }
  function statusNote(place) {
    if (place.status === 'verified') {
      return place.verifiedAt ? T('bob.statusNote.verified', { date: place.verifiedAt }) : '';
    }
    return T('bob.statusNote.' + place.status);
  }
  function listButtons(place) {
    var saved = store.get(place.id);
    var html = '<div class="bob-list-buttons" role="group" aria-label="' + esc(T('bob.list.groupAria')) + '">';
    P.LIST_STATUSES.forEach(function (status) {
      html += '<button type="button" class="bob-chip" data-bob="list-set" data-id="' + esc(place.id) + '" data-status="' + status
        + '" aria-pressed="' + (saved && saved.status === status ? 'true' : 'false') + '">' + esc(T('bob.list.' + status)) + '</button>';
    });
    if (saved) {
      html += '<button type="button" class="bob-link-btn" data-bob="list-remove" data-id="' + esc(place.id) + '" aria-label="'
        + esc(T('bob.list.removeAria', { name: placeName(place) })) + '">' + esc(T('bob.list.remove')) + '</button>';
    }
    return html + '</div>';
  }
  function memoHtml(place, where) {
    var saved = store.get(place.id);
    if (!saved || !store.writable()) return '';
    var id = 'bobMemo-' + where + '-' + place.id;
    return '<div class="bob-memo"><label for="' + esc(id) + '">' + esc(T('bob.list.memo')) + '</label>'
      + '<textarea id="' + esc(id) + '" rows="2" maxlength="' + P.MAX_MEMO + '" data-memo-for="' + esc(place.id) + '">' + esc(saved.memo) + '</textarea>'
      + '<button type="button" class="bob-btn" data-bob="memo-save" data-id="' + esc(place.id) + '" data-memo="' + esc(id) + '">'
      + esc(T('bob.list.memoSave')) + '</button></div>';
  }
  function cardHtml(place, shown) {
    var links = P.mapLinks(place);
    var name = placeName(place);
    var semas = (place.sources || []).filter(function (source) { return source.kind === 'semas'; })[0];
    var facts = (place.facts || []);
    var known = {};
    facts.forEach(function (fact) { known[fact.kind] = true; });
    var rows = '<div class="bob-fact"><dt>' + esc(T('bob.card.area')) + '</dt><dd>' + esc(T('bob.area.' + place.area))
      + ' · ' + esc(place.address) + '</dd></div>'
      + '<div class="bob-fact"><dt>' + esc(T('bob.card.cuisine')) + '</dt><dd>' + esc(T('bob.cuisine.' + place.cuisine)) + '</dd></div>'
      + facts.map(factRow).join('')
      + SHOWN_FACTS.filter(function (kind) { return !known[kind]; }).map(function (kind) {
        return '<div class="bob-fact"><dt>' + esc(T('bob.fact.' + kind)) + '</dt><dd class="bob-unknown">' + esc(T('bob.card.unknown')) + '</dd></div>';
      }).join('');
    var kicker = shown.from === 'pick' ? T('bob.pick.resultKicker') : T('bob.card.kicker');
    var html = '<article class="bob-card bob-card--' + esc(place.status) + '" data-id="' + esc(place.id) + '" tabindex="-1" data-bob-focus aria-labelledby="bobCardName">'
      + '<p class="bob-card-kicker">' + esc(kicker) + '</p>'
      + '<h3 class="bob-card-name" id="bobCardName">' + esc(name) + '</h3>'
      + (place.nameEn ? '<p class="bob-card-en" lang="en">' + esc(place.nameEn) + '</p>' : '')
      + '<p class="bob-badge bob-badge--' + esc(place.status) + '">' + esc(T('bob.status.' + place.status)) + '</p>'
      + (statusNote(place) ? '<p class="bob-card-note">' + esc(statusNote(place)) + '</p>' : '')
      + (shown.pool === 'candidate' ? '<p class="bob-card-note">' + esc(T('bob.pick.fromCandidates')) + '</p>' : '')
      + '<dl class="bob-facts">' + rows + '</dl>'
      + (semas ? '<p class="bob-source">' + esc(T('bob.card.source', { source: T('bob.card.sourceSemas'), date: semas.checkedAt })) + '</p>' : '')
      + listButtons(place)
      + memoHtml(place, 'card')
      + '<div class="bob-actions">'
      + '<button type="button" class="bob-btn" data-bob="share-place" data-id="' + esc(place.id) + '" aria-label="'
      + esc(T('bob.card.shareAria', { name: name })) + '">' + esc(T('bob.card.share')) + '</button>'
      + '<a class="bob-btn" href="' + esc(links.naver) + '" target="_blank" rel="noopener" aria-label="'
      + esc(T('bob.card.mapAria', { map: T('bob.card.naver'), name: name })) + '">' + esc(T('bob.card.naver')) + '</a>'
      + '<a class="bob-btn" href="' + esc(links.kakao) + '" target="_blank" rel="noopener" aria-label="'
      + esc(T('bob.card.mapAria', { map: T('bob.card.kakao'), name: name })) + '">' + esc(T('bob.card.kakao')) + '</a>'
      + (shown.from === 'pick' ? '<button type="button" class="bob-btn bob-btn--primary" data-bob="spin">' + esc(T('bob.pick.again')) + '</button>' : '')
      + '</div>'
      + '</article>';
    return html;
  }
  function sharePlace(id) {
    var place = byId(id);
    if (!place) return;
    // The memo and the list status stay out: only the place's public name, area and link.
    shareOut({ title: placeName(place),
               text: T('bob.share.placeText', { name: placeName(place), area: T('bob.area.' + place.area) }),
               url: P.placeLink(place.id, pageUrl()) });
  }

  // ---------- 먹킷리스트 ----------
  function renderList() {
    var body = $('bobListBody');
    var items = store.list();
    var notes = '';
    if (store.recovered()) notes += '<p class="bob-warn">' + esc(T('bob.list.recovered')) + '</p>';
    if (!store.writable()) notes += '<p class="bob-warn">' + esc(T(items.length ? 'bob.list.readOnly' : 'bob.list.cannotSave')) + '</p>';
    if (!items.length) {
      body.innerHTML = notes + '<p class="bob-state">' + esc(T('bob.list.empty')) + '</p>';
      return;
    }
    var html = notes;
    P.LIST_STATUSES.forEach(function (status) {
      var group = items.filter(function (item) { return item.status === status; });
      if (!group.length) return;
      html += '<section class="bob-list-group" aria-labelledby="bobListH-' + status + '">'
        + '<h3 class="bob-list-title" id="bobListH-' + status + '">' + esc(T('bob.list.' + status))
        + ' <span class="bob-count">' + esc(T('bob.list.count', { n: group.length })) + '</span></h3><ul class="bob-rows">';
      group.forEach(function (item) { html += rowHtml(item); });
      html += '</ul></section>';
    });
    body.innerHTML = html;
  }
  function rowHtml(item) {
    var place = state.load === 'ready' ? byId(item.id) : null;
    if (state.load === 'ready' && !place) {
      return '<li class="bob-row bob-row--missing"><div class="bob-row-main"><p class="bob-row-name">' + esc(T('bob.list.missing'))
        + '</p><p class="bob-row-meta">' + esc(T('bob.list.missingNote')) + '</p></div>'
        + '<button type="button" class="bob-btn" data-bob="list-remove" data-id="' + esc(item.id) + '">' + esc(T('bob.list.remove')) + '</button></li>';
    }
    var name = place ? placeName(place) : item.id;
    return '<li class="bob-row"><div class="bob-row-main"><p class="bob-row-name">' + esc(name) + '</p>'
      + (place ? '<p class="bob-row-meta">' + esc(T('bob.area.' + place.area)) + ' · ' + esc(T('bob.cuisine.' + place.cuisine))
        + ' · <span class="bob-badge bob-badge--' + esc(place.status) + '">' + esc(T('bob.status.' + place.status)) + '</span></p>' : '')
      + (item.memo ? '<p class="bob-row-memo">' + esc(item.memo) + '</p>' : '')
      + '</div>'
      + (place ? '<button type="button" class="bob-btn" data-bob="open" data-id="' + esc(item.id) + '" aria-label="'
        + esc(T('bob.list.openAria', { name: name })) + '">' + esc(T('bob.list.open')) + '</button>' : '')
      + '</li>';
  }

  // ---------- 정산 ----------
  function settleInput() {
    var s = state.settle;
    return {
      total: S.parseWon(s.total), mode: s.mode, unit: s.unit, payer: s.payer,
      people: s.people.map(function (person) {
        var fixed = String(person.fixed || '').trim();
        return { name: person.name, excluded: s.mode === 'split' && person.excluded, fixed: fixed === '' ? null : S.parseWon(fixed) };
      })
    };
  }
  function personName(index) {
    var name = String(state.settle.people[index].name || '').trim();
    return name || T('bob.settle.person', { n: index + 1 });
  }
  function renderSettleForm() {
    var s = state.settle;
    var html = '<div class="bob-field"><label for="bobTotal">' + esc(T('bob.settle.total')) + '</label>'
      + '<div class="bob-money"><input id="bobTotal" type="text" inputmode="numeric" autocomplete="off" data-settle="total" value="'
      + esc(s.total) + '" placeholder="' + esc(T('bob.settle.totalPlaceholder')) + '"><span aria-hidden="true">' + esc(T('bob.settle.won')) + '</span></div></div>'
      + '<div class="bob-field" role="group" aria-labelledby="bobModeLabel"><p class="bob-label" id="bobModeLabel">' + esc(T('bob.settle.mode')) + '</p><div class="bob-chips">'
      + '<button type="button" class="bob-chip" data-bob="mode" data-value="split" aria-pressed="' + (s.mode === 'split') + '">' + esc(T('bob.settle.modeSplit')) + '</button>'
      + '<button type="button" class="bob-chip" data-bob="mode" data-value="treat" aria-pressed="' + (s.mode === 'treat') + '">' + esc(T('bob.settle.modeTreat')) + '</button>'
      + '</div></div>';
    if (s.mode === 'split') {
      html += '<div class="bob-field"><label for="bobUnit">' + esc(T('bob.settle.unit')) + '</label><select id="bobUnit" data-settle="unit">'
        + S.UNITS.map(function (unit) {
          return '<option value="' + unit + '"' + (unit === s.unit ? ' selected' : '') + '>' + esc(T('bob.settle.unit' + unit)) + '</option>';
        }).join('') + '</select></div>';
    }
    html += '<p class="bob-label">' + esc(T('bob.settle.people')) + '</p><ol class="bob-people">';
    s.people.forEach(function (person, i) {
      var label = personName(i);
      html += '<li class="bob-person" data-index="' + i + '">'
        + '<input type="text" class="bob-person-name" data-settle="name" data-index="' + i + '" maxlength="30" value="' + esc(person.name)
        + '" placeholder="' + esc(T('bob.settle.person', { n: i + 1 })) + '" aria-label="' + esc(T('bob.settle.nameAria', { n: i + 1 })) + '">';
      if (s.mode === 'split') {
        html += '<input type="text" class="bob-person-fixed" inputmode="numeric" autocomplete="off" data-settle="fixed" data-index="' + i
          + '" value="' + esc(person.fixed) + '" placeholder="' + esc(T('bob.settle.fixedPlaceholder')) + '" aria-label="'
          + esc(T('bob.settle.fixedAria', { name: label })) + '"' + (person.excluded ? ' disabled' : '') + '>'
          + '<button type="button" class="bob-chip" data-bob="exclude" data-index="' + i + '" aria-pressed="' + !!person.excluded
          + '" aria-label="' + esc(T('bob.settle.excludeAria', { name: label })) + '">' + esc(T('bob.settle.exclude')) + '</button>';
      } else {
        html += '<button type="button" class="bob-chip" data-bob="payer" data-index="' + i + '" aria-pressed="' + (s.payer === i)
          + '" aria-label="' + esc(T('bob.settle.payerAria', { name: label })) + '">' + esc(T('bob.settle.payer')) + '</button>';
      }
      html += '<button type="button" class="bob-icon-btn" data-bob="remove-person" data-index="' + i + '" aria-label="'
        + esc(T('bob.settle.removeAria', { name: label })) + '"' + (s.people.length <= 1 ? ' disabled' : '') + '><span aria-hidden="true">×</span></button>'
        + '</li>';
    });
    html += '</ol><button type="button" class="bob-btn" data-bob="add-person"' + (s.people.length >= S.MAX_PEOPLE ? ' disabled' : '') + '>'
      + esc(T('bob.settle.add')) + '</button>';
    $('bobSettleForm').innerHTML = html;
    renderSettleResult();
  }
  function settleOutcome() {
    if (String(state.settle.total).trim() === '') return null;
    return S.settle(settleInput());
  }
  function renderSettleResult() {
    var box = $('bobSettleResult');
    var result = settleOutcome();
    if (!result) {
      box.innerHTML = '<p class="bob-note">' + esc(T('bob.settle.hint')) + '</p>';
      return;
    }
    if (!result.ok) {
      var input = settleInput();
      var fixedSum = input.people.reduce(function (acc, p) { return acc + (!p.excluded && isFinite(p.fixed) && p.fixed !== null ? p.fixed : 0); }, 0);
      box.innerHTML = '<p class="bob-error" data-error="' + esc(result.error) + '">' + esc(T('bob.settle.err.' + result.error, { sum: won(fixedSum) })) + '</p>';
      return;
    }
    var html = '<h3 class="bob-result-title">' + esc(T('bob.settle.resultTitle')) + '</h3><ul class="bob-shares">';
    result.shares.forEach(function (share) {
      var tags = [];
      if (share.excluded) tags.push(T('bob.settle.tagExcluded'));
      if (share.fixed !== null) tags.push(T('bob.settle.tagFixed'));
      if (result.mode === 'treat' && share.amount === result.total && result.total > 0) tags.push(T('bob.settle.tagTreat'));
      html += '<li class="bob-share' + (share.excluded ? ' is-excluded' : '') + '"><span class="bob-share-name">' + esc(personName(share.index))
        + (tags.length ? ' <span class="bob-tag">' + esc(tags.join(' · ')) + '</span>' : '') + '</span>'
        + '<span class="bob-share-amount" data-amount="' + share.amount + '">' + esc(won(share.amount)) + '</span></li>';
    });
    var sum = result.shares.reduce(function (acc, share) { return acc + share.amount; }, 0);
    html += '</ul><p class="bob-sum">' + esc(T('bob.settle.sum', { sum: won(sum) })) + '</p>';
    if (result.mode === 'split') html += '<p class="bob-note">' + esc(T('bob.settle.rule', { unit: won(result.unit) })) + '</p>';
    html += '<button type="button" class="bob-btn bob-btn--primary" data-bob="share-settle">' + esc(T('bob.settle.share')) + '</button>';
    box.innerHTML = html;
  }
  function settleText(result) {
    var lines = [T('bob.settle.shareHead', { total: won(result.total) })];
    result.shares.forEach(function (share) {
      var tag = share.excluded ? ' (' + T('bob.settle.tagExcluded') + ')' : '';
      lines.push('- ' + personName(share.index) + ' ' + won(share.amount) + tag);
    });
    lines.push(T('bob.settle.shareFoot'));
    return lines.join('\n');
  }

  // ---------- Render and events ----------
  function renderAll() {
    renderPick();
    renderList();
    renderSettleForm();
  }
  function onClick(event) {
    var el = event.target.closest('[data-bob]');
    if (!el) return;
    var action = el.getAttribute('data-bob');
    var id = el.getAttribute('data-id');
    var index = parseInt(el.getAttribute('data-index'), 10);
    var s = state.settle;
    switch (action) {
      case 'spin': spin(); break;
      case 'retry': loadData(); break;
      case 'filter':
        state.filters[el.getAttribute('data-group')] = el.getAttribute('data-value');
        state.shown = null;
        renderPick();
        refocus('[data-bob="filter"][data-group="' + el.getAttribute('data-group') + '"][data-value="' + el.getAttribute('data-value') + '"]');
        break;
      case 'saved-only':
        state.savedOnly = !state.savedOnly;
        state.shown = null;
        renderPick();
        refocus('[data-bob="saved-only"]');
        break;
      case 'reset':
        state.filters = { area: 'all', cuisine: 'all', budget: 'all' };
        state.savedOnly = false;
        state.shown = null;
        renderPick();
        $('bobSpin').focus();
        break;
      case 'open-filters':
        state.filtersOpen = true;
        state.shown = null;
        renderPick();
        var first = $('bobFilters').querySelector('button');
        if (first) first.focus();
        break;
      case 'consent':
        state.consent = true;
        spin();
        break;
      case 'consent-off':
        state.consent = false;
        state.shown = null;
        renderPick();
        $('bobSpin').focus();
        break;
      case 'list-set':
        if (store.set(id, el.getAttribute('data-status'))) {
          announce(T('bob.list.added', { status: T('bob.list.' + el.getAttribute('data-status')) }));
        } else if (!store.writable()) {
          announce(T('bob.list.cannotSave'));
        }
        renderResult();
        renderList();
        refocus('[data-bob="list-set"][data-id="' + id + '"][data-status="' + el.getAttribute('data-status') + '"]');
        break;
      case 'list-remove':
        if (store.remove(id)) announce(T('bob.list.removed'));
        renderResult();
        renderList();
        refocus('[data-bob="list-set"][data-id="' + id + '"]') || $('bobListTitle').focus();
        break;
      case 'memo-save':
        var area = $(el.getAttribute('data-memo'));
        if (area && store.setMemo(id, area.value)) announce(T('bob.list.memoSaved'));
        renderList();
        break;
      case 'open':
        state.shown = { id: id, from: 'list' };
        renderResult();
        focusCard();
        break;
      case 'share-place': sharePlace(id); break;
      case 'copy-close':
        $('bobCopy').hidden = true;
        $('bobCopy').innerHTML = '';
        break;
      case 'mode':
        s.mode = el.getAttribute('data-value');
        renderSettleForm();
        refocus('[data-bob="mode"][data-value="' + s.mode + '"]');
        break;
      case 'exclude':
        s.people[index].excluded = !s.people[index].excluded;
        renderSettleForm();
        refocus('[data-bob="exclude"][data-index="' + index + '"]');
        break;
      case 'payer':
        s.payer = index;
        renderSettleForm();
        refocus('[data-bob="payer"][data-index="' + index + '"]');
        break;
      case 'add-person':
        if (s.people.length < S.MAX_PEOPLE) s.people.push({ name: '', excluded: false, fixed: '' });
        renderSettleForm();
        refocus('.bob-person-name[data-index="' + (s.people.length - 1) + '"]');
        break;
      case 'remove-person':
        if (s.people.length > 1) {
          s.people.splice(index, 1);
          if (s.payer === index) s.payer = 0;
          else if (s.payer > index) s.payer -= 1;
        }
        renderSettleForm();
        refocus('.bob-person-name[data-index="' + Math.min(index, s.people.length - 1) + '"]');
        break;
      case 'share-settle':
        var result = settleOutcome();
        if (result && result.ok) shareOut({ title: T('bob.title'), text: settleText(result), url: pageUrl() }, 'bob.share.copiedText');
        break;
    }
  }
  function refocus(selector) {
    var el = document.querySelector('#bobApp ' + selector);
    if (el) el.focus();
    return !!el;
  }
  function onInput(event) {
    var el = event.target;
    var field = el.getAttribute && el.getAttribute('data-settle');
    if (!field) return;
    var s = state.settle;
    var index = parseInt(el.getAttribute('data-index'), 10);
    if (field === 'total') s.total = el.value;
    else if (field === 'unit') s.unit = parseInt(el.value, 10);
    else if (field === 'name') s.people[index].name = el.value;
    else if (field === 'fixed') s.people[index].fixed = el.value;
    renderSettleResult();
  }

  $('bobFiltersToggle').addEventListener('click', function () {
    state.filtersOpen = !state.filtersOpen;
    renderPick();
  });
  $('bobSpin').addEventListener('click', spin);
  $('bobApp').addEventListener('click', function (event) {
    if (event.target.closest('#bobSpin, #bobFiltersToggle')) return;
    onClick(event);
  });
  $('bobApp').addEventListener('input', onInput);
  $('bobApp').addEventListener('change', onInput);
  document.addEventListener('babdoduk-lang', renderAll);
  window.addEventListener('storage', function (event) {
    if (event.key === P.SAVED_KEY) { store.reload(); renderList(); renderResult(); }
  });
  renderAll();
  loadData();
})();
