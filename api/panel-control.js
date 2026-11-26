'use strict';

const fs = require('fs');
const path = require('path');
const LAB = 'babdoduk-lab.vercel.app';
const STATES = new Set(['idle', 'starting', 'running', 'publishing', 'complete', 'failed', 'auth_failed', 'rate_limit']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function project(body) {
  if (!body || !STATES.has(body.state) || !Number.isFinite(Date.parse(body.updatedAt))) throw new Error('invalid');
  const result = { updatedAt: body.updatedAt, state: body.state };
  if (UUID.test(body.requestId)) result.requestId = body.requestId;
  if (body.state === 'rate_limit' && Number.isFinite(Date.parse(body.retryAt))) result.retryAt = body.retryAt;
  return result;
}

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(body));
}

async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex, nofollow');
  const headers = req.headers || {};
  if (String(headers.host || '').toLowerCase() !== LAB) { res.statusCode = 404; res.end(); return; }
  if (!['GET', 'POST'].includes(req.method)) {
    res.setHeader('Allow', 'GET, POST'); res.statusCode = 405; res.end(); return;
  }
  try {
    const config = fs.readFileSync(path.join(__dirname, '../js/ggongbab-public-config.js'), 'utf8');
    const base = (config.match(/SUPABASE_URL:\s*'([^']+)'/) || [])[1];
    const key = (config.match(/SUPABASE_PUBLISHABLE_KEY:\s*'([^']+)'/) || [])[1];
    if (!base || !key) throw new Error('config');
    const getControl = async () => {
      const response = await fetch(base + '/storage/v1/object/public/panel-live/control.json?v=' + Date.now(), {
        cache: 'no-store', signal: AbortSignal.timeout(3000)
      });
      if (!response.ok) throw new Error('unavailable');
      const raw = await response.json();
      const status = project(raw);
      if (Math.abs(Date.now() - Date.parse(status.updatedAt)) > 30000) throw new Error('offline');
      return { raw, status };
    };
    if (req.method === 'GET') {
      const { status } = await getControl();
      send(res, 200, status); return;
    }
    if (headers.origin !== 'https://' + LAB || !/^application\/json(?:;|$)/i.test(headers['content-type'] || '')) {
      send(res, 403, { code: 'forbidden' }); return;
    }
    const token = (String(headers.authorization || '').match(/^Bearer ([A-Za-z0-9_.-]{32,8192})$/) || [])[1];
    if (!token) { send(res, 401, { code: 'signin' }); return; }
    let input = req.body;
    if (typeof input === 'string') {
      if (input.length > 200) { send(res, 400, { code: 'invalid' }); return; }
      try { input = JSON.parse(input); } catch (err) { input = null; }
    }
    if (!input || Object.keys(input).sort().join(',') !== 'action,requestId'
        || input.action !== 'start' || !UUID.test(input.requestId)) {
      send(res, 400, { code: 'invalid' }); return;
    }
    // getUser validates the JWT with Auth. User-editable metadata never grants access.
    const auth = await fetch(base + '/auth/v1/user', {
      headers: { apikey: key, Authorization: 'Bearer ' + token }, cache: 'no-store', signal: AbortSignal.timeout(3000)
    });
    if (!auth.ok) { send(res, 401, { code: 'signin' }); return; }
    const user = await auth.json();
    if (!user.id || !user.app_metadata || user.app_metadata.panel_operator !== true) {
      send(res, 403, { code: 'operator_only' }); return;
    }
    const { raw, status } = await getControl();
    if (['starting', 'running', 'publishing'].includes(status.state)) {
      send(res, 409, { code: 'running', ...status }); return;
    }
    if (status.state === 'rate_limit' && Date.parse(status.retryAt) > Date.now()) {
      send(res, 429, { code: 'rate_limit', ...status }); return;
    }
    // This capability can only replace one bounded PRIVATE inbox object. It grants no reads
    // and no execution. The ops worker independently authenticates every uploaded request.
    if (typeof raw.upload !== 'string' || !raw.upload.startsWith('/object/upload/sign/panel-requests/pending.json?token=')) throw new Error('inbox');
    const url = new URL(base + '/storage/v1' + raw.upload);
    if (url.origin !== new URL(base).origin || url.pathname !== '/storage/v1/object/upload/sign/panel-requests/pending.json'
        || !url.searchParams.get('token') || !Number.isFinite(Date.parse(raw.uploadExpiresAt))
        || Date.parse(raw.uploadExpiresAt) <= Date.now()) throw new Error('inbox');
    const upload = await fetch(url.href, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'cache-control': 'max-age=0' },
      body: JSON.stringify({ requestId: input.requestId, createdAt: new Date().toISOString(), accessToken: token }),
      signal: AbortSignal.timeout(3000)
    });
    if (!upload.ok) throw new Error('inbox');
    send(res, 202, { state: 'requested', requestId: input.requestId });
  } catch (err) {
    res.setHeader('Retry-After', '5'); send(res, 503, { code: 'offline' });
  }
}

module.exports = handler;
module.exports.project = project;
