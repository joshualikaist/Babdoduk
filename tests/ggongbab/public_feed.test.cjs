/* Pure synthetic controller tests; Node built-ins only, no network. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const feed = require('../../js/ggongbab-public-feed.js');
const config = { SUPABASE_URL: 'https://public.invalid', SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_SYNTHETIC' };
const row = (id = 'a', revision = 'r1') => ({ id, content_revision: revision,
  title: 'Lunch', summary: 'Campus', start_at: '2026-09-23T03:00:00Z', end_at: null,
  date_text: '', time_text: '', location_name: 'N1', building: 'N1', room: '101',
  food_provided: 'true', food_type: 'meal', food_description: 'Lunch',
  organizer: 'Campus', eligibility: 'All', registration_required: 'unknown',
  registration_deadline: null, registration_url: '', confidence: 0.9,
  source_types: ['dooray', 'dooray_mailbox', 'kaist_public', 'manual', 'portal'], updated_at: '2026-09-23T00:00:00Z' });
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(setImmediate); };
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function harness(overrides = {}) {
  const h = { rows: [row()], calls: [], channels: [], frames: [], timers: new Map(), snapshots: 0,
    failures: 0, creates: 0, removed: 0, disconnected: 0, maxChannels: 0, activeChannels: 0 };
  let timerId = 0;
  h.client = {
    realtime: { disconnect() { h.disconnected++; } },
    from(table) {
      const call = { table, order: [] }; h.calls.push(call);
      return {
        select(columns) { call.columns = columns; return this; },
        order(key, opts) { call.order.push([key, opts]); return this; },
        range(start, end) { call.range = [start, end]; return this; },
        async abortSignal(signal) {
          call.signal = signal;
          if (h.select) return h.select(call);
          if (h.selectError) return { error: true, data: null };
          return { data: h.rows.slice(call.range[0], call.range[1] + 1) };
        }
      };
    },
    channel(name) {
      h.activeChannels++; h.maxChannels = Math.max(h.maxChannels, h.activeChannels);
      const ch = { name,
        on(event, filter, cb) { Object.assign(ch, { event, filter, cb }); return ch; },
        subscribe(status) { ch.status = status; return ch; }
      };
      h.channels.push(ch); return ch;
    },
    async removeChannel() { h.removed++; if (h.removal) await h.removal; h.activeChannels--; }
  };
  h.ctl = feed.create({ config, makeClient: async () => { h.creates++; if (h.clientError) throw Error(); return h.client; },
    loadSnapshot: async () => { h.snapshots++; if (h.snapshotError) throw Error(); return h.snapshot || { events: [{ id: 'snapshot', title: 'Snapshot' }], generatedAt: '2026-09-22T00:00:00Z' }; },
    onData: (data, state) => h.frames.push({ data, state }), onError: () => h.failures++,
    setTimeout: (fn, delay) => { const id = ++timerId; h.timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => h.timers.delete(id), random: () => 1,
    ...overrides });
  h.latest = () => h.frames.at(-1)?.data;
  h.status = status => h.channels.at(-1).status(status);
  h.change = (eventType, data) => h.channels.at(-1).cb(eventType === 'DELETE' ? { eventType, old: data } : { eventType, new: data });
  h.tick = async delay => {
    const [id, timer] = [...h.timers].find(([, t]) => t.delay === delay) || [];
    assert.ok(timer, `timer ${delay} exists`); h.timers.delete(id); timer.fn(); await flush();
  };
  h.start = async () => { h.ctl.start(); await flush(); };
  h.live = async () => { await h.start(); h.status('SUBSCRIBED'); await flush(); };
  return h;
}

test('mapping matches nested snapshot shape, fixed sources and KST seconds', () => {
  const event = feed.mapRow(row());
  assert.equal(event.startAt, '2026-09-23T12:00:00+09:00');
  assert.equal(event.endAt, null);
  assert.deepEqual(event.location, { name: 'N1', building: 'N1', room: '101' });
  assert.deepEqual(event.food, { provided: 'true', type: 'meal', description: 'Lunch' });
  assert.deepEqual(event.registration, { required: 'unknown', deadline: null, url: '' });
  assert.equal(event.sources[1].name, 'Dooray 메일함');
  assert.equal(event.sources[4].name, 'KAIST Portal');
  assert.equal(event.sources.length, 5);
  assert.equal('content_revision' in event, false);
  assert.equal('updated_at' in event, false);
  assert.equal(event.sources.some(s => 'url' in s), false);
});
test('mapping keeps tri-state strings and nullable timestamps', () => {
  for (const value of ['true', 'false', 'unknown']) {
    const event = feed.mapRow({ ...row(), food_provided: value, registration_required: value,
      end_at: '2026-09-23T13:00:00.123+09:00', registration_deadline: 'invalid' });
    assert.equal(event.food.provided, value); assert.equal(event.registration.required, value);
    assert.equal(event.endAt, '2026-09-23T13:00:00+09:00'); assert.equal(event.registration.deadline, null);
  }
});
test('mapping discards unrecognized sources and extra fields', () => {
  const event = feed.mapRow({ ...row(), source_types: ['portal', 'toString', 'PRIVATE'], private_data: 'PRIVATE' });
  assert.deepEqual(event.sources, [{ type: 'portal', name: 'KAIST Portal' }]);
  assert.equal(JSON.stringify(event).includes('PRIVATE'), false);
});
test('exact 22-column select and ordered paginated public table only', async () => {
  const h = harness(); await h.live();
  assert.equal(feed.columns.split(',').length, 22);
  assert.deepEqual(h.calls.map(c => c.table), ['ggongbab_public_events', 'ggongbab_public_events']);
  assert.ok(h.calls.every(c => c.columns === feed.columns && c.signal instanceof AbortSignal));
  assert.deepEqual(h.calls[0].order, [['start_at', { ascending: true }], ['id', { ascending: true }]]);
  assert.deepEqual(h.calls.map(c => c.range), [[0, 499], [1, 500]]);
});
test('no select before confirmed subscription; exact channel scope', async () => {
  const h = harness(); await h.start(); assert.equal(h.calls.length, 0);
  assert.equal(h.channels[0].event, 'postgres_changes');
  assert.deepEqual(h.channels[0].filter, { event: '*', schema: 'public', table: 'ggongbab_public_events' });
  h.status('SUBSCRIBED'); await flush(); assert.equal(h.ctl.status(), 'db-live');
});
test('INSERT upserts canonical ID without duplicate cards', async () => {
  const h = harness(); await h.live(); h.change('INSERT', row('b')); h.change('INSERT', row('b'));
  assert.deepEqual(h.latest().events.map(e => e.id), ['a', 'b']); assert.equal(h.frames.length, 2);
});
test('UPDATE replaces content and same revision ignores timestamp-only changes', async () => {
  const h = harness(); await h.live();
  h.change('UPDATE', { ...row('a', 'r2'), title: 'Changed' });
  h.change('UPDATE', { ...row('a', 'r2'), updated_at: '2026-10-01' });
  assert.equal(h.latest().events[0].title, 'Changed'); assert.equal(h.frames.length, 2);
});
test('DELETE needs only old primary key and unknown deletion is a no-op', async () => {
  const h = harness(); await h.live(); h.change('DELETE', { id: 'a' }); h.change('DELETE', { id: 'absent' });
  assert.deepEqual(h.latest().events, []); assert.equal(h.frames.length, 2);
});
test('full periodic reconciliation removes stale IDs and is authoritative empty', async () => {
  const h = harness(); await h.live(); h.rows = []; await h.tick(60000);
  assert.deepEqual(h.latest().events, []); assert.equal(h.snapshots, 0);
});
test('initial empty DB is successful and does not fall back', async () => {
  const h = harness(); h.rows = []; await h.live();
  assert.deepEqual(h.latest().events, []); assert.equal(h.ctl.status(), 'db-live'); assert.equal(h.snapshots, 0);
});
test('reconnect reselect removes offline-deleted rows', async () => {
  const h = harness(); await h.live(); const count = h.calls.length;
  h.status('CHANNEL_ERROR'); await flush(); assert.equal(h.latest().events[0].id, 'a');
  h.rows = [row('b')]; await h.tick(1000); h.status('SUBSCRIBED'); await flush();
  assert.ok(h.calls.length > count); assert.deepEqual(h.latest().events.map(e => e.id), ['b']);
  assert.equal(h.maxChannels, 1); assert.equal(h.removed, 1);
});
test('initial select failure uses snapshot with its generation timestamp', async () => {
  const h = harness(); h.selectError = true; await h.live();
  assert.equal(h.ctl.status(), 'snapshot-fallback'); assert.equal(h.latest().events[0].id, 'snapshot');
  assert.equal(h.latest().generatedAt, '2026-09-22T00:00:00Z');
});
test('DB recovery replaces rather than merges snapshot and suppresses generatedAt', async () => {
  const h = harness(); h.selectError = true; await h.live(); h.selectError = false;
  await h.tick(1000); h.status('SUBSCRIBED'); await flush();
  assert.deepEqual(h.latest().events.map(e => e.id), ['a']); assert.equal(h.latest().generatedAt, null);
});
test('subscription failure preserves last successful DB even if fallback is stale', async () => {
  const h = harness(); await h.live(); h.status('CLOSED'); await flush();
  assert.equal(h.ctl.status(), 'reconnecting'); assert.equal(h.latest().events[0].id, 'a');
  assert.equal(h.frames.length, 1); assert.equal(h.snapshots, 1);
});
test('missing config loads JSON without constructing a client or a retry loop', async () => {
  const h = harness({ config: null }); await h.start();
  assert.equal(h.creates, 0); assert.equal(h.channels.length, 0); assert.equal(h.timers.size, 0);
  assert.equal(h.latest().events[0].id, 'snapshot');
});
test('unavailable library or browser support uses JSON', async () => {
  const h = harness(); h.clientError = true; await h.start();
  assert.equal(h.latest().events[0].id, 'snapshot'); assert.equal(h.channels.length, 0);
});
test('subscription handshake timeout falls back and retires old channel', async () => {
  const h = harness(); await h.start(); await h.tick(12000);
  assert.equal(h.latest().events[0].id, 'snapshot'); assert.equal(h.removed, 1);
});
test('snapshot failure only reports error when no good data exists', async () => {
  const h = harness(); h.snapshotError = true; await h.live(); h.status('TIMED_OUT'); await flush();
  assert.equal(h.failures, 0); assert.equal(h.latest().events.length, 1);
  const first = harness({ config: null }); first.snapshotError = true; await first.start(); assert.equal(first.failures, 1);
});
test('backoff grows to a hard cap with bounded jitter', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 50].map(n => feed.retryDelay(n, () => 1)), [1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  for (let n = 0; n < 100; n++) assert.ok(feed.retryDelay(n, () => 0) <= 30000);
  assert.equal(feed.retryDelay(0, () => 0), 800);
});
test('actual failed attempts back off rather than tight-loop', async () => {
  const h = harness(); h.clientError = true; await h.start();
  for (const delay of [1000, 2000, 4000, 8000, 16000, 30000]) await h.tick(delay);
  assert.equal(h.creates, 7); assert.ok([...h.timers.values()].some(t => t.delay === 30000));
});
test('stop cleans timers/channel and resume performs full select', async () => {
  const h = harness(); await h.live(); await h.ctl.stop(); const oldCalls = h.calls.length;
  assert.equal(h.timers.size, 0); assert.equal(h.activeChannels, 0); assert.equal(h.disconnected, 1);
  await h.live(); assert.ok(h.calls.length > oldCalls); assert.equal(h.maxChannels, 1);
});
test('repeated start and retries never create overlapping subscriptions', async () => {
  const h = harness(); await h.live(); h.ctl.start(); h.ctl.start();
  const wait = deferred(); h.removal = wait.promise;
  h.ctl.retry(); h.ctl.retry(); await flush(); assert.equal(h.channels.length, 1);
  wait.resolve(); await flush(); assert.equal(h.channels.length, 2); assert.equal(h.maxChannels, 1);
});
test('callbacks from retired channel cannot mutate current feed', async () => {
  const h = harness(); await h.live(); const old = h.channels[0]; h.ctl.retry(); await flush();
  h.status('SUBSCRIBED'); await flush(); old.cb({ eventType: 'DELETE', old: { id: 'a' } }); old.status('CHANNEL_ERROR');
  assert.equal(h.latest().events[0].id, 'a'); assert.equal(h.ctl.status(), 'db-live');
});
test('change during select forces fresh select, never replays stale buffer over new data', async () => {
  const h = harness(); const wait = deferred(); let once = true;
  h.select = async call => {
    if (call.range[0]) return { data: [] };
    if (once) { once = false; return wait.promise; }
    return { data: [{ ...row('a', 'r3'), title: 'Newest' }] };
  };
  await h.start(); h.status('SUBSCRIBED'); await flush();
  h.change('UPDATE', { ...row('a', 'r2'), title: 'Intermediate' });
  wait.resolve({ data: [row()] }); await flush();
  assert.equal(h.latest().events[0].title, 'Newest'); assert.equal(h.frames.length, 1); assert.equal(h.calls.length, 4);
});
test('late failed-attempt select does not overwrite recovered DB', async () => {
  const h = harness(); const wait = deferred(); h.select = () => wait.promise;
  await h.start(); h.status('SUBSCRIBED'); await flush(); await h.tick(12000);
  h.select = null; h.rows = [row('b')]; await h.tick(1000); h.status('SUBSCRIBED'); await flush();
  wait.resolve({ data: [row('stale')] }); await flush();
  assert.deepEqual(h.latest().events.map(e => e.id), ['b']); assert.equal(h.calls[0].signal.aborted, true);
});
test('late fallback cannot overwrite DB recovery', async () => {
  const wait = deferred(); const h = harness({ loadSnapshot: () => wait.promise });
  h.selectError = true; await h.live(); h.selectError = false; await h.tick(1000); h.status('SUBSCRIBED'); await flush();
  wait.resolve({ events: [{ id: 'stale' }] }); await flush(); assert.equal(h.latest().events[0].id, 'a');
});
test('invalid or partial select does not publish an incomplete set', async () => {
  const h = harness(); h.select = async call => call.range[0] ? { error: true } : { data: [row()] };
  await h.live(); assert.equal(h.latest().events[0].id, 'snapshot');
});
test('repeated SDK SUBSCRIBED status also reconciles without extra channels', async () => {
  const h = harness(); await h.live(); h.rows = []; h.status('SUBSCRIBED'); await flush();
  assert.deepEqual(h.latest().events, []); assert.equal(h.channels.length, 1);
});
test('only explicit browser public config accepted, legacy anon supported', () => {
  assert.deepEqual(feed.publicConfig(config), { url: 'https://public.invalid', key: config.SUPABASE_PUBLISHABLE_KEY });
  const jwt = role => 'e30.' + Buffer.from(JSON.stringify({ role })).toString('base64url') + '.synthetic';
  assert.ok(feed.publicConfig({ ...config, SUPABASE_PUBLISHABLE_KEY: jwt('anon') }));
  for (const key of ['', 'private', jwt('service_role'), jwt('authenticated')])
    assert.equal(feed.publicConfig({ ...config, SUPABASE_PUBLISHABLE_KEY: key }), null);
  for (const url of ['http://public.invalid', 'https://user:password@public.invalid', 'https://public.invalid/path', 'https://public.invalid/?key=x'])
    assert.equal(feed.publicConfig({ ...config, SUPABASE_URL: url }), null);
});
test('hung snapshot has a bounded error deadline and aborts request', async () => {
  let signal;
  const h = harness({ config: null, loadSnapshot: s => { signal = s; return new Promise(() => {}); } });
  await h.start(); await h.tick(8000);
  assert.equal(h.failures, 1); assert.equal(signal.aborted, true);
});
test('page stop aborts pending snapshot and late response is ignored', async () => {
  const wait = deferred(); let signal;
  const h = harness({ config: null, loadSnapshot: s => { signal = s; return wait.promise; } });
  await h.start(); await h.ctl.stop();
  assert.equal(signal.aborted, true); assert.equal(h.timers.size, 0);
  wait.resolve({ events: [{ id: 'late' }] }); await flush(); assert.equal(h.frames.length, 0);
});
test('continuous changes exhaust bounded reconciliation then fall back', async () => {
  const h = harness();
  h.select = async call => {
    if (call.range[0]) return { data: [] };
    h.change('UPDATE', row()); return { data: [row()] };
  };
  await h.live(); assert.equal(h.calls.length, 10);
  assert.equal(h.latest().events[0].id, 'snapshot');
});
