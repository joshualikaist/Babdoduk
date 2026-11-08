/* 밥약 메이커 식당 (bobyak.html, docs/BOBYAK.md): the rules behind the restaurant roulette, the detail card's
   links and the 먹킷리스트 kept in this browser. No network calls; the page loads data/places/latest.json.

   - Roulette: verified places first. Candidates (public data nobody has checked) join only when no
     verified place fits and the visitor said yes; stale and closed places never come up.
   - Budget is matched only against a confirmed budget fact: a place whose prices nobody checked never
     matches a budget filter.
   - 먹킷리스트: localStorage `babdoduk-places-saved`, {v:1, items:[{id, status, memo, savedAt, updatedAt}]},
     status 'want' (가고 싶어) | 'been' (가봤어) | 'again' (또 갈래). The memo is private: it never goes into
     a link or a shared text. The fields mean what saved_places(place_id, status, memo, saved_at,
     updated_at) means, so a later account sync can lift the list as it is. */
(function (global) {
  var AREAS = ['kaist', 'eoeun', 'gung'];
  var CUISINES = ['korean', 'chinese', 'japanese', 'western', 'asian', 'snack', 'fastfood', 'cafe', 'bakery', 'pub', 'other'];
  var BUDGETS = ['under10k', '10to15k', 'over15k'];
  var STATUSES = ['verified', 'candidate', 'stale', 'closed'];
  var LIST_STATUSES = ['want', 'been', 'again'];
  var ID_RE = /^p-[0-9a-z]{4,24}$/;

  // ---------- Roulette ----------
  function budgetOf(place) {
    var facts = (place && place.facts) || [];
    for (var i = 0; i < facts.length; i++) {
      if (facts[i] && facts[i].kind === 'budget' && BUDGETS.indexOf(facts[i].band) >= 0) return facts[i].band;
    }
    return null;
  }
  function matches(place, filters) {
    filters = filters || {};
    if (filters.area && filters.area !== 'all' && place.area !== filters.area) return false;
    if (filters.cuisine && filters.cuisine !== 'all' && place.cuisine !== filters.cuisine) return false;
    if (filters.budget && filters.budget !== 'all' && budgetOf(place) !== filters.budget) return false;
    return true;
  }
  function choose(pool, avoid, random) {
    if (pool.length > 1 && avoid) {
      var others = pool.filter(function (place) { return place.id !== avoid; });
      if (others.length) pool = others;
    }
    var r = (random || Math.random)();
    return pool[Math.min(pool.length - 1, Math.floor(r * pool.length))];
  }
  /* opts: {area, cuisine, budget, consent, savedIds (array, or null for every place), avoid, random}
     -> {status:'ok', place, pool:'verified'|'candidate', size}
        {status:'consent', count}                       no verified place fits; count candidates would
        {status:'empty', reason:'data'|'saved'|'filters'} */
  function pick(places, opts) {
    opts = opts || {};
    places = Array.isArray(places) ? places : [];
    var saved = Array.isArray(opts.savedIds) ? opts.savedIds : null;
    var open = places.filter(function (place) {
      return place && (place.status === 'verified' || place.status === 'candidate')
        && (!saved || saved.indexOf(place.id) >= 0);
    });
    var fit = open.filter(function (place) { return matches(place, opts); });
    var verified = fit.filter(function (place) { return place.status === 'verified'; });
    if (verified.length) return { status: 'ok', place: choose(verified, opts.avoid, opts.random), pool: 'verified', size: verified.length };
    var candidates = fit.filter(function (place) { return place.status === 'candidate'; });
    if (candidates.length) {
      if (!opts.consent) return { status: 'consent', count: candidates.length };
      return { status: 'ok', place: choose(candidates, opts.avoid, opts.random), pool: 'candidate', size: candidates.length };
    }
    var reason = !open.length && saved ? 'saved' : (!places.length ? 'data' : (!open.length ? 'data' : 'filters'));
    return { status: 'empty', reason: reason };
  }
  function counts(places) {
    var out = { verified: 0, candidate: 0, stale: 0, closed: 0 };
    (places || []).forEach(function (place) { if (place && out[place.status] !== undefined) out[place.status] += 1; });
    return out;
  }

  // ---------- Links ----------
  // Search by name and address together, so a same-name shop elsewhere is not the first hit.
  function searchText(place) {
    var parts = [place.name, place.branch, place.address].filter(function (part) { return part && String(part).trim(); });
    return parts.join(' ');
  }
  function mapLinks(place) {
    var q = encodeURIComponent(searchText(place));
    return { naver: 'https://map.naver.com/p/search/' + q, kakao: 'https://map.kakao.com/?q=' + q };
  }
  function placeLink(id, base) {
    var path = 'bobyak.html?p=' + encodeURIComponent(id);
    return base ? String(base).replace(/[^/]*$/, '') + path : path;
  }
  function idFromQuery(search) {
    var match = /[?&]p=([^&#]*)/.exec(search || '');
    if (!match) return null;
    var id = decodeURIComponent(match[1]);
    return ID_RE.test(id) ? id : null;
  }

  // ---------- 먹킷리스트 ----------
  var SAVED_KEY = 'babdoduk-places-saved';
  var BACKUP_KEY = 'babdoduk-places-saved-unreadable';
  var VERSION = 1;
  var MAX_SAVED = 500;
  var MAX_MEMO = 500;

  function clip(value, n) { return typeof value === 'string' ? value.slice(0, n) : ''; }
  function cleanItem(item) {
    if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !ID_RE.test(item.id)) return null;
    if (LIST_STATUSES.indexOf(item.status) < 0) return null;
    return { id: item.id, status: item.status, memo: clip(item.memo, MAX_MEMO),
             savedAt: clip(item.savedAt, 40), updatedAt: clip(item.updatedAt, 40) };
  }
  // {items, writable, recovered}: unreadable data is set aside once and the list starts empty; a newer
  // schema than this page knows is shown but never rewritten.
  function readStore(storage) {
    var raw = null;
    if (!storage) return { items: [], writable: false };
    try { raw = storage.getItem(SAVED_KEY); } catch (err) { return { items: [], writable: false }; }
    if (raw == null || raw === '') return { items: [], writable: true };
    var data;
    try { data = JSON.parse(raw); } catch (err) { data = null; }
    if (!data || typeof data !== 'object' || !Array.isArray(data.items) || typeof data.v !== 'number') {
      try { if (storage.getItem(BACKUP_KEY) == null) storage.setItem(BACKUP_KEY, String(raw).slice(0, 50000)); } catch (err) {}
      try { storage.removeItem(SAVED_KEY); } catch (err) {}
      return { items: [], writable: true, recovered: true };
    }
    var seen = {};
    var items = data.items.map(cleanItem).filter(function (item) {
      if (!item || seen[item.id]) return false;
      seen[item.id] = true;
      return true;
    }).slice(0, MAX_SAVED);
    return { items: items, writable: data.v === VERSION };
  }
  function safeStorage() {
    try { return global.localStorage; } catch (err) { return null; }
  }
  function createStore(storage) {
    storage = storage === undefined ? safeStorage() : storage;
    var state = readStore(storage);
    function write() {
      if (!state.writable || !storage) return false;
      try {
        storage.setItem(SAVED_KEY, JSON.stringify({ v: VERSION, items: state.items }));
        return true;
      } catch (err) { return false; }
    }
    function find(id) {
      for (var i = 0; i < state.items.length; i++) if (state.items[i].id === id) return state.items[i];
      return null;
    }
    return {
      list: function () { return state.items.slice(); },
      ids: function () { return state.items.map(function (item) { return item.id; }); },
      get: find,
      has: function (id) { return !!find(id); },
      writable: function () { return state.writable; },
      recovered: function () { return !!state.recovered; },
      // Add the place with this status, or move it to this status. Keeps the memo.
      set: function (id, status, now) {
        if (!ID_RE.test(String(id || '')) || LIST_STATUSES.indexOf(status) < 0 || !state.writable) return false;
        var stamp = (now || new Date()).toISOString();
        var item = find(id);
        if (item) {
          if (item.status === status) return true;
          item.status = status;
          item.updatedAt = stamp;
        } else {
          if (state.items.length >= MAX_SAVED) return false;
          state.items.unshift({ id: id, status: status, memo: '', savedAt: stamp, updatedAt: stamp });
        }
        return write();
      },
      setMemo: function (id, memo, now) {
        var item = find(id);
        if (!item || !state.writable) return false;
        item.memo = clip(String(memo == null ? '' : memo), MAX_MEMO);
        item.updatedAt = (now || new Date()).toISOString();
        return write();
      },
      remove: function (id) {
        var before = state.items.length;
        state.items = state.items.filter(function (item) { return item.id !== id; });
        return state.items.length !== before && write();
      },
      reload: function () { state = readStore(storage); }
    };
  }

  global.BabdodukPlaces = {
    AREAS: AREAS, CUISINES: CUISINES, BUDGETS: BUDGETS, STATUSES: STATUSES, LIST_STATUSES: LIST_STATUSES,
    SAVED_KEY: SAVED_KEY, BACKUP_KEY: BACKUP_KEY, MAX_MEMO: MAX_MEMO, ID_RE: ID_RE,
    budgetOf: budgetOf, matches: matches, pick: pick, counts: counts,
    mapLinks: mapLinks, placeLink: placeLink, idFromQuery: idFromQuery, searchText: searchText,
    readStore: readStore, createStore: createStore
  };
})(window);
