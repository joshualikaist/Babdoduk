/* 밥약 메이커 정산 (bobyak.html, docs/BOBYAK.md): who pays how much, in whole won.
   Pure arithmetic in this browser: nothing here is stored or sent anywhere.

   settle({total, mode, payer, unit, people:[{name, excluded, fixed}]}) ->
     {ok: true, total, mode, unit, shares: [{index, name, amount, excluded, fixed}]}
     {ok: false, error: 'total' | 'nobody' | 'tooMany' | 'payer' | 'unit' | 'fixedInvalid' | 'fixedOver' | 'fixedShort'}

   Modes:
     'split' (나눠 내기): everyone not excluded shares what is left after the fixed amounts, equally.
     'treat' (한턱): the payer pays everything, everyone else 0.
   The leftover rule, so the shares always add up to the total exactly:
     the equal part is rounded down to the unit (1, 10, 100 or 1000 won); the units left over go one
     each to the people at the top of the list (among those sharing equally); what is left below one
     unit (only when the total itself is not a multiple of the unit) goes to the first of them. */
(function (global) {
  var MAX_TOTAL = 100000000;     // 1억 원
  var MAX_PEOPLE = 30;
  var UNITS = [1, 10, 100, 1000];

  function isWon(value) { return typeof value === 'number' && isFinite(value) && Math.floor(value) === value && value >= 0; }

  function settle(input) {
    input = input || {};
    var total = input.total;
    var people = Array.isArray(input.people) ? input.people : [];
    var mode = input.mode === 'treat' ? 'treat' : 'split';
    var unit = input.unit == null ? 1 : input.unit;
    if (!isWon(total) || total > MAX_TOTAL) return { ok: false, error: 'total' };
    if (UNITS.indexOf(unit) < 0) return { ok: false, error: 'unit' };
    if (!people.length) return { ok: false, error: 'nobody' };
    if (people.length > MAX_PEOPLE) return { ok: false, error: 'tooMany' };
    var shares = people.map(function (person, index) {
      person = person || {};
      return { index: index, name: String(person.name || '').trim().slice(0, 30), amount: 0,
               excluded: !!person.excluded, fixed: person.fixed == null || person.fixed === '' ? null : person.fixed };
    });
    var included = shares.filter(function (share) { return !share.excluded; });
    if (!included.length) return { ok: false, error: 'nobody' };

    if (mode === 'treat') {
      var payer = shares[input.payer];
      if (!payer || payer.excluded) return { ok: false, error: 'payer' };
      payer.amount = total;
      shares.forEach(function (share) { share.fixed = null; });
      return done(total, mode, unit, shares);
    }

    var fixedSum = 0;
    for (var i = 0; i < included.length; i++) {
      var fixed = included[i].fixed;
      if (fixed === null) continue;
      if (!isWon(fixed)) return { ok: false, error: 'fixedInvalid' };
      fixedSum += fixed;
    }
    shares.forEach(function (share) { if (share.excluded) share.fixed = null; });
    if (fixedSum > total) return { ok: false, error: 'fixedOver' };
    var equal = included.filter(function (share) { return share.fixed === null; });
    included.forEach(function (share) { if (share.fixed !== null) share.amount = share.fixed; });
    var rest = total - fixedSum;
    if (!equal.length) return rest === 0 ? done(total, mode, unit, shares) : { ok: false, error: 'fixedShort' };
    var units = Math.floor(rest / unit);
    var each = Math.floor(units / equal.length);
    var extra = units - each * equal.length;
    equal.forEach(function (share, n) { share.amount = each * unit + (n < extra ? unit : 0); });
    equal[0].amount += rest - units * unit;
    return done(total, mode, unit, shares);
  }

  function done(total, mode, unit, shares) {
    var sum = shares.reduce(function (acc, share) { return acc + share.amount; }, 0);
    if (sum !== total) throw new Error('settle: shares do not add up');   // never shown: the rule makes it impossible
    return { ok: true, total: total, mode: mode, unit: unit, shares: shares };
  }

  // "45,000" from a digit string the visitor typed ("45,000원", "45 000" -> 45000); NaN when it is not a whole amount.
  function parseWon(text) {
    var raw = String(text == null ? '' : text).replace(/[\s,원₩]/g, '');
    if (!/^[0-9]{1,9}$/.test(raw)) return NaN;
    return parseInt(raw, 10);
  }
  function formatWon(amount, lang) {
    var digits = String(Math.round(amount)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return lang === 'en' ? '₩' + digits : digits + '원';
  }

  global.BabdodukSettle = { settle: settle, parseWon: parseWon, formatWon: formatWon,
                            MAX_TOTAL: MAX_TOTAL, MAX_PEOPLE: MAX_PEOPLE, UNITS: UNITS.slice() };
})(window);
