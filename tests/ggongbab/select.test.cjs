/* js/ggongbab-select.js under fixed times; Node built-ins only, no network. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const context = { window: {}, Date };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../js/ggongbab-select.js'), 'utf8'), context);
  return context.window.BabdodukFreeFood;
}
const F = load();
const at = hm => F.toKst('2026-09-28T' + hm + ':00+09:00');
// MISS-001: "11:30 ~ 소진 시까지", mailed around 11:45.
const coffee = { id: 'miss-001', startAt: '2026-09-28T11:30:00+09:00', endAt: null,
  food: { provided: 'true', type: 'beverage' } };

test('campus news cannot inflate counts, radar, next-free or archived eligibility', () => {
  const news = { ...coffee, id: 'news', contentType: 'campus_food_news', hasFreeOffer: false,
    startAt: '2026-09-28T10:00:00+09:00' };
  // Even a malformed news row carrying food.provided=true is excluded.
  const mixed = [news, coffee];
  assert.equal(F.isPublic(news), false);
  assert.deepEqual(Array.from(F.todayUpcoming(mixed, at('09:00')), e => e.id), ['miss-001']);
  assert.deepEqual(Array.from(F.futurePublic(mixed, at('09:00')), e => e.id), ['miss-001']);
  assert.equal(F.isPublic({ ...news, hasFreeOffer: true }), false);
  assert.equal(F.isPublic({ ...coffee, contentType: 'free_food' }), true);
});

test('an open-ended hand-out stays listed for three hours after it starts', () => {
  for (const hm of ['11:00', '11:31', '11:45', '14:29']) {
    assert.equal(F.isUpcoming(coffee, at(hm)), true, hm);
    assert.equal(F.todayUpcoming([coffee], at(hm)).length, 1, hm);
    assert.equal(F.futurePublic([coffee], at(hm)).length, 1, hm);
  }
  for (const hm of ['14:31', '18:00']) {
    assert.equal(F.isUpcoming(coffee, at(hm)), false, hm);
    assert.equal(F.todayUpcoming([coffee], at(hm)).length, 0, hm);
  }
});

test('a known end time still ends the listing at that time', () => {
  const lunch = { ...coffee, id: 'lunch', startAt: '2026-09-28T12:00:00+09:00', endAt: '2026-09-28T13:00:00+09:00' };
  assert.equal(F.isUpcoming(lunch, at('12:59')), true);
  assert.equal(F.isUpcoming(lunch, at('13:01')), false);
});

test('eventEnd of an open-ended event is start + 3 h; an undated row has none', () => {
  assert.equal(F.eventEnd(coffee).getTime() - F.toKst(coffee.startAt).getTime(), 3 * 3600000);
  assert.equal(F.eventEnd({ startAt: null, endAt: null }), null);
});

test('open-ended rows still need explicit food and no review to be listed', () => {
  assert.equal(F.todayUpcoming([{ ...coffee, food: { provided: 'unknown' } }], at('11:45')).length, 0);
  assert.equal(F.todayUpcoming([{ ...coffee, needs_review: true }], at('11:45')).length, 0);
});
