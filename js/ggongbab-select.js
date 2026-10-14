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
    futurePublic: futurePublic
  };
})(window);
