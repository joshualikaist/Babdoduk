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

// Owner decisions 2026-10-14: a giveaway (prize draw or gift for participants) is listed with a
// gift mark but never counted as free food; a giveaway with no event date of its own is listed at,
// and until, its sign-up deadline.
const giftOnly = { id: 'expo', startAt: '2026-09-28T12:00:00+09:00', endAt: '2026-09-28T17:00:00+09:00',
  food: { provided: 'unknown', type: 'unknown', description: '' },
  giveaway: { provided: 'true', description: '경품 추첨 (에어팟)' } };
const both = { ...coffee, id: 'both', giveaway: { provided: 'true', description: '기념품 증정' } };

test('a giveaway-only row is listed but never counted as free food', () => {
  assert.equal(F.isPublic(giftOnly), true);
  assert.equal(F.isFreeFood(giftOnly), false);
  assert.equal(F.isGiveawayOnly(giftOnly), true);
  assert.equal(F.hasGiveaway(giftOnly), true);
  assert.equal(F.hasFood(giftOnly), false);
  assert.deepEqual(Array.from(F.todayUpcoming([giftOnly, coffee], at('09:00')), e => e.id), ['miss-001']);
  assert.deepEqual(Array.from(F.futurePublic([giftOnly], at('09:00')), e => e.id), []);
  assert.equal(F.isPublic({ ...giftOnly, food: { provided: 'false' } }), true);
});

test('a row with food and a giveaway counts once, as free food', () => {
  assert.equal(F.isFreeFood(both), true);
  assert.equal(F.isGiveawayOnly(both), false);
  assert.deepEqual(Array.from(F.todayUpcoming([both], at('09:00')), e => e.id), ['both']);
});

test('only a real giveaway lists a row without food; review and news still exclude it', () => {
  for (const giveaway of [undefined, null, 'true', { provided: 'false' }, { provided: 'unknown' }, {}]) {
    assert.equal(F.isPublic({ ...giftOnly, giveaway }), false, JSON.stringify(giveaway));
  }
  assert.equal(F.isPublic({ ...giftOnly, giveaway: { provided: true, description: '' } }), true);
  assert.equal(F.isPublic({ ...giftOnly, needs_review: true }), false);
  assert.equal(F.isPublic({ ...giftOnly, needsReview: true }), false);
  assert.equal(F.isPublic({ ...giftOnly, contentType: 'campus_food_news' }), false);
});

test('a deadline-only giveaway is recognised by instant, from either feed path', () => {
  const deadline = { ...giftOnly, id: 'draw', startAt: '2026-10-18T23:59:00+09:00', endAt: null,
    registration: { required: 'true', deadline: '2026-10-18T23:59:00+09:00', url: '' } };
  assert.equal(F.isDeadlineOnly(deadline), true);
  // The same instant spelled in UTC, as another path may write it.
  assert.equal(F.isDeadlineOnly({ ...deadline, registration: { deadline: '2026-10-18T14:59:00Z' } }), true);
  assert.equal(F.isDeadlineOnly({ ...deadline, registration: { deadline: '2026-10-17T23:59:00+09:00' } }), false);
  assert.equal(F.isDeadlineOnly({ ...deadline, registration: null }), false);
  assert.equal(F.isDeadlineOnly({ ...deadline, registration: undefined }), false);   // the archive has none
  // Food with a deadline at its start is an event, not a deadline-only giveaway.
  const { giveaway, ...food } = { ...deadline, food: coffee.food };
  assert.equal(F.isDeadlineOnly(food), false);
});

test('a deadline-only giveaway is listed until its deadline, without the open-ended grace', () => {
  const deadline = { ...giftOnly, id: 'draw', startAt: '2026-09-28T18:00:00+09:00', endAt: null,
    registration: { required: 'true', deadline: '2026-09-28T18:00:00+09:00' } };
  assert.equal(F.eventEnd(deadline).getTime(), F.toKst(deadline.startAt).getTime());
  assert.equal(F.isUpcoming(deadline, at('17:59')), true);
  assert.equal(F.isUpcoming(deadline, at('18:01')), false);
  // A giveaway that has its own event time keeps the hand-out grace like any open-ended event.
  const dated = { ...deadline, registration: { required: 'true', deadline: '2026-09-27T18:00:00+09:00' } };
  assert.equal(F.isUpcoming(dated, at('20:59')), true);
});

// --- sessions and audience (2026-10-18) ---------------------------------------------------------
const kst = iso => F.toKst(iso);
const day = (d, from, to, extra = {}) => ({ startAt: `2026-11-0${d}T${from}:00+09:00`, endAt: to ? `2026-11-0${d}T${to}:00+09:00` : null, ...extra });
const hall = { name: '자연과학관 공통강의실', building: 'E6-1', room: '1501' };
const fusion = { name: 'KI빌딩 퓨전홀', building: 'E4', room: 'C101' };
const concert = {
  id: 'cc', title: '자연과학과 함께하는 토크 콘서트', organizer: '자연과학대학', eligibility: '',
  startAt: '2026-11-02T12:00:00+09:00', endAt: '2026-11-06T19:30:00+09:00',
  location: { name: 'both halls', building: 'E6-1 / E4', room: '1501 / C101' },
  food: { provided: 'true', type: 'meal', description: 'sandwiches / burgers' },
  sessions: [2, 3, 4, 5].map(d => day(d, '12:00', '12:50', { location: hall, foodDescription: '샌드위치' }))
    .concat([day(6, '16:00', '19:30', { location: fusion, foodDescription: '버거' })]),
};

test('a multi-day event becomes one occurrence per session day with its own time, place and food', () => {
  const rows = F.occurrences([concert]);
  assert.equal(rows.length, 5);
  assert.deepEqual(Array.from(rows, r => r.id), ['cc#1', 'cc#2', 'cc#3', 'cc#4', 'cc#5']);
  assert.deepEqual(Array.from(rows, r => r.startAt.slice(0, 16)),
    ['2026-11-02T12:00', '2026-11-03T12:00', '2026-11-04T12:00', '2026-11-05T12:00', '2026-11-06T16:00']);
  assert.equal(rows[0].endAt, '2026-11-02T12:50:00+09:00');
  assert.deepEqual(rows[0].location, hall);
  assert.deepEqual(rows[4].location, fusion);
  assert.equal(rows[0].food.description, '샌드위치');
  assert.equal(rows[4].food.description, '버거');
  assert.equal(rows[4].food.provided, 'true');                           // the rest of the food is kept
  assert.deepEqual({ ...rows[2].session }, { n: 3, total: 5 });
  assert.ok(rows.every(r => !('sessions' in r) && r.organizer === '자연과학대학' && r.title === concert.title));
  assert.ok(Array.isArray(concert.sessions) && concert.sessions.length === 5 && concert.id === 'cc');   // the input is untouched
});

test('each session day is counted, listed and ended on its own', () => {
  const rows = F.occurrences([concert]);
  assert.equal(F.futurePublic(rows, kst('2026-11-02T09:00:00+09:00')).length, 5);
  assert.deepEqual(Array.from(F.todayUpcoming(rows, kst('2026-11-03T09:00:00+09:00')), r => r.id), ['cc#2']);
  assert.equal(F.isUpcoming(rows[0], kst('2026-11-02T14:00:00+09:00')), false);   // Monday is over...
  assert.equal(F.isUpcoming(rows[1], kst('2026-11-02T14:00:00+09:00')), true);    // ...Tuesday is not
  assert.equal(F.futurePublic(rows, kst('2026-11-06T17:00:00+09:00')).length, 1);  // only Friday is left
  assert.equal(F.futurePublic(rows, kst('2026-11-06T20:00:00+09:00')).length, 0);
});

test('a session without an end time is open-ended, like any event without one', () => {
  const rows = F.occurrences([{ ...concert, sessions: [day(2, '12:00', null), day(3, '12:00', null)] }]);
  assert.equal(rows[0].endAt, null);
  assert.equal(F.isUpcoming(rows[0], kst('2026-11-02T14:59:00+09:00')), true);
  assert.equal(F.isUpcoming(rows[0], kst('2026-11-02T15:01:00+09:00')), false);
});

test('sessions that do not hold together leave the event as one unchanged row', () => {
  const ok = [day(2, '12:00', '12:50'), day(3, '12:00', '12:50')];
  const cases = {
    none: undefined, one: [ok[0]], notAList: 'Mon-Fri', tooMany: Array.from({ length: 15 }, (_, i) => day(2, '12:00', null, { startAt: `2026-11-02T${String(i).padStart(2, '0')}:00:00+09:00` })),
    outOfOrder: [ok[1], ok[0]], sameStart: [ok[0], ok[0]], badStart: [ok[0], { startAt: 'soon', endAt: null }],
    badEnd: [ok[0], { startAt: ok[1].startAt, endAt: 'later' }], endsBeforeStart: [ok[0], day(3, '12:00', '11:00')],
    notAnObject: [ok[0], 'Fri 16:00'],
  };
  for (const [name, sessions] of Object.entries(cases)) {
    const event = { ...concert, sessions };
    const rows = F.occurrences([event]);
    assert.equal(rows.length, 1, name);
    assert.equal(rows[0], event, name);
  }
  assert.deepEqual(Array.from(F.occurrences(undefined)), []);
});

test('the audience is the extracted one, marked when inferred, with the stated eligibility as the fallback', () => {
  const mark = who => `${who} (추정)`;
  assert.equal(F.audienceOf({ audience: { text: '기계공학과 학부생', basis: 'stated' }, eligibility: 'x' }, mark), '기계공학과 학부생');
  assert.equal(F.audienceOf({ audience: { text: '기계공학과 학부생', basis: 'inferred' } }, mark), '기계공학과 학부생 (추정)');
  assert.equal(F.audienceOf({ audience: { text: '기계공학과 학부생', basis: 'inferred' } }), '기계공학과 학부생');   // no marker given
  assert.equal(F.audienceOf({ audience: { text: '  ', basis: 'stated' }, eligibility: 'KAIST 재학생' }, mark), 'KAIST 재학생');
  assert.equal(F.audienceOf({ eligibility: 'KAIST 재학생' }, mark), 'KAIST 재학생');
  assert.equal(F.audienceOf({ audience: null, eligibility: '' }, mark), '');
  assert.equal(F.audienceOf(null, mark), '');
});
