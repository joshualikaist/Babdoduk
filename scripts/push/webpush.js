'use strict';

const crypto = require('crypto');

const b64u = (buf) => Buffer.from(buf).toString('base64url');
const unb64u = (text) => Buffer.from(String(text || ''), 'base64url');
const RECORD_SIZE = 4096;

function hkdf(ikm, salt, info, length) {
  return Buffer.from(crypto.hkdfSync('sha256', ikm, salt, info, length));
}

function encrypt(plaintext, p256dh, auth, opts = {}) {
  const receiver = unb64u(p256dh);
  const secret = unb64u(auth);
  if (receiver.length !== 65 || receiver[0] !== 4) throw new Error('bad receiver key');
  if (secret.length !== 16) throw new Error('bad auth secret');
  const data = Buffer.from(plaintext);
  if (data.length + 1 + 16 > RECORD_SIZE - 86) throw new Error('message too long');
  const ecdh = crypto.createECDH('prime256v1');
  if (opts.senderPrivateKey) ecdh.setPrivateKey(unb64u(opts.senderPrivateKey));
  else ecdh.generateKeys();
  const sender = ecdh.getPublicKey();
  const shared = ecdh.computeSecret(receiver);
  const ikm = hkdf(shared, secret, Buffer.concat([Buffer.from('WebPush: info\0'), receiver, sender]), 32);
  const salt = opts.salt ? unb64u(opts.salt) : crypto.randomBytes(16);
  const key = hkdf(ikm, salt, Buffer.from('Content-Encoding: aes128gcm\0'), 16);
  const nonce = hkdf(ikm, salt, Buffer.from('Content-Encoding: nonce\0'), 12);
  const cipher = crypto.createCipheriv('aes-128-gcm', key, nonce);
  const body = Buffer.concat([cipher.update(Buffer.concat([data, Buffer.from([2])])), cipher.final(), cipher.getAuthTag()]);
  const head = Buffer.alloc(21);
  salt.copy(head, 0);
  head.writeUInt32BE(RECORD_SIZE, 16);
  head[20] = sender.length;
  return Buffer.concat([head, sender, body]);
}

function pad32(buf) { return buf.length >= 32 ? buf : Buffer.concat([Buffer.alloc(32 - buf.length), buf]); }
function generateKeys() {
  const ecdh = crypto.createECDH('prime256v1');
  ecdh.generateKeys();
  return { publicKey: b64u(ecdh.getPublicKey()), privateKey: b64u(pad32(ecdh.getPrivateKey())) };
}

function signingKey(keys) {
  const pub = unb64u(keys.publicKey);
  const d = unb64u(keys.privateKey);
  if (pub.length !== 65 || pub[0] !== 4 || d.length < 1 || d.length > 32) throw new Error('bad key file');
  return crypto.createPrivateKey({
    format: 'jwk',
    key: { kty: 'EC', crv: 'P-256', d: b64u(pad32(d)), x: b64u(pub.subarray(1, 33)), y: b64u(pub.subarray(33)) }
  });
}

function vapidAuthorization(endpoint, keys, subject, nowMs) {
  const head = b64u(JSON.stringify({ typ: 'JWT', alg: 'ES256' }));
  const claims = b64u(JSON.stringify({
    aud: new URL(endpoint).origin,
    exp: Math.floor((nowMs == null ? Date.now() : nowMs) / 1000) + 12 * 3600,
    sub: subject
  }));
  const sig = crypto.sign('sha256', Buffer.from(head + '.' + claims), { key: signingKey(keys), dsaEncoding: 'ieee-p1363' });
  return 'vapid t=' + head + '.' + claims + '.' + b64u(sig) + ', k=' + keys.publicKey;
}

function pushRequest(device, message, keys, subject, opts = {}) {
  const body = encrypt(JSON.stringify(message), device.p256dh, device.auth);
  return {
    url: device.endpoint,
    init: {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Encoding': 'aes128gcm',
        TTL: String(Math.max(60, Math.floor(opts.ttl || 1800))),
        Urgency: 'high',
        Authorization: vapidAuthorization(device.endpoint, keys, subject, opts.now)
      },
      body
    }
  };
}

module.exports = { encrypt, generateKeys, vapidAuthorization, pushRequest, b64u, unb64u };
