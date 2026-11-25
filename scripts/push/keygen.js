#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { generateKeys } = require('./webpush');

const file = process.env.BABDODUK_PUSH_KEYS || path.join(os.homedir(), '.config/babdoduk/credentials/babdoduk_push-vapid');
const publicFile = process.env.BABDODUK_PUSH_PUBLIC || path.join(__dirname, '..', '..', '.local/push/vapid-public.txt');

const dir = path.dirname(file);
fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
fs.chmodSync(dir, 0o700);

let keys;
try {
  keys = JSON.parse(fs.readFileSync(file, 'utf8'));
  console.log('키가 이미 있어서 그대로 둬요.');
} catch (err) {
  keys = generateKeys();
  fs.writeFileSync(file, JSON.stringify(keys) + '\n', { mode: 0o600, flag: 'wx' });
  console.log('새 키를 만들었어요.');
}
fs.mkdirSync(path.dirname(publicFile), { recursive: true });
fs.writeFileSync(publicFile, keys.publicKey + '\n');
console.log('공개 키: ' + keys.publicKey);
