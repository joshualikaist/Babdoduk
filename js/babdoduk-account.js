/* 마이 밥도둑 accounts (밥도둑 2.0 Phase 2, lab only; docs/MY_BABDODUK.md).
 *
 * window.BabdodukAccount: optional Google / kakao sign-in through Supabase Auth, the signed-in copy of
 * the saved free-food list (same interface as BabdodukLive.createStore), the one-time merge of what a
 * guest saved in this browser, and clearing data or leaving. Everything is off unless
 * js/babdoduk-auth-config.js enables it for the current host, so production never loads the SDK.
 *
 * Privacy: the browser holds only the publishable key. Account rows are private by RLS
 * (supabase/migrations/011_accounts.sql). Signing out keeps this browser's own guest list untouched;
 * the account list is never written into it.
 */
(function (global) {
  'use strict';

  var SDK_URL = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.116.0/dist/umd/supabase.js';
  var SDK_INTEGRITY = 'sha384-iLddHTLokph6Omwoyid4XKxHaWa6w41BnoEj0q5oOrzmYPpHIKt1wyjReA7s//pP';
  var SAVED_KEY = 'babdoduk-ggongbab-saved';
  var PLACES_KEY = 'babdoduk-places-saved';
  var MERGE_KEY = 'babdoduk-account-merged';
  var EVENT_ID = /^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$/;
  var PLACE_ID = /^[A-Za-z0-9_-]{1,80}$/;
  var PROVIDERS = ['google', 'kakao'];
  var RECENT_MS = 10 * 60 * 1000;   // delete_my_account() accepts a sign-in from the last 10 minutes
  var MAX_SAVED = 300;

  // ---- configuration ---------------------------------------------------------------------------
  function publicConfig() {
    var config = global.BABDODUK_PUBLIC_FEED_CONFIG || {};
    try {
      var url = new URL(config.SUPABASE_URL);
      var key = config.SUPABASE_PUBLISHABLE_KEY;
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') return null;
      if (typeof key !== 'string' || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) return null;
      var ref = url.hostname.split('.')[0];
      if (!/^[a-z0-9]{6,40}$/.test(ref)) return null;
      return { url: url.origin, key: key, ref: ref };
    } catch (e) { return null; }
  }
  function available() {
    var auth = global.BABDODUK_AUTH_CONFIG || {};
    var hosts = Array.isArray(auth.hosts) ? auth.hosts : [];
    return auth.enabled === true && hosts.indexOf(global.location.hostname) !== -1 && !!publicConfig();
  }
  function storage() { try { return global.localStorage; } catch (e) { return null; } }
  function tokenKey() { var c = publicConfig(); return c ? 'sb-' + c.ref + '-auth-token' : ''; }
  // A page other than my.html loads the SDK only for someone who already signed in on this browser.
  function hasSession() {
    var s = storage();
    try { return !!(s && tokenKey() && s.getItem(tokenKey())); } catch (e) { return false; }
  }

  // ---- client ----------------------------------------------------------------------------------
  function loadSdk() {
    if (global.supabase && global.supabase.createClient) return Promise.resolve(global.supabase);
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      var timeout = setTimeout(failed, 10000);
      function failed() { clearTimeout(timeout); script.remove(); reject(new Error('client unavailable')); }
      script.src = SDK_URL;
      script.integrity = SDK_INTEGRITY;
      script.crossOrigin = 'anonymous';
      script.referrerPolicy = 'no-referrer';
      script.onload = function () {
        clearTimeout(timeout);
        if (global.supabase && global.supabase.createClient) resolve(global.supabase); else failed();
      };
      script.onerror = failed;
      document.head.appendChild(script);
    });
  }
  var clientPromise = null;
  function client() {
    if (clientPromise) return clientPromise;
    if (!available()) return Promise.reject(new Error('accounts are off'));
    var config = publicConfig();
    clientPromise = loadSdk().then(function (sdk) {
      return sdk.createClient(config.url, config.key, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: 'pkce' }
      });
    });
    clientPromise.catch(function () { clientPromise = null; });
    return clientPromise;
  }
  function currentUser() {
    return client().then(function (c) { return c.auth.getSession(); }).then(function (res) {
      if (res && res.error) throw res.error;
      var session = res && res.data && res.data.session;
      return session && session.user ? session.user : null;
    });
  }
  function returnUrl(next) {
    var url = global.location.origin + '/my.html';
    return next && /^[a-z-]{1,20}$/.test(next) ? url + '?next=' + next : url;
  }
  // A full-page redirect (no popup), so it works the same inside the talk app's browser. Google refuses
  // embedded browsers; the page offers "open in the default browser" there instead of this call.
  function signIn(provider, next) {
    if (PROVIDERS.indexOf(provider) === -1) return Promise.reject(new Error('unknown provider'));
    return client().then(function (c) {
      return c.auth.signInWithOAuth({ provider: provider, options: { redirectTo: returnUrl(next) } });
    }).then(function (res) { if (res && res.error) throw res.error; return res; });
  }
  // Add another provider to the same account. Supabase needs "manual linking" on for this; a refusal
  // comes back as an error the page explains.
  function linkProvider(provider) {
    if (PROVIDERS.indexOf(provider) === -1) return Promise.reject(new Error('unknown provider'));
    return client().then(function (c) {
      if (!c.auth.linkIdentity) throw new Error('linking unavailable');
      return c.auth.linkIdentity({ provider: provider, options: { redirectTo: returnUrl('linked') } });
    }).then(function (res) { if (res && res.error) throw res.error; return res; });
  }
  // This device only: other devices stay signed in. The guest list in this browser is untouched.
  function signOut() {
    return client().then(function (c) { return c.auth.signOut({ scope: 'local' }); }).then(function (res) {
      if (res && res.error) throw res.error;
    });
  }
  function providersOf(user) {
    var out = [];
    ((user && user.identities) || []).forEach(function (identity) {
      var p = identity && identity.provider;
      if (PROVIDERS.indexOf(p) !== -1 && out.indexOf(p) === -1) out.push(p);
    });
    var listed = user && user.app_metadata && user.app_metadata.providers;
    (Array.isArray(listed) ? listed : []).forEach(function (p) {
      if (PROVIDERS.indexOf(p) !== -1 && out.indexOf(p) === -1) out.push(p);
    });
    return out;
  }
  // The provider's own name for the person, shown only to them. kakao may give no e-mail at all, and
  // nothing here needs one.
  function providerName(user) {
    var meta = (user && user.user_metadata) || {};
    var name = meta.full_name || meta.name || meta.nickname || meta.preferred_username || '';
    return typeof name === 'string' ? name.trim().slice(0, 40) : '';
  }
  function signedInRecently(user, now) {
    var at = Date.parse(user && user.last_sign_in_at);
    var t = (now || new Date()).getTime();
    return !isNaN(at) && t - at >= -60000 && t - at < RECENT_MS;
  }

  // ---- the guest copy in this browser ----------------------------------------------------------
  function readItems(key, idRe) {
    var s = storage();
    if (!s) return [];
    try {
      var value = JSON.parse(s.getItem(key) || 'null');
      if (!value || value.v !== 1 || !Array.isArray(value.items)) return [];
      return value.items.filter(function (item) { return item && idRe.test(String(item.id || '')); });
    } catch (e) { return []; }
  }
  function readMarks() {
    var s = storage();
    try {
      var value = JSON.parse((s && s.getItem(MERGE_KEY)) || 'null');
      return value && value.v === 1 && value.users && typeof value.users === 'object' ? value : { v: 1, users: {} };
    } catch (e) { return { v: 1, users: {} }; }
  }
  function lastMerged(uid) {
    var at = readMarks().users[uid];
    return typeof at === 'string' && !isNaN(Date.parse(at)) ? at : '';
  }
  function markMerged(uid, iso) {
    var s = storage();
    if (!s) return;
    var marks = readMarks();
    marks.users[uid] = iso;
    var ids = Object.keys(marks.users);
    if (ids.length > 10) ids.slice(0, ids.length - 10).forEach(function (id) { delete marks.users[id]; });
    try { s.setItem(MERGE_KEY, JSON.stringify(marks)); } catch (e) { /* the merge is idempotent anyway */ }
  }
  // What this browser saved that the account has not taken in yet: everything the first time this
  // account signs in here, afterwards only what was saved (or changed) since, so an item deleted on
  // another device does not come back from an old browser copy.
  function pending(uid) {
    var since = Date.parse(lastMerged(uid)) || 0;
    function fresh(item) {
      var at = Date.parse(item.updatedAt || item.savedAt);
      return !since || isNaN(at) || at > since;
    }
    return {
      events: readItems(SAVED_KEY, EVENT_ID).filter(fresh).slice(0, MAX_SAVED)
        .map(function (item) { return { id: item.id, savedAt: item.savedAt, seen: item.seen || {} }; }),
      places: readItems(PLACES_KEY, PLACE_ID).filter(fresh).slice(0, 1000)
        .map(function (item) { return { id: item.id, status: item.status, memo: item.memo || '', savedAt: item.savedAt }; })
    };
  }
  // Q13: merge automatically, add only what is missing, overwrite nothing, report conflicts, and keep
  // the list of what was added so "되돌리기" can take exactly that back out.
  function mergeGuest(c, uid, now) {
    var todo = pending(uid);
    var result = { events: 0, places: 0, eventIds: [], placeIds: [], conflicts: [], at: (now || new Date()).toISOString() };
    if (!todo.events.length && !todo.places.length) { markMerged(uid, result.at); return Promise.resolve(result); }
    var before = { events: {}, places: {} };
    return Promise.all([
      c.from('saved_events').select('event_id').limit(MAX_SAVED),
      todo.places.length ? c.from('saved_places').select('place_id').limit(1000) : Promise.resolve({ data: [] })
    ]).then(function (res) {
      if (res[0].error) throw res[0].error;
      (res[0].data || []).forEach(function (row) { before.events[row.event_id] = true; });
      (res[1].data || []).forEach(function (row) { before.places[row.place_id] = true; });
      return todo.events.length ? c.rpc('merge_saved_events', { p_items: todo.events }) : { data: 0 };
    }).then(function (res) {
      if (res.error) throw res.error;
      result.events = Number(res.data) || 0;
      result.eventIds = todo.events.map(function (i) { return i.id; }).filter(function (id) { return !before.events[id]; });
      return todo.places.length ? c.rpc('merge_saved_places', { p_items: todo.places }) : { data: { added: 0, conflicts: [] } };
    }).then(function (res) {
      if (res.error) throw res.error;
      result.places = Number(res.data && res.data.added) || 0;
      result.conflicts = (res.data && Array.isArray(res.data.conflicts)) ? res.data.conflicts : [];
      result.placeIds = todo.places.map(function (i) { return i.id; }).filter(function (id) { return !before.places[id]; });
      markMerged(uid, result.at);
      return result;
    });
  }
  function undoMerge(c, result) {
    var jobs = [];
    if (result && result.eventIds && result.eventIds.length) jobs.push(c.from('saved_events').delete().in('event_id', result.eventIds));
    if (result && result.placeIds && result.placeIds.length) jobs.push(c.from('saved_places').delete().in('place_id', result.placeIds));
    return Promise.all(jobs).then(function (res) {
      res.forEach(function (r) { if (r && r.error) throw r.error; });
    });
  }

  // ---- the account's saved free-food list --------------------------------------------------------
  // Same synchronous interface as BabdodukLive.createStore, over an in-memory copy; every change goes
  // to the server and is undone in memory (with onChange('failed')) when the server refuses it.
  function createRemoteStore(c, uid, onChange) {
    var items = [];
    var ready = false;
    var L = global.BabdodukLive;
    function emit(kind) { if (typeof onChange === 'function') onChange(kind); }
    function find(id) {
      for (var i = 0; i < items.length; i++) if (items[i].id === id) return items[i];
      return null;
    }
    function seenOf(ev) { return L && L.seenOf ? L.seenOf(ev) : { title: ev.title || '', startAt: ev.startAt || null, endAt: ev.endAt || null, place: '' }; }
    function settle(promise, undo) {
      promise.then(function (res) {
        if (res && res.error) throw res.error;
        emit('saved');
      }).catch(function () { undo(); emit('failed'); });
      return true;
    }
    var store = {
      remote: true,
      list: function () { return items.slice(); },
      has: function (id) { return !!find(id); },
      get: find,
      writable: function () { return ready; },
      recovered: function () { return false; },
      add: function (ev, now) {
        if (!ready || !ev || !EVENT_ID.test(String(ev.id || '')) || find(ev.id) || items.length >= MAX_SAVED) return false;
        var item = { id: ev.id, savedAt: (now || new Date()).toISOString(), seen: seenOf(ev) };
        items.unshift(item);
        return settle(c.from('saved_events').insert({ user_id: uid, event_id: item.id, saved_at: item.savedAt, seen: item.seen }),
          function () { items = items.filter(function (x) { return x !== item; }); });
      },
      remove: function (id) {
        var item = find(id);
        if (!ready || !item) return false;
        var at = items.indexOf(item);
        items.splice(at, 1);
        return settle(c.from('saved_events').delete().eq('event_id', id),
          function () { if (!find(id)) items.splice(Math.min(at, items.length), 0, item); });
      },
      acknowledge: function (ev) {
        var item = find(ev && ev.id);
        if (!ready || !item) return false;
        var was = item.seen;
        item.seen = seenOf(ev);
        return settle(c.from('saved_events').update({ seen: item.seen }).eq('event_id', item.id),
          function () { item.seen = was; });
      },
      reload: function () {
        return c.from('saved_events').select('event_id,saved_at,seen').order('saved_at', { ascending: false }).limit(MAX_SAVED)
          .then(function (res) {
            if (res.error) throw res.error;
            items = (res.data || []).filter(function (row) { return EVENT_ID.test(String(row.event_id || '')); })
              .map(function (row) { return { id: row.event_id, savedAt: row.saved_at, seen: row.seen || {} }; });
            ready = true;
            return store;
          });
      }
    };
    return store;
  }

  // On ggongbab.html: for someone signed in on this browser, swap the guest store for the account's
  // and say which one is showing. Guests never load anything.
  function attachSavedStore(onReady, onChange) {
    if (!available() || !hasSession()) return false;
    var c;
    client().then(function (cl) { c = cl; return currentUser(); }).then(function (user) {
      if (!user) return null;
      return mergeGuest(c, user.id).catch(function () { return null; }).then(function () {
        return createRemoteStore(c, user.id, onChange).reload();
      });
    }).then(function (store) { if (store) onReady(store); }).catch(function () { onReady(null, 'failed'); });
    return true;
  }

  // ---- account data ------------------------------------------------------------------------------
  function loadProfile(c, uid) {
    return c.from('profiles').select('display_name').eq('user_id', uid).maybeSingle().then(function (res) {
      if (res.error) throw res.error;
      return res.data || null;
    });
  }
  function saveProfile(c, uid, name) {
    var clean = String(name || '').trim().slice(0, 40);
    return c.from('profiles').upsert({ user_id: uid, display_name: clean || null }, { onConflict: 'user_id' }).then(function (res) {
      if (res.error) throw res.error;
      return clean;
    });
  }
  function placeCounts(c) {
    return c.from('saved_places').select('status').limit(1000).then(function (res) {
      if (res.error) throw res.error;
      var out = { want: 0, been: 0, again: 0 };
      (res.data || []).forEach(function (row) { if (out[row.status] !== undefined) out[row.status] += 1; });
      return out;
    });
  }
  // The private calendar subscription token (supabase/migrations/013_calendar_feed.sql); renew replaces it.
  function calendarFeed(c, renew) {
    return c.rpc('my_calendar_feed', { p_new: !!renew }).then(function (res) {
      if (res.error) throw res.error;
      return typeof res.data === 'string' && /^[A-Za-z0-9_-]{43}$/.test(res.data) ? res.data : '';
    });
  }
  function clearSavedData(c) {
    return c.rpc('delete_my_saved_data').then(function (res) { if (res.error) throw res.error; });
  }
  function clearBrowserCopy() {
    var s = storage();
    if (!s) return;
    [SAVED_KEY, PLACES_KEY, MERGE_KEY].forEach(function (key) { try { s.removeItem(key); } catch (e) { /* nothing to do */ } });
  }
  function deleteAccount(c) {
    return c.rpc('delete_my_account').then(function (res) {
      if (res.error) throw res.error;
      return c.auth.signOut({ scope: 'local' }).catch(function () { return null; });
    }).then(function () {
      var s = storage();
      try { if (s && tokenKey()) s.removeItem(tokenKey()); } catch (e) { /* signed out already */ }
    });
  }

  global.BabdodukAccount = {
    PROVIDERS: PROVIDERS,
    MERGE_KEY: MERGE_KEY,
    available: available,
    hasSession: hasSession,
    client: client,
    currentUser: currentUser,
    signIn: signIn,
    linkProvider: linkProvider,
    signOut: signOut,
    providersOf: providersOf,
    providerName: providerName,
    signedInRecently: signedInRecently,
    pending: pending,
    lastMerged: lastMerged,
    mergeGuest: mergeGuest,
    undoMerge: undoMerge,
    createRemoteStore: createRemoteStore,
    attachSavedStore: attachSavedStore,
    loadProfile: loadProfile,
    saveProfile: saveProfile,
    placeCounts: placeCounts,
    calendarFeed: calendarFeed,
    clearSavedData: clearSavedData,
    clearBrowserCopy: clearBrowserCopy,
    deleteAccount: deleteAccount
  };
})(window);
