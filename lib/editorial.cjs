'use strict';

// Shared by the authenticated Vercel handler and synthetic Node tests.
const crypto = require('node:crypto');
const ORIGIN = 'https://babdoduk-lab.vercel.app';
const REPO = 'joshualikaist/Babdoduk';
const QUEUE = 'inputs/editorial/schedule.json';
const RECEIPTS = 'inputs/editorial/published.json';
const fail = message => { throw Object.assign(new Error(message), { status: 400 }); };
function keys(value, required, optional = []) {
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      required.some(k => !(k in value)) || Object.keys(value).some(k => !required.includes(k) && !optional.includes(k))) fail('Invalid fields');
}
function pair(value, rich = false) {
  keys(value, ['ko', 'en']);
  for (const text of Object.values(value)) {
    if (typeof text !== 'string' || !text.trim() || text.length > 10000) fail('Both languages are required');
    if (rich && /[<>]/.test(text.replace(/<\/?strong>/g, ''))) fail('Only <strong> markup is allowed');
    if (rich && (text.match(/<strong>/g) || []).length !== (text.match(/<\/strong>/g) || []).length) fail('Close every <strong> tag');
  }
}
function day(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) fail('Invalid date');
}
function validateItem(item) {
  keys(item, ['id', 'kind', 'status', 'publishAt', 'content']);
  if (!/^[a-z0-9-]{8,80}$/.test(item.id)) fail('Invalid id');
  if (!['notice', 'activity'].includes(item.kind) || !['draft', 'scheduled'].includes(item.status)) fail('Invalid state');
  if (item.publishAt !== null && (typeof item.publishAt !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+09:00$/.test(item.publishAt) || !Number.isFinite(Date.parse(item.publishAt)))) fail('Use a Korean publication time');
  if (item.publishAt !== null) {
    day(item.publishAt.slice(0, 10));
    if (Number(item.publishAt.slice(11, 13)) > 23 || Number(item.publishAt.slice(14, 16)) > 59) fail('Invalid publication time');
  }
  if (item.status === 'scheduled' && !item.publishAt) fail('Publication time required');
  const c = item.content;
  if (item.kind === 'notice') {
    keys(c, ['date', 'title', 'text']); day(c.date); pair(c.title); pair(c.text);
  } else {
    keys(c, ['start', 'end', 'confirmation', 'link', 'title', 'details'], ['place']);
    day(c.start); day(c.end);
    if (c.end < c.start || !['announced', 'tentative', 'held', 'cancelled'].includes(c.confirmation)) fail('Invalid activity dates or confirmation');
    // Existing interactive activities are edited through normal source review, not this queue.
    try { const u = new URL(c.link); if (u.protocol !== 'https:' || u.username || u.password) fail('HTTPS link required'); }
    catch { fail('HTTPS link required'); }
    pair(c.title); if (c.place) pair(c.place);
    keys(c.details, ['summary'], ['duration', 'prizes', 'participation']);
    Object.values(c.details).forEach(value => pair(value, true));
  }
  return item;
}
function validateQueue(data) {
  keys(data, ['schemaVersion', 'items']);
  if (data.schemaVersion !== 1 || !Array.isArray(data.items) || data.items.length > 200) fail('Invalid queue');
  data.items.forEach(validateItem);
  if (new Set(data.items.map(i => i.id)).size !== data.items.length) fail('Duplicate id');
  return data;
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function digest(value) { return crypto.createHash('sha256').update(canonical(value)).digest('hex'); }
function seal(value, secret) {
  const iv = crypto.randomBytes(12), key = crypto.createHash('sha256').update(secret).digest();
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString('base64url');
}
function unseal(value, secret, expiring = true) {
  try {
    const bytes = Buffer.from(value, 'base64url');
    const decipher = crypto.createDecipheriv('aes-256-gcm', crypto.createHash('sha256').update(secret).digest(), bytes.subarray(0, 12));
    decipher.setAuthTag(bytes.subarray(12, 28));
    const data = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]));
    return !expiring || data.exp > Date.now() ? data : null;
  } catch { return null; }
}
function encodeQueue(data, secret) {
  if (!secret || secret.length < 32) fail('Queue encryption key is not configured');
  return { schemaVersion: 1, encrypted: seal(validateQueue(data), secret) };
}
function decodeQueue(data, secret) {
  // The only plaintext form allowed is the empty bootstrap file; unpublished text stays private
  // even though the repository and its full Git history are public.
  if (data?.schemaVersion === 1 && Array.isArray(data.items) && data.items.length === 0 && Object.keys(data).length === 2) return validateQueue(data);
  if (!secret || secret.length < 32 || data?.schemaVersion !== 1 || typeof data.encrypted !== 'string' || Object.keys(data).length !== 2) fail('Invalid encrypted queue');
  const decoded = unseal(data.encrypted, secret, false);
  if (!decoded) fail('Queue could not be decrypted');
  return validateQueue(decoded);
}
module.exports = { ORIGIN, REPO, QUEUE, RECEIPTS, validateItem, validateQueue, canonical, digest, seal, unseal, encodeQueue, decodeQueue };
