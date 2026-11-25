'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SITES = new Set(['www.babdodukms.com', 'babdoduk.vercel.app', 'babdoduk-lab.vercel.app']);
const PAGE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const LANGS = new Set(['ko', 'en']);
const DEVICES = new Set(['phone', 'tablet', 'computer']);
const CRAWLER = /bot|crawl|spider|slurp|facebookexternalhit|preview|headless|lighthouse|pagespeed/i;
const MAX_BODY = 512;

function publicConfig() {
  const text = fs.readFileSync(path.join(ROOT, 'js/ggongbab-public-config.js'), 'utf8');
  const url = (text.match(/SUPABASE_URL:\s*'([^']+)'/) || [])[1];
  const key = (text.match(/SUPABASE_PUBLISHABLE_KEY:\s*'([^']+)'/) || [])[1];
  return { url, key };
}

function siteOf(headers) {
  const h = headers || {};
  const host = String(h['x-forwarded-host'] || h.host || '').split(',')[0].trim().toLowerCase();
  return SITES.has(host) ? host : null;
}

async function readBody(req) {
  let raw = req.body;
  if (raw && typeof raw === 'object' && !Buffer.isBuffer(raw)) return raw;
  if (raw === undefined || raw === null) {
    raw = '';
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > MAX_BODY) return null;
    }
  }
  raw = Buffer.isBuffer(raw) ? raw.toString('utf8') : String(raw);
  if (raw.length > MAX_BODY) return null;
  try { return JSON.parse(raw); } catch (e) { return null; }
}

function visitOf(body, headers) {
  const site = siteOf(headers);
  const agent = String((headers || {})['user-agent'] || '');
  if (!site || !agent || CRAWLER.test(agent) || !body || typeof body !== 'object') return null;
  const { page, lang, device } = body;
  if (typeof page !== 'string' || page.length > 40 || !PAGE.test(page)) return null;
  if (!LANGS.has(lang) || !DEVICES.has(device)) return null;
  return { p_site: site, p_page: page, p_lang: lang, p_device: device };
}

async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.statusCode = 405;
    res.setHeader('Allow', 'POST');
    res.end();
    return;
  }
  res.statusCode = 204;
  try {
    const visit = visitOf(await readBody(req), req.headers);
    if (visit) {
      const { url, key } = publicConfig();
      if (url && key) {
        await fetch(url + '/rest/v1/rpc/count_visit', {
          method: 'POST',
          headers: { apikey: key, Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
          body: JSON.stringify(visit),
          signal: AbortSignal.timeout(3000)
        });
      }
    }
  } catch (e) {  }
  res.end();
}

module.exports = handler;
module.exports.visitOf = visitOf;
