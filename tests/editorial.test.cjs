'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { validateQueue, seal, unseal, digest, QUEUE, RECEIPTS, encodeQueue, decodeQueue } = require('../lib/editorial.cjs');
const handler = require('../api/editorial.js');
const secret = 'synthetic-secret-for-tests-at-least-32-chars';
Date.now = () => Date.UTC(2026, 10, 6, 3, 0, 0);
const entry = () => ({ id: 'synthetic-001', kind: 'notice', status: 'scheduled', publishAt: '2099-11-07T13:30:00+09:00',
  content: { date: '2099-11-07', title: { ko: '검사', en: 'Test' }, text: { ko: '내용', en: 'Text' } } });
const queue = () => ({ schemaVersion: 1, items: [entry()] });
const session = () => '__Host-editorial=' + seal({ token: 'synthetic-token', csrf: 'synthetic-csrf', exp: Date.now() + 60000 }, secret);
async function request(action, options = {}) {
  const req = { headers: { host: 'babdoduk-lab.vercel.app', cookie: session(), origin: 'https://babdoduk-lab.vercel.app',
    'x-editorial-csrf': 'synthetic-csrf', ...(options.headers || {}) }, url: '/api/editorial?action=' + action,
    method: options.method || 'GET', body: options.body };
  const res = { statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v; }, status(n) { this.statusCode = n; return this; }, json(value) { this.body = value; }, end() {} };
  await handler(req, res); return res;
}
function mockGithub(overrides = {}) {
  const writes = [];
  global.fetch = async (url, options = {}) => {
    const path = new URL(url).pathname;
    let value;
    if (path === '/user') value = { login: overrides.login || 'joshualikaist' };
    else if (path === '/repos/joshualikaist/Babdoduk') value = { permissions: { push: overrides.push !== false } };
    else if (path.endsWith('/git/ref/heads/lab')) value = { object: { sha: 'lab-base' } };
    else if (path.endsWith('/git/commits/lab-base')) value = { tree: { sha: 'base-tree' } };
    else if (options.method === 'POST' || options.method === 'PATCH') {
      writes.push({ path, body: JSON.parse(options.body) });
      if (options.method === 'PATCH' && overrides.moved) return { ok: false, status: 422 };
      value = path.endsWith('/git/blobs') ? { sha: 'new-blob' } : path.endsWith('/git/trees') ? { sha: 'new-tree' } : { sha: 'lab-commit' };
    }
    else if (path.endsWith(RECEIPTS)) value = { sha: 'receipts', content: Buffer.from(JSON.stringify({ schemaVersion: 1, items: overrides.receipts || [] })).toString('base64') };
    else if (path.endsWith(QUEUE)) value = { sha: 'queue-blob', content: Buffer.from(JSON.stringify({ schemaVersion: 1, items: [] })).toString('base64') };
    else throw new Error('Unexpected synthetic request');
    return { ok: true, json: async () => value };
  };
  return writes;
}
test('queue contract rejects invalid content, timestamps, executable markup and duplicate ids', () => {
  validateQueue(queue());
  for (const mutate of [q => { q.items[0].content.title.en = ''; }, q => { q.items[0].publishAt = '2099-02-31T10:00:00+09:00'; },
    q => { q.items[0].status = 'published'; }, q => { q.items.push(q.items[0]); }, q => { q.items[0].content.raw = 'secret'; }]) {
    const q = queue(); mutate(q); assert.throws(() => validateQueue(q));
  }
  const activity = { ...entry(), kind: 'activity', content: { start: '2099-11-07', end: '2099-11-07', confirmation: 'announced',
    link: 'https://example.invalid/post', title: { ko: '검사', en: 'Test' }, details: { summary: { ko: '<strong>내용</strong>', en: '<strong>Text</strong>' } } } };
  validateQueue({ schemaVersion: 1, items: [activity] });
  activity.content.details.summary.ko = '<img src=x onerror=alert(1)>';
  assert.throws(() => validateQueue({ schemaVersion: 1, items: [activity] }));
});
test('sealed cookies reject tampering, expiry and the wrong secret', () => {
  const data = { token: 'hidden', exp: Date.now() + 60000 }, value = seal(data, secret);
  assert.deepEqual(unseal(value, secret), data); assert.equal(unseal(value + 'changed', secret), null);
  assert.equal(unseal(value, 'wrong'), null); assert.equal(unseal(seal({ exp: 1 }, secret), secret), null);
});
test('the public Git queue contains no plaintext drafts and rejects wrong keys and plaintext entries', () => {
  const encoded = encodeQueue(queue(), secret);
  assert.equal(JSON.stringify(encoded).includes('synthetic-001'), false);
  assert.deepEqual(decodeQueue(encoded, secret), queue());
  assert.throws(() => decodeQueue(encoded, 'a different sufficiently long secret'));
  assert.throws(() => decodeQueue(queue(), secret));
  assert.deepEqual(decodeQueue({ schemaVersion: 1, items: [] }, secret), { schemaVersion: 1, items: [] });
});
test('API fails closed off lab, without configuration, and without authentication', async () => {
  delete process.env.EDITORIAL_SESSION_SECRET;
  assert.equal((await request('session', { headers: { host: 'babdoduk.vercel.app' } })).statusCode, 404);
  assert.equal((await request('session')).body.configured, false);
  process.env.EDITORIAL_SESSION_SECRET = secret; process.env.EDITORIAL_QUEUE_KEY = secret; process.env.EDITORIAL_GITHUB_CLIENT_ID = 'synthetic'; process.env.EDITORIAL_GITHUB_CLIENT_SECRET = 'synthetic';
  assert.equal((await request('queue', { headers: { cookie: '' } })).statusCode, 401);
});
test('API enforces administrator identity, repo permission, origin and CSRF', async () => {
  mockGithub({ login: 'someone-else' }); assert.equal((await request('queue')).statusCode, 403);
  mockGithub({ push: false }); assert.equal((await request('queue')).statusCode, 403);
  mockGithub();
  assert.equal((await request('queue', { method: 'POST', headers: { origin: 'https://attacker.invalid' } })).statusCode, 403);
  assert.equal((await request('queue', { method: 'POST', headers: { 'x-editorial-csrf': '' } })).statusCode, 403);
  assert.equal((await request('callback', { headers: { cookie: '' } })).statusCode, 403);
});
test('API compares queue revision and writes only the queue on lab', async () => {
  const writes = mockGithub();
  assert.equal((await request('queue', { method: 'POST', body: { sha: 'old', queue: queue() } })).statusCode, 409);
  assert.equal(writes.length, 0);
  const saved = await request('queue', { method: 'POST', body: { sha: 'queue-blob', queue: queue() } });
  assert.equal(saved.statusCode, 200); assert.equal(writes.length, 4);
  assert.equal(writes[1].body.base_tree, 'base-tree');
  assert.deepEqual(writes[1].body.tree.map(e => e.path), [QUEUE]);
  assert.equal(Buffer.from(writes[0].body.content, 'base64').toString().includes('synthetic-001'), false);
  assert.deepEqual(writes[2].body.parents, ['lab-base']);
  assert.equal(writes[3].path, '/repos/joshualikaist/Babdoduk/git/refs/heads/lab');
  assert.deepEqual(writes[3].body, { sha: 'lab-commit', force: false });
  assert.equal(JSON.stringify(saved.body).includes('synthetic-token'), false);
});
test('a simultaneous publication or cancellation rejects the normal lab ref update', async () => {
  const writes = mockGithub({ moved: true });
  const saved = await request('queue', { method: 'POST', body: { sha: 'queue-blob', queue: queue() } });
  assert.equal(saved.statusCode, 409);
  assert.equal(writes[3].body.force, false);
});
test('published entries cannot be edited and past schedules cannot be newly approved', async () => {
  mockGithub({ receipts: [{ id: entry().id, digest: digest(entry()) }] });
  const changed = queue(); changed.items[0].content.title.en = 'Changed';
  assert.equal((await request('queue', { method: 'POST', body: { sha: 'queue-blob', queue: changed } })).statusCode, 409);
  mockGithub(); const past = queue(); past.items[0].publishAt = '2000-01-01T10:00:00+09:00';
  assert.equal((await request('queue', { method: 'POST', body: { sha: 'queue-blob', queue: past } })).statusCode, 400);
});
