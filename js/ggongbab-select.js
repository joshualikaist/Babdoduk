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
  function hasFood(ev) { return tri((ev.food || {}).provided) === 'true'; }
  function hasGiveaway(ev) {
    var gift = ev.giveaway;
    return !!gift && typeof gift === 'object' && tri(gift.provided) === 'true';
  }
  function isPublic(ev) {
    return (!ev.contentType || ev.contentType === 'free_food') &&
      (hasFood(ev) || hasGiveaway(ev)) && !ev.needs_review && !ev.needsReview;
  }
  function isFreeFood(ev) { return isPublic(ev) && hasFood(ev); }
  function isGiveawayOnly(ev) { return isPublic(ev) && !hasFood(ev); }
  function isDeadlineOnly(ev) {
    if (!hasGiveaway(ev)) return false;
    var start = toKst(ev.startAt);
    var deadline = toKst((ev.registration || {}).deadline);
    return !!start && !!deadline && start.getTime() === deadline.getTime();
  }
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
  function audienceOf(ev, mark) {
    var a = ev && ev.audience;
    if (a && typeof a.text === 'string' && a.text.trim()) {
      var who = a.text.trim();
      return a.basis === 'inferred' && typeof mark === 'function' ? mark(who) : who;
    }
    return ev && ev.eligibility ? String(ev.eligibility) : '';
  }

  var INSTAGRAM_POST = /^https:\/\/www\.instagram\.com\/(?:p|reel)\/[A-Za-z0-9_-]{5,20}\/$/;
  function sourceLink(ev) {
    var sources = ((ev && ev.sources) || []).filter(function (src) { return src && typeof src.url === 'string' && src.url; });
    var notice = sources.filter(function (src) { return src.type === 'kaist_public' || src.type === 'manual'; })[0];
    var post = sources.filter(function (src) { return src.type === 'instagram' && INSTAGRAM_POST.test(src.url); })[0];
    var link = notice || post;
    return link ? { type: link.type, url: link.url } : null;
  }
  var SOURCE_GROUPS = [['instagram', 'instagram'], ['tip', 'tip'], ['dooray', 'mail'], ['dooray_mailbox', 'mail'],
    ['portal', 'portal'], ['kaist_public', 'public'], ['manual', 'manual']];
  function sourceGroup(ev) {
    var types = ((ev && ev.sources) || []).map(function (src) { return src && src.type; });
    for (var i = 0; i < SOURCE_GROUPS.length; i++) {
      if (types.indexOf(SOURCE_GROUPS[i][0]) >= 0) return SOURCE_GROUPS[i][1];
    }
    return '';
  }

  var MEETING_HOST = /(^|\.)(zoom\.us|zoom\.com|zoomgov\.com|meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|webex\.com)$/i;
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

  var DISHES = [
    ['burger', /버거|burger/i],
    ['pizza', /피자|pizza/i],
    ['chicken', /치킨|chicken/i],
    ['sushi', /초밥|스시|sushi/i],
    ['sandwich', /샌드위치|sandwich/i],
    ['lunchbox', /도시락|lunch ?box|bento/i],
    ['bbq', /바비큐|바베큐|소고기|삼겹|BBQ|barbecue/i],
    ['kimbap', /김밥|주먹밥|kimbap/i],
    ['bread', /빵|베이커리|bakery|bread|pastr/i],
    ['cake', /케이크|cake/i],
    ['coffee', /커피|coffee/i],
    ['drink', /음료|드링크|주스|콜라|사이다|drinks?\b|beverage|juice/i],
    ['snack', /간식|과자|스낵|snacks?\b/i],
    ['refreshment', /다과|refreshments?/i],
    ['coupon', /쿠폰|기프티콘|coupon|voucher/i]
  ];
  var LIGHT = { coffee: 1, drink: 1, snack: 1, refreshment: 1 };
  var GENERAL = [
    ['dinner', /석식|저녁|dinner/i],
    ['lunch', /점심|중식|lunch/i],
    ['catering', /케이터링|뷔페|catering|buffet/i],
    ['meal', /식사|meals?\b/i]
  ];
  var TYPE_DISH = { meal: 'meal', lunchbox: 'lunchbox', snack: 'snack', refreshment: 'refreshment',
    beverage: 'drink', coupon: 'coupon' };
  function dishes(ev) {
    if (!hasFood(ev)) return [];
    var food = ev.food || {};
    var text = String(food.description || '');
    var found = DISHES.filter(function (row) { return row[1].test(text); }).map(function (row) { return row[0]; });
    if (found.indexOf('chicken') >= 0) found = found.filter(function (key) { return key !== 'bbq'; });
    found = found.slice(0, 2);
    var general = GENERAL.filter(function (row) { return row[1].test(text); }).map(function (row) { return row[0]; })[0];
    if (general && (!found.length || (found.length === 1 && LIGHT[found[0]]))) found.unshift(general);
    if (!found.length) found.push(TYPE_DISH[food.type] || 'food');
    return found.map(function (key) { return { key: key }; });
  }
  function dishLabel(ev, t) {
    return dishes(ev).map(function (d) { return t('dish.' + d.key, d.key); }).join(' · ');
  }
  function inLang(text, lang) {
    var hangul = /[가-힣]/.test(String(text || ''));
    return lang === 'en' ? !hangul : hangul;
  }

  global.BabdodukFreeFood = {
    dishes: dishes,
    dishLabel: dishLabel,
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
    sourceLink: sourceLink,
    sourceGroup: sourceGroup,
    signUp: signUp
  };
})(window);
