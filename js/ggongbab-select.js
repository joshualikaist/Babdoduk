/* Client-side eligibility for published free-food rows, shared by the hub
   and the home summary. The backend selection policy stays authoritative;
   this repeats its safety checks so an unsafe row never becomes a card or count. */
(function (global) {
  var KST_OFFSET = 9 * 60;

  function toKst(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return new Date(d.getTime() + (d.getTimezoneOffset() + KST_OFFSET) * 60000);
  }
  function nowKst() { return toKst(new Date().toISOString()); }
  function ymd(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function tri(value) {
    if (value === true) return 'true';
    if (value === false) return 'false';
    var s = String(value == null ? 'unknown' : value).toLowerCase();
    return (s === 'true' || s === 'false') ? s : 'unknown';
  }
  // A listing stands on explicit food, or on a giveaway: a prize draw or a gift for participants
  // (owner decision 2026-10-14; the backend's publication_eligible). Unknown food is neither a
  // positive nor a negative claim, so a row with neither is not shown.
  function hasFood(ev) { return tri((ev.food || {}).provided) === 'true'; }
  function hasGiveaway(ev) {
    var gift = ev.giveaway;
    return !!gift && typeof gift === 'object' && tri(gift.provided) === 'true';
  }
  function isPublic(ev) {
    return (!ev.contentType || ev.contentType === 'free_food') &&
      (hasFood(ev) || hasGiveaway(ev)) && !ev.needs_review && !ev.needsReview;
  }
  // What every free-food (꽁밥) count counts: a listed row with explicit food. A giveaway-only
  // listing is shown with its gift mark but is never counted as free food.
  function isFreeFood(ev) { return isPublic(ev) && hasFood(ev); }
  function isGiveawayOnly(ev) { return isPublic(ev) && !hasFood(ev); }
  // A giveaway with no event date of its own is listed at its sign-up deadline: the export writes
  // the deadline as startAt. Compared as instants, so the static snapshot and the lab Realtime
  // rows read the same however each spells the time.
  function isDeadlineOnly(ev) {
    if (!hasGiveaway(ev)) return false;
    var start = toKst(ev.startAt);
    var deadline = toKst((ev.registration || {}).deadline);
    return !!start && !!deadline && start.getTime() === deadline.getTime();
  }
  // With no end time ("11:30 ~ 소진 시까지"), an event stays current for the same window
  // the feed keeps it after it starts (GGONGBAB_EXPIRED_GRACE_HOURS, 3 h), so a hand-out
  // that began before anyone saw the notice is still listed while it may be running.
  // A deadline-only giveaway is listed until its sign-up deadline, and no longer.
  var OPEN_ENDED_HOURS = 3;
  function eventEnd(ev) {
    var end = toKst(ev.endAt);
    if (end) return end;
    var start = toKst(ev.startAt);
    if (!start) return null;
    return isDeadlineOnly(ev) ? start : new Date(start.getTime() + OPEN_ENDED_HOURS * 3600000);
  }
  function isUpcoming(ev, now) {
    var end = eventEnd(ev);
    return !end || end >= now;
  }
  function byStart(a, b) { return String(a.startAt || '').localeCompare(String(b.startAt || '')); }
  // The counted free food of today, and from today on: giveaway-only listings are left out.
  function todayUpcoming(events, now) {
    return (events || []).filter(function (ev) {
      var s = toKst(ev.startAt);
      return isFreeFood(ev) && s && ymd(s) === ymd(now) && isUpcoming(ev, now);
    }).sort(byStart);
  }
  function futurePublic(events, now) {
    return (events || []).filter(function (ev) {
      var s = toKst(ev.startAt);
      return isFreeFood(ev) && s && ymd(s) >= ymd(now) && isUpcoming(ev, now);
    }).sort(byStart);
  }

  // ---- Sessions (2026-10-18) ----
  // An event that runs over several days carries `sessions`: each with its own start, end and, when the
  // source said so, its own place and food. `occurrences` turns such an event into one row per session
  // day (id "<id>#<n>", that session's times, place and food, every other field of the event), so the
  // counts, dots, day panel and upcoming list all work per day without knowing about sessions. An event
  // without sessions, or whose sessions do not hold together, stays one row exactly as before.
  var MAX_SESSIONS = 14;
  function validSessions(ev) {
    var list = ev && ev.sessions;
    if (!Array.isArray(list) || list.length < 2 || list.length > MAX_SESSIONS) return null;
    var previous = null;
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      var start = s && typeof s === 'object' ? toKst(s.startAt) : null;
      var end = s && s.endAt ? toKst(s.endAt) : null;
      if (!start || (s.endAt && !end) || (end && end < start) || (previous && start <= previous)) return null;
      previous = start;
    }
    return list;
  }
  function occurrences(events) {
    var out = [];
    (events || []).forEach(function (ev) {
      var list = validSessions(ev);
      if (!list) { out.push(ev); return; }
      list.forEach(function (s, i) {
        var copy = {};
        Object.keys(ev).forEach(function (key) { if (key !== 'sessions') copy[key] = ev[key]; });
        copy.id = ev.id + '#' + (i + 1);
        copy.startAt = s.startAt;
        copy.endAt = s.endAt || null;
        copy.session = { n: i + 1, total: list.length };
        var place = s.location;
        if (place && (place.name || place.building || place.room)) copy.location = place;
        if (s.foodDescription) copy.food = Object.assign({}, ev.food, { description: s.foodDescription });
        out.push(copy);
      });
    });
    return out;
  }
  // Who an event is for, as a short line, or ''. The extracted audience wins (an inferred one is
  // marked, because it is a guess from the content, not a statement); the stated eligibility is the
  // fallback. `mark` formats an inferred audience, e.g. "{who} (추정)".
  function audienceOf(ev, mark) {
    var a = ev && ev.audience;
    if (a && typeof a.text === 'string' && a.text.trim()) {
      var who = a.text.trim();
      return a.basis === 'inferred' && typeof mark === 'function' ? mark(who) : who;
    }
    return ev && ev.eligibility ? String(ev.eligibility) : '';
  }

  // A Zoom/Meet/Teams/Webex address is how to attend online, never a sign-up form. The parser
  // sometimes reads one as "register here" (and then marks sign-up as required), so the pages
  // split the registration into {required, url} for a real sign-up and {join} for a meeting link.
  // A sign-up is only claimed with a form link or a deadline; "false" is kept as it is.
  var MEETING_HOST = /(^|\.)(zoom\.us|zoom\.com|zoomgov\.com|meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|webex\.com)$/i;
  // The browser's own URL parser decides the host (backslashes, user@ prefixes, a trailing dot), so a
  // look-alike such as https://evil.com\.zoom.us/ is not taken for Zoom. A registration page on those
  // hosts (/webinar/register/...) is a real sign-up and stays one.
  function isMeetingLink(url) {
    var u;
    try { u = new URL(String(url || '').trim()); } catch (err) { return false; }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return false;
    if (/\/register(\/|$)/i.test(u.pathname)) return false;
    return MEETING_HOST.test(u.hostname.replace(/\.$/, ''));
  }
  function signUp(ev) {
    var reg = (ev && ev.registration) || {};
    var url = String(reg.url || '').trim();
    var required = tri(reg.required);
    if (!isMeetingLink(url)) return { required: required, url: url, join: '' };
    return { required: required === 'true' && !reg.deadline ? 'unknown' : required, url: '', join: url };
  }

  // What is handed out, in one or two words (owner 2026-11-05: the time and the food first, the rest on
  // a tap): the dishes the food description names, as i18n keys `dish.<key>` with a decorative emoji.
  // Only the description is read, never the title. Named dishes come first (at most two); a general
  // word (점심, 식사) stands alone or leads only light food ("식사 · 간식"); without either, the type.
  var DISHES = [
    ['burger', '🍔', /버거|burger/i],
    ['pizza', '🍕', /피자|pizza/i],
    ['chicken', '🍗', /치킨|chicken/i],
    ['sushi', '🍣', /초밥|스시|sushi/i],
    ['sandwich', '🥪', /샌드위치|sandwich/i],
    ['lunchbox', '🍱', /도시락|lunch ?box|bento/i],
    ['bbq', '🍖', /바비큐|바베큐|소고기|삼겹|BBQ|barbecue/i],
    ['kimbap', '🍙', /김밥|주먹밥|kimbap/i],
    ['bread', '🥐', /빵|베이커리|bakery|bread|pastr/i],
    ['cake', '🍰', /케이크|cake/i],
    ['coffee', '☕', /커피|coffee/i],
    ['drink', '🥤', /음료|드링크|주스|콜라|사이다|drinks?\b|beverage|juice/i],
    ['snack', '🍪', /간식|과자|스낵|snacks?\b/i],
    ['refreshment', '🍪', /다과|refreshments?/i],
    ['coupon', '🎟️', /쿠폰|기프티콘|coupon|voucher/i]
  ];
  var LIGHT = { coffee: 1, drink: 1, snack: 1, refreshment: 1 };
  var GENERAL = [
    ['dinner', '🍽️', /석식|저녁|dinner/i],
    ['lunch', '🍽️', /점심|중식|lunch/i],
    ['catering', '🍽️', /케이터링|뷔페|catering|buffet/i],
    ['meal', '🍽️', /식사|meals?\b/i]
  ];
  var TYPE_DISH = { meal: 'meal', lunchbox: 'lunchbox', snack: 'snack', refreshment: 'refreshment',
    beverage: 'drink', coupon: 'coupon' };
  var DISH_EMOJI = {};
  DISHES.concat(GENERAL).forEach(function (row) { DISH_EMOJI[row[0]] = row[1]; });
  DISH_EMOJI.food = '🍽️';
  function dishes(ev) {
    if (!hasFood(ev)) return [];
    var food = ev.food || {};
    var text = String(food.description || '');
    var found = DISHES.filter(function (row) { return row[2].test(text); }).map(function (row) { return row[0]; });
    // "BBQ 황금올리브 치킨" is a chicken brand, not a barbecue.
    if (found.indexOf('chicken') >= 0) found = found.filter(function (key) { return key !== 'bbq'; });
    found = found.slice(0, 2);
    var general = GENERAL.filter(function (row) { return row[2].test(text); }).map(function (row) { return row[0]; })[0];
    if (general && (!found.length || (found.length === 1 && LIGHT[found[0]]))) found.unshift(general);
    if (!found.length) found.push(TYPE_DISH[food.type] || 'food');
    return found.map(function (key) { return { key: key, emoji: DISH_EMOJI[key] }; });
  }
  // One label for a row: "샌드위치", "도시락 · 다과". `t(key, fallback)` is the page's translation lookup.
  function dishLabel(ev, t) {
    return dishes(ev).map(function (d) { return t('dish.' + d.key, d.key); }).join(' · ');
  }
  function dishEmoji(ev) {
    var list = dishes(ev);
    return list.length ? list[0].emoji : '';
  }
  // Whether a free text is in the page's language: Korean text on the Korean page, text without
  // Hangul on the English page. Source text in the other language stays out of the page's lines.
  function inLang(text, lang) {
    var hangul = /[가-힣]/.test(String(text || ''));
    return lang === 'en' ? !hangul : hangul;
  }

  global.BabdodukFreeFood = {
    dishes: dishes,
    dishLabel: dishLabel,
    dishEmoji: dishEmoji,
    inLang: inLang,
    toKst: toKst,
    nowKst: nowKst,
    ymd: ymd,
    tri: tri,
    hasFood: hasFood,
    hasGiveaway: hasGiveaway,
    isPublic: isPublic,
    isFreeFood: isFreeFood,
    isGiveawayOnly: isGiveawayOnly,
    isDeadlineOnly: isDeadlineOnly,
    eventEnd: eventEnd,
    isUpcoming: isUpcoming,
    todayUpcoming: todayUpcoming,
    futurePublic: futurePublic,
    occurrences: occurrences,
    audienceOf: audienceOf,
    signUp: signUp
  };
})(window);
