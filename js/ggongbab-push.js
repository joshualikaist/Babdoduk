/* 별 누른 꽁밥 30분 전 알림 (owner 2026-11-12; docs/PUSH_ALERTS.md), the browser half.
 *
 * window.BabdodukPush turns web push on or off for this browser and keeps the server's copy of the starred
 * list current. On iPhone, web push works only in the site opened from the home screen (iOS 16.4+); there
 * the first star asks once. What the server keeps is the browser's push address, the starred listing ids,
 * the language and the site (supabase/migrations/014_push_alerts.sql); no account or name. The ops
 * computer sends the alert (scripts/push/send.js) from the newest public time of each listing.
 *
 * Off unless the public push key below is set and the page runs on one of HOSTS, so production never
 * offers it before the feature is promoted. No service worker is installed until someone turns it on.
 * Needs js/ggongbab-public-config.js (the public URL and publishable key).
 */
(function (global) {
  'use strict';

  // The public half of the push key pair (scripts/push/keygen.js prints it). Public by design.
  var VAPID_PUBLIC_KEY = 'BEfX71XgdO8TANAExCRNO-a4XUUTlSnN3TwuOOvUxepyCwajiYW-1JUoobGNies2RRsRBjUTvNj1H4IoDEtQc38';
  var HOSTS = ['babdoduk-lab.vercel.app'];
  var EVENT_ID = /^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$/;
  var SYNC_KEY = 'babdoduk-push-synced';   // what was last sent, so an unchanged list is not sent again
  var ASKED_KEY = 'babdoduk-push-asked';   // the one-time question after a star was answered
  var MAX = 300;

  function nav() { return global.navigator || {}; }
  function store() { try { return global.localStorage; } catch (e) { return null; } }
  function read(key) { var s = store(); try { return s ? s.getItem(key) : null; } catch (e) { return null; } }
  function write(key, value) { var s = store(); try { if (s) s.setItem(key, value); return !!s; } catch (e) { return false; } }

  function publicConfig() {
    var config = global.BABDODUK_PUBLIC_FEED_CONFIG || {};
    try {
      var url = new URL(config.SUPABASE_URL);
      var key = config.SUPABASE_PUBLISHABLE_KEY;
      if (url.protocol !== 'https:' || url.pathname !== '/' || url.search || url.hash) return null;
      if (typeof key !== 'string' || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) return null;
      return { url: url.origin, key: key };
    } catch (e) { return null; }
  }
  function configured() {
    return /^[A-Za-z0-9_-]{87}$/.test(VAPID_PUBLIC_KEY) && HOSTS.indexOf(global.location.hostname) !== -1 && !!publicConfig();
  }
  function supported() {
    var n = nav();
    return !!(n.serviceWorker && global.PushManager && global.Notification && global.isSecureContext !== false);
  }
  // iPadOS says Macintosh; a touch screen tells it apart.
  function isIos() {
    var ua = nav().userAgent || '';
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && nav().maxTouchPoints > 1);
  }
  function standalone() {
    if (nav().standalone === true) return true;
    try { return !!(global.matchMedia && global.matchMedia('(display-mode: standalone)').matches); } catch (e) { return false; }
  }

  // Someone signed in on this browser: their list is the account's, which ggongbab.html and my.html send.
  // The home page holds only this browser's guest list, so it leaves the alert list to those pages.
  function signedIn() {
    var s = store();
    try {
      for (var i = 0; s && i < s.length; i++) if (/^sb-[a-z0-9]+-auth-token$/.test(s.key(i) || '')) return true;
    } catch (e) { return false; }
    return false;
  }
  function subscription() {
    return nav().serviceWorker.getRegistration('/').then(function (reg) { return reg ? reg.pushManager.getSubscription() : null; });
  }
  // Resolves 'hidden' (not offered here) | 'home' (iPhone: open the site from the home screen first) |
  // 'unsupported' | 'denied' | 'off' | 'on'.
  function status() {
    if (!configured()) return Promise.resolve('hidden');
    if (!supported()) return Promise.resolve(isIos() && !standalone() ? 'home' : 'unsupported');
    if (global.Notification.permission === 'denied') return Promise.resolve('denied');
    return subscription().then(function (sub) { return sub ? 'on' : 'off'; }, function () { return 'off'; });
  }
  // The one-time question after a star: only where a yes can work right away and nobody answered before.
  function shouldAsk() {
    return configured() && supported() && global.Notification.permission === 'default' && !read(ASKED_KEY) && !!store();
  }

  function cleanIds(ids) {
    var seen = {};
    return (ids || []).filter(function (id) {
      if (typeof id !== 'string' || !EVENT_ID.test(id) || seen[id]) return false;
      seen[id] = true;
      return true;
    }).slice(0, MAX);
  }
  function keyBytes(text) {
    var b64 = text.replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    var raw = global.atob(b64);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function rpc(name, body) {
    var c = publicConfig();
    return global.fetch(c.url + '/rest/v1/rpc/' + name, {
      method: 'POST',
      headers: { apikey: c.key, Authorization: 'Bearer ' + c.key, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (res) { if (!res.ok) throw new Error('push ' + res.status); return true; });
  }
  function kstDay() { return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10); }
  // The list is sent again when it, the language or the address changes, and once a day at most otherwise.
  function signature(sub, ids, lang) {
    var text = sub.endpoint + '|' + lang + '|' + kstDay() + '|' + ids.slice().sort().join(',');
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h.toString(36);
  }
  function save(sub, ids, lang) {
    var json = sub.toJSON ? sub.toJSON() : {};
    var keys = json.keys || {};
    var list = cleanIds(ids);
    lang = lang === 'en' ? 'en' : 'ko';
    return rpc('push_device_save', {
      p_endpoint: json.endpoint || sub.endpoint, p_p256dh: keys.p256dh, p_auth: keys.auth,
      p_events: list, p_lang: lang, p_site: global.location.origin
    }).then(function () { write(SYNC_KEY, signature(sub, list, lang)); return true; });
  }

  // Must start inside the click that asked for it: iPhone shows the permission question only then.
  // Resolves 'on' | 'denied' | 'failed'.
  function enable(ids, lang) {
    if (!configured() || !supported()) return Promise.resolve('failed');
    write(ASKED_KEY, '1');
    var asking;
    try { asking = global.Notification.requestPermission(); } catch (e) { return Promise.resolve('failed'); }
    return Promise.resolve(asking).then(function (permission) {
      permission = permission || global.Notification.permission;
      if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'failed';
      return nav().serviceWorker.register('/sw.js', { scope: '/' }).then(function () {
        return nav().serviceWorker.ready;
      }).then(function (reg) {
        return reg.pushManager.getSubscription().then(function (sub) {
          return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(VAPID_PUBLIC_KEY) });
        });
      }).then(function (sub) {
        // A browser subscribed but unknown to the server would stay silent: undo it, so "on" is never a lie.
        return save(sub, ids, lang).then(function () { return 'on'; }, function () {
          return sub.unsubscribe().then(function () { return 'failed'; }, function () { return 'failed'; });
        });
      });
    }).catch(function () { return 'failed'; });
  }
  // Resolves 'off' | 'failed'. The browser's own subscription goes first: without it nothing can arrive,
  // even if the server's row is removed later (the sender forgets a gone address by itself).
  function disable() {
    if (!supported()) return Promise.resolve('off');
    return subscription().then(function (sub) {
      if (!sub) return 'off';
      var endpoint = sub.endpoint;
      return sub.unsubscribe().then(function () {
        write(SYNC_KEY, '');
        return rpc('push_device_remove', { p_endpoint: endpoint }).catch(function () { return false; });
      }).then(function () { return 'off'; });
    }).catch(function () { return 'failed'; });
  }
  // After the stars change, and once per page load: send the list if alerts are on here and it changed.
  var pending = null;
  function sync(ids, lang) {
    if (!configured() || !supported()) return Promise.resolve(false);
    lang = lang === 'en' ? 'en' : 'ko';
    return subscription().then(function (sub) {
      if (!sub) return false;
      var list = cleanIds(ids);
      if (read(SYNC_KEY) === signature(sub, list, lang)) return false;
      return save(sub, list, lang);
    }).catch(function () { return false; });
  }
  function changed(ids, lang) {
    clearTimeout(pending);
    pending = setTimeout(function () { sync(ids, lang); }, 500);
  }

  // The one-time question, in the same small bottom panel as the calendar question (css/site.css .starcal).
  // `text` holds the page's strings (title, body, yes, no, later). `answer(choice)` runs inside the click and
  // gets true, false, or null (Escape: ask again next time).
  function ask(text, answer) {
    var doc = global.document;
    var old = doc.getElementById('pushAsk');
    if (old) old.remove();
    var box = doc.createElement('div');
    box.id = 'pushAsk';
    box.className = 'starcal';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-labelledby', 'pushAskTitle');
    box.setAttribute('aria-describedby', 'pushAskBody');
    box.innerHTML = '<p class="starcal-title" id="pushAskTitle"></p><p class="starcal-body" id="pushAskBody"></p>' +
      '<div class="starcal-actions"><button type="button" class="starcal-yes" data-push-ask="yes"></button>' +
      '<button type="button" class="starcal-no" data-push-ask="no"></button></div><p class="starcal-later"></p>';
    box.querySelector('.starcal-title').textContent = text.title;
    box.querySelector('.starcal-body').textContent = text.body;
    box.querySelector('.starcal-yes').textContent = text.yes;
    box.querySelector('.starcal-no').textContent = text.no;
    box.querySelector('.starcal-later').textContent = text.later;
    function close(choice) {
      box.remove();
      doc.removeEventListener('keydown', onKey, true);
      if (choice !== null) write(ASKED_KEY, '1');
      answer(choice);
    }
    function onKey(e) { if (e.key === 'Escape' && box.isConnected) { e.preventDefault(); close(null); } }
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-push-ask]');
      if (b) close(b.getAttribute('data-push-ask') === 'yes');
    });
    doc.addEventListener('keydown', onKey, true);
    doc.body.appendChild(box);
    box.querySelector('.starcal-yes').focus({ preventScroll: true });
    return box;
  }

  global.BabdodukPush = {
    status: status,
    shouldAsk: shouldAsk,
    standalone: standalone,
    signedIn: signedIn,
    enable: enable,
    disable: disable,
    sync: sync,
    changed: changed,
    ask: ask,
    ASKED_KEY: ASKED_KEY,
    SYNC_KEY: SYNC_KEY
  };
})(window);
