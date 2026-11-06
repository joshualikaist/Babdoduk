'use strict';
const crypto = require('node:crypto');
const { ORIGIN, REPO, QUEUE, RECEIPTS, validateQueue, digest, seal, unseal, encodeQueue, decodeQueue } = require('../lib/editorial.cjs');
const SESSION = '__Host-editorial', OAUTH = '__Host-editorial-oauth';
const cookie = (name, value, age) => `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${age}`;
const forbidden = () => { throw Object.assign(new Error('Access denied'), { status: 403 }); };
async function github(token, path, method = 'GET', body) {
  const response = await fetch('https://api.github.com' + path, {
    method, headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000)
  });
  if (!response.ok) throw Object.assign(new Error(response.status === 409 || response.status === 422 ? 'Changed on server. Reload before saving.' : 'GitHub request failed'), { status: response.status === 404 ? 404 : response.status === 409 || response.status === 422 ? 409 : 502 });
  return response.json();
}
async function read(token, path, ref, fallback) {
  try {
    const file = await github(token, `/repos/${REPO}/contents/${path}?ref=${ref}`);
    return { sha: file.sha, data: JSON.parse(Buffer.from(file.content, 'base64').toString('utf8')) };
  } catch (e) { if (e.status === 404 && fallback) return { sha: null, data: fallback }; throw e; }
}
module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer');
  const json = (status, body) => res.status(status).json(body);
  const redirect = url => { res.statusCode = 302; res.setHeader('Location', url); res.end(); };
  try {
    // Exact production lab host only; previews and the public project cannot serve an admin API.
    if (req.headers.host !== new URL(ORIGIN).host) return json(404, { error: 'Not found' });
    const secret = process.env.EDITORIAL_SESSION_SECRET || '';
    const queueKey = process.env.EDITORIAL_QUEUE_KEY || '';
    const configured = secret.length >= 32 && queueKey.length >= 32 && !!process.env.EDITORIAL_GITHUB_CLIENT_ID && !!process.env.EDITORIAL_GITHUB_CLIENT_SECRET;
    const url = new URL(req.url, ORIGIN), action = url.searchParams.get('action') || 'session';
    if (!['GET', 'POST'].includes(req.method)) return json(405, { error: 'Method not allowed' });
    if (!configured) return json(action === 'session' ? 200 : 503, { configured: false, authenticated: false, error: 'Publishing login is not configured' });
    const cookies = Object.fromEntries((req.headers.cookie || '').split(';').map(s => s.trim().split('=', 2)));
    let session = unseal(cookies[SESSION] || '', secret);
    if (req.method === 'POST' && req.headers.origin !== ORIGIN) forbidden();
    if (action === 'login' && req.method === 'GET') {
      const state = crypto.randomBytes(32).toString('base64url'), verifier = crypto.randomBytes(32).toString('base64url');
      res.setHeader('Set-Cookie', cookie(OAUTH, seal({ state, verifier, exp: Date.now() + 600000 }, secret), 600));
      const params = new URLSearchParams({ client_id: process.env.EDITORIAL_GITHUB_CLIENT_ID,
        redirect_uri: ORIGIN + '/api/editorial?action=callback', state, scope: 'public_repo',
        code_challenge: crypto.createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256' });
      return redirect('https://github.com/login/oauth/authorize?' + params);
    }
    if (action === 'callback' && req.method === 'GET') {
      const pending = unseal(cookies[OAUTH] || '', secret);
      res.setHeader('Set-Cookie', cookie(OAUTH, '', 0));
      if (!pending || pending.state !== url.searchParams.get('state') || !url.searchParams.get('code')) forbidden();
      const tokenResponse = await fetch('https://github.com/login/oauth/access_token', { method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: process.env.EDITORIAL_GITHUB_CLIENT_ID,
          client_secret: process.env.EDITORIAL_GITHUB_CLIENT_SECRET, code: url.searchParams.get('code'),
          redirect_uri: ORIGIN + '/api/editorial?action=callback', code_verifier: pending.verifier }), signal: AbortSignal.timeout(15000) });
      const token = (await tokenResponse.json()).access_token;
      if (!token) forbidden();
      session = { token, csrf: crypto.randomBytes(24).toString('base64url'), exp: Date.now() + 3600000 };
    }
    if (!session) return json(401, { configured: true, authenticated: false });
    // Recheck identity and repository permission on every request, including cookie reuse.
    const [user, repo] = await Promise.all([github(session.token, '/user'), github(session.token, `/repos/${REPO}`)]);
    const allowed = (process.env.EDITORIAL_GITHUB_ADMINS || 'joshualikaist').split(',').map(s => s.trim().toLowerCase());
    if (!allowed.includes(user.login.toLowerCase()) || !repo.permissions?.push) forbidden();
    if (action === 'callback') {
      res.setHeader('Set-Cookie', [cookie(OAUTH, '', 0), cookie(SESSION, seal(session, secret), 3600)]);
      return redirect(ORIGIN + '/lab.html');
    }
    if (req.method === 'POST' && req.headers['x-editorial-csrf'] !== session.csrf) forbidden();
    if (action === 'logout' && req.method === 'POST') { res.setHeader('Set-Cookie', cookie(SESSION, '', 0)); return json(200, { ok: true }); }
    if (action === 'session' && req.method === 'GET') return json(200, { configured: true, authenticated: true, login: user.login, csrf: session.csrf });
    if (action === 'queue' && req.method === 'GET') {
      const [queue, receipts] = await Promise.all([read(session.token, QUEUE, 'lab', { schemaVersion: 1, items: [] }),
        read(session.token, RECEIPTS, 'main', { schemaVersion: 1, items: [] })]);
      return json(200, { queue: decodeQueue(queue.data, queueKey), sha: queue.sha, receipts: receipts.data });
    }
    if (action === 'queue' && req.method === 'POST') {
      let body = req.body;
      if (typeof body === 'string') { if (Buffer.byteLength(body) > 500000) return json(413, { error: 'Too large' }); body = JSON.parse(body); }
      if (!body || Buffer.byteLength(JSON.stringify(body)) > 500000) return json(413, { error: 'Too large' });
      const queue = validateQueue(body.queue);
      // Capture the branch before checking receipts. A publish/cancel race must reject the ref
      // update, even when the queue blob itself did not change in the publication commit.
      const base = await github(session.token, `/repos/${REPO}/git/ref/heads/lab`);
      const baseSha = base.object.sha;
      const receipts = await read(session.token, RECEIPTS, 'main', { schemaVersion: 1, items: [] });
      for (const receipt of receipts.data.items) {
        const entry = queue.items.find(i => i.id === receipt.id);
        if (entry && digest(entry) !== receipt.digest) return json(409, { error: 'Already published. Create a new post instead.' });
      }
      const current = await read(session.token, QUEUE, baseSha, { schemaVersion: 1, items: [] });
      current.data = decodeQueue(current.data, queueKey);
      if (body.sha !== current.sha) return json(409, { error: 'Changed on server. Reload before saving.' });
      for (const entry of queue.items) {
        const old = current.data.items.find(i => i.id === entry.id);
        if (entry.status === 'scheduled' && digest(old || {}) !== digest(entry) && Date.parse(entry.publishAt) <= Date.now())
          return json(400, { error: 'Choose a future publication time' });
      }
      const baseCommit = await github(session.token, `/repos/${REPO}/git/commits/${baseSha}`);
      const content = JSON.stringify(encodeQueue(queue, queueKey), null, 2) + '\n';
      const blob = await github(session.token, `/repos/${REPO}/git/blobs`, 'POST', { content: Buffer.from(content).toString('base64'), encoding: 'base64' });
      const tree = await github(session.token, `/repos/${REPO}/git/trees`, 'POST', {
        base_tree: baseCommit.tree.sha, tree: [{ path: QUEUE, mode: '100644', type: 'blob', sha: blob.sha }] });
      const commit = await github(session.token, `/repos/${REPO}/git/commits`, 'POST', {
        message: 'content(editorial): update publication queue\n\nAgent: Editorial admin', tree: tree.sha, parents: [baseSha] });
      await github(session.token, `/repos/${REPO}/git/refs/heads/lab`, 'PATCH', { sha: commit.sha, force: false });
      return json(200, { sha: blob.sha, commit: commit.sha });
    }
    return json(404, { error: 'Not found' });
  } catch (e) {
    // Never log access tokens, cookies, request bodies or OAuth codes.
    return json(e.status || 500, { error: e.status ? e.message : 'Publishing request failed' });
  }
};
