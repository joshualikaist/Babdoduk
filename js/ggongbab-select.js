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

  // The source a listing links to, or null: a KAIST notice or Babdoduk's own entry, else the
  // Instagram post itself, and only in its canonical permalink form (2026-10-31). Mail, the Portal
  // and reader tips never link. Pages still pass the URL through their own safeHref.
  var INSTAGRAM_POST = /^https:\/\/www\.instagram\.com\/(?:p|reel)\/[A-Za-z0-9_-]{5,20}\/$/;
  function sourceLink(ev) {
    var sources = ((ev && ev.sources) || []).filter(function (src) { return src && typeof src.url === 'string' && src.url; });
    var notice = sources.filter(function (src) { return src.type === 'kaist_public' || src.type === 'manual'; })[0];
    var post = sources.filter(function (src) { return src.type === 'instagram' && INSTAGRAM_POST.test(src.url); })[0];
    var link = notice || post;
    return link ? { type: link.type, url: link.url } : null;
  }
  // The one group a listing is credited to (data/content/labels.json sourceLabels): where it was
  // found when that is public (an Instagram post, a reader tip), else the existing order.
  var SOURCE_GROUPS = [['instagram', 'instagram'], ['tip', 'tip'], ['dooray', 'mail'], ['dooray_mailbox', 'mail'],
    ['portal', 'portal'], ['kaist_public', 'public'], ['manual', 'manual']];
  function sourceGroup(ev) {
    var types = ((ev && ev.sources) || []).map(function (src) { return src && src.type; });
    for (var i = 0; i < SOURCE_GROUPS.length; i++) {
      if (types.indexOf(SOURCE_GROUPS[i][0]) >= 0) return SOURCE_GROUPS[i][1];
    }
    return '';
  }

  global.BabdodukFreeFood = {
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
    sourceGroup: sourceGroup
  };
})(window);
