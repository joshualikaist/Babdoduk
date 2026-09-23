/* Read-only public feed controller. Rendering never owns connections. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BabdodukPublicFeed = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  var TABLE = 'ggongbab_public_events';
  var COLUMNS = 'id,title,summary,start_at,end_at,date_text,time_text,location_name,building,room,food_provided,food_type,food_description,organizer,eligibility,registration_required,registration_deadline,registration_url,source_types,confidence,content_revision,updated_at';
  var NAMES = Object.freeze({ dooray: 'Dooray', dooray_mailbox: 'Dooray 메일함',
    kaist_public: 'KAIST 공지', manual: 'Manual', portal: 'KAIST Portal' });
  var SDK_URL = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.116.0/dist/umd/supabase.js';
  var sdkPromise;

  function kst(value) {
    if (!value) return null;
    var date = new Date(value);
    if (!Number.isFinite(date.getTime())) return null;
    return new Date(date.getTime() + 9 * 3600000).toISOString().slice(0, 19) + '+09:00';
  }
  function mapRow(row) {
    return {
      id: row.id, title: row.title, summary: row.summary,
      startAt: kst(row.start_at), endAt: kst(row.end_at),
      dateText: row.date_text, timeText: row.time_text,
      location: { name: row.location_name, building: row.building, room: row.room },
      food: { provided: row.food_provided, type: row.food_type, description: row.food_description },
      organizer: row.organizer, eligibility: row.eligibility,
      registration: { required: row.registration_required, deadline: kst(row.registration_deadline), url: row.registration_url },
      confidence: row.confidence,
      sources: (row.source_types || []).filter(function (kind) {
        return Object.prototype.hasOwnProperty.call(NAMES, kind);
      }).map(function (kind) { return { type: kind, name: NAMES[kind] }; })
    };
  }
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
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      var timeout = setTimeout(failed, 8000);
      function failed() {
        clearTimeout(timeout); script.remove(); sdkPromise = null;
        reject(new Error('public client unavailable'));
      }
      script.src = SDK_URL;
      script.integrity = 'sha384-iLddHTLokph6Omwoyid4XKxHaWa6w41BnoEj0q5oOrzmYPpHIKt1wyjReA7s//pP';
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
    return sdkPromise;
  }
  async function browserClient(config) {
    if (typeof WebSocket !== 'function' || typeof AbortController !== 'function') throw new Error('public client unavailable');
    var sdk = await loadSdk();
    return sdk.createClient(config.url, config.key, {
      db: { schema: 'public' },
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      realtime: { timeout: 8000 }
    });
  }
  function retryDelay(attempt, random) {
    return Math.min(30000, 1000 * Math.pow(2, Math.min(attempt, 5))) * (0.8 + 0.2 * random());
  }

  function create(options) {
    var config = publicConfig(options.config);
    var makeClient = options.makeClient || browserClient;
    var schedule = options.setTimeout || setTimeout;
    var cancel = options.clearTimeout || clearTimeout;
    var random = options.random || Math.random;
    var state = 'loading', collection = new Map(), generatedAt = null;
    var hasData = false, dbData = false, active = false, epoch = 0, attempt = 0;
    var client = null, channel = null, cleanup = Promise.resolve();
    var retryTimer, deadlineTimer, refreshTimer, abort, snapshotAbort, snapshotTimer;
    var reconciling = false, dirty = false;

    function current(token) { return active && token === epoch; }
    function emit() {
      options.onData({ events: Array.from(collection.values()).map(function (item) { return item.event; }),
        generatedAt: generatedAt }, state);
    }
    function clearTimers() {
      cancel(retryTimer); cancel(deadlineTimer); cancel(refreshTimer);
      cancel(snapshotTimer);
      if (snapshotAbort) snapshotAbort.abort();
    }
    function detach() {
      if (abort) abort.abort();
      abort = null;
      var old = channel, owner = client;
      channel = null;
      if (old) cleanup = cleanup.then(async function () {
        try {
          var removed = await owner.removeChannel(old);
          // A failed removal must not reuse a client retaining an old channel.
          if (removed === 'error' || removed === 'timed out') client = null;
        } catch (e) { client = null; }
        finally { owner.realtime.disconnect(); }
      }).catch(function () { /* Fixed boundary: never log transport objects. */ });
      return cleanup;
    }
    async function fallback(token) {
      var timer;
      try {
        snapshotAbort = typeof AbortController === 'function' ? new AbortController() : null;
        var controller = snapshotAbort;
        var timeout = new Promise(function (resolve, reject) {
          timer = snapshotTimer = schedule(function () {
            if (controller) controller.abort();
            reject(new Error('public snapshot unavailable'));
          }, 8000);
        });
        var data = await Promise.race([options.loadSnapshot(controller ? controller.signal : undefined), timeout]);
        if (!current(token)) return;
        if (!data || !Array.isArray(data.events)) throw new Error('public snapshot unavailable');
        // An outage must never replace a successfully selected DB feed with an
        // older snapshot (including resurrecting deleted rows). Keep it visible.
        if (dbData) return;
        collection = new Map(data.events.map(function (event) { return [event.id, { event: event }]; }));
        generatedAt = data.generatedAt || null;
        hasData = true; state = 'snapshot-fallback'; emit();
      } catch (e) {
        if (current(token) && !hasData && options.onError) options.onError();
      } finally { cancel(timer); }
    }
    function fail(token) {
      if (!current(token)) return;
      var next = ++epoch;
      clearTimers(); detach();
      reconciling = false;
      state = hasData ? (dbData ? 'reconnecting' : 'snapshot-fallback') : 'loading';
      fallback(next);
      if (config) retryTimer = schedule(connect, retryDelay(attempt++, random));
    }
    function entry(row) {
      if (!row || typeof row.id !== 'string' || !row.id || typeof row.content_revision !== 'string' || !row.content_revision) throw new Error('public row unavailable');
      return { event: mapRow(row), revision: row.content_revision };
    }
    function change(payload, token) {
      if (!current(token)) return;
      if (reconciling) { dirty = true; return; }
      try {
        if (payload.eventType === 'DELETE') {
          if (payload.old && collection.delete(payload.old.id)) emit();
        } else if (payload.eventType === 'INSERT' || payload.eventType === 'UPDATE') {
          var item = entry(payload.new), old = collection.get(item.event.id);
          if (old && old.revision === item.revision) return;
          collection.set(item.event.id, item); emit();
        }
      } catch (e) { fail(token); }
    }
    async function selectAll(token) {
      var rows = [], offset = 0;
      // Continue to an EMPTY page, not a short page: server limits may be lower
      // than our requested range. Deadline bounds pathological/huge responses.
      while (current(token)) {
        var response = await client.from(TABLE).select(COLUMNS)
          .order('start_at', { ascending: true }).order('id', { ascending: true })
          .range(offset, offset + 499).abortSignal(abort.signal);
        if (response.error || !Array.isArray(response.data)) throw new Error('public select unavailable');
        if (!response.data.length) return rows;
        rows = rows.concat(response.data); offset += response.data.length;
      }
      throw new Error('public select cancelled');
    }
    async function reconcile(token) {
      if (!current(token) || reconciling) return;
      reconciling = true;
      cancel(refreshTimer);
      cancel(deadlineTimer);
      deadlineTimer = schedule(function () { fail(token); }, 12000);
      abort = new AbortController();
      try {
        // Changes during SELECT invalidate that result. Re-select rather than
        // replay buffered older rows over a newer snapshot. No partial publish.
        for (var round = 0; round < 5; round++) {
          dirty = false;
          var rows = await selectAll(token);
          if (!current(token)) return;
          if (dirty) continue;
          var replacement = new Map();
          rows.forEach(function (row) { replacement.set(row.id, entry(row)); });
          var changed = !dbData || replacement.size !== collection.size;
          replacement.forEach(function (item, id) {
            if (!collection.has(id) || collection.get(id).revision !== item.revision) changed = true;
          });
          collection = replacement; generatedAt = null; hasData = true; dbData = true;
          state = 'db-live'; reconciling = false; attempt = 0;
          cancel(deadlineTimer);
          if (changed) emit();
          refreshTimer = schedule(function () { reconcile(token); }, 60000);
          return;
        }
        throw new Error('public feed busy');
      } catch (e) { fail(token); }
    }
    async function connect() {
      if (!active) return;
      var token = ++epoch;
      clearTimers();
      state = hasData ? 'reconnecting' : 'loading';
      reconciling = false;
      await detach();
      if (!current(token)) return;
      if (!config) { await fallback(token); return; }
      deadlineTimer = schedule(function () { fail(token); }, 12000);
      try {
        if (!client) {
          var created = await makeClient(config);
          if (!current(token)) { created.realtime.disconnect(); return; }
          client = created;
        }
        // Fence changes even before SUBSCRIBED. Only its authoritative SELECT
        // may replace the visible snapshot/cached feed.
        reconciling = true;
        channel = client.channel('ggongbab-public-feed');
        channel.on('postgres_changes', { event: '*', schema: 'public', table: TABLE },
          function (payload) { change(payload, token); });
        var confirmed = false;
        channel.subscribe(function (status) {
          if (!current(token)) return;
          if (status === 'SUBSCRIBED' && !confirmed) {
            confirmed = true; reconciling = false; reconcile(token);
          } else if (status === 'SUBSCRIBED') {
            reconcile(token);
          } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') fail(token);
        });
      } catch (e) { fail(token); }
    }
    function start() { if (!active) { active = true; connect(); } }
    function stop() { active = false; ++epoch; clearTimers(); return detach(); }
    return { start: start, stop: stop,
      retry: function () { if (active) connect(); else start(); },
      status: function () { return state; } };
  }
  return { create: create, mapRow: mapRow, columns: COLUMNS, publicConfig: publicConfig, retryDelay: retryDelay };
});
