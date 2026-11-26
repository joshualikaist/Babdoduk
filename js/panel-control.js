(function () {
  'use strict';
  var root = document.getElementById('pnControl');
  if (!root) return;
  var button = document.getElementById('pnStart');
  var message = document.getElementById('pnControlStatus');
  var login = document.getElementById('pnControlLogin');
  var lab = location.hostname === 'babdoduk-lab.vercel.app';
  var state = null, failed = false, sending = false, pending = null, pendingAt = 0, notice = '';

  function t(key, vars) {
    var lang = document.documentElement.lang === 'en' ? 'en' : 'ko';
    var text = ((window.BABDODUK_STR || {})[lang] || {})['panel.control.' + key] || key;
    Object.keys(vars || {}).forEach(function (k) { text = text.split('{' + k + '}').join(String(vars[k])); });
    return text;
  }
  function paint() {
    var code = state && state.state;
    var busy = ['starting', 'running', 'publishing'].indexOf(code) !== -1;
    var limited = code === 'rate_limit' && Date.parse(state.retryAt) > Date.now();
    button.disabled = !lab || !state || failed || sending || !!pending || busy || limited;
    button.textContent = t(sending || pending ? 'requesting' : busy ? 'busy' : 'start');
    var key = !lab ? 'labOnly' : failed ? 'offline' : !state ? 'loading' : notice || (pending ? 'requested' :
      limited ? 'limited' : ['starting', 'running', 'publishing', 'complete', 'failed', 'auth_failed'].indexOf(code) !== -1 ? code : 'ready');
    var time = limited ? new Date(state.retryAt).toLocaleTimeString(document.documentElement.lang === 'en' ? 'en-GB' : 'ko-KR', {
      timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit'
    }) : '';
    var text = t(key, { time: time });
    if (message.textContent !== text) message.textContent = text;
    var account = window.BabdodukAccount;
    login.hidden = !lab || (notice !== 'signin' && account && account.hasSession());
    root.setAttribute('data-state', failed ? 'offline' : pending ? 'requested' : code || 'loading');
  }
  function poll() {
    fetch('/api/panel-control', { cache: 'no-store', signal: AbortSignal.timeout(8000) }).then(function (res) {
      if (!res.ok) throw new Error('offline');
      return res.json();
    }).then(function (body) {
      if (!body || typeof body.state !== 'string' || !Number.isFinite(Date.parse(body.updatedAt))) throw new Error('invalid');
      var previous = state;
      state = body; failed = false;
      if (notice === 'offline') notice = '';
      if (body.state === 'complete' && previous &&
          (previous.state !== 'complete' || previous.requestId !== body.requestId)) {
        document.dispatchEvent(new CustomEvent('babdoduk-panel-complete'));
      }
      if (pending && body.requestId === pending) { pending = null; notice = ''; }
      else if (pending && Date.now() - pendingAt > 30000) { pending = null; notice = 'unconfirmed'; }
    }).catch(function () { failed = true; }).finally(function () {
      paint(); setTimeout(poll, 5000);
    });
  }
  button.addEventListener('click', function () {
    if (button.disabled) return;
    notice = ''; sending = true; paint();
    var account = window.BabdodukAccount;
    if (!account || !account.hasSession()) { notice = 'signin'; sending = false; paint(); return; }
    var requestId = crypto.randomUUID();
    account.client().then(function (client) { return client.auth.getSession(); }).then(function (res) {
      var session = res && res.data && res.data.session;
      if (!session || !session.access_token) { notice = 'signin'; return null; }
      return fetch('/api/panel-control', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.access_token },
        body: JSON.stringify({ action: 'start', requestId: requestId }), cache: 'no-store', signal: AbortSignal.timeout(8000)
      });
    }).then(function (res) {
      if (!res) return;
      return res.json().then(function (body) {
        if (res.status === 202) { pending = requestId; pendingAt = Date.now(); notice = ''; }
        else if (res.status === 401) notice = 'signin';
        else if (res.status === 403) notice = 'operatorOnly';
        else if (res.status === 409 || res.status === 429) { state = body; notice = ''; }
        else notice = 'offline';
      });
    }).catch(function () { notice = 'offline'; }).finally(function () { sending = false; paint(); });
  });
  document.addEventListener('babdoduk-lang', paint);
  paint();
  if (lab) poll();
})();
