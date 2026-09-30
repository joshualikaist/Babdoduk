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
  // Unknown food is neither a positive nor a negative claim: it is not shown.
  function isPublic(ev) {
    return (!ev.contentType || ev.contentType === 'free_food') &&
      tri((ev.food || {}).provided) === 'true' && !ev.needs_review && !ev.needsReview;
  }
  // With no end time ("11:30 ~ 소진 시까지"), an event stays current for the same window
  // the feed keeps it after it starts (GGONGBAB_EXPIRED_GRACE_HOURS, 3 h), so a hand-out
  // that began before anyone saw the notice is still listed while it may be running.
  var OPEN_ENDED_HOURS = 3;
  function eventEnd(ev) {
    var end = toKst(ev.endAt);
    if (end) return end;
    var start = toKst(ev.startAt);
    return start ? new Date(start.getTime() + OPEN_ENDED_HOURS * 3600000) : null;
  }
  function isUpcoming(ev, now) {
    var end = eventEnd(ev);
    return !end || end >= now;
  }
  function byStart(a, b) { return String(a.startAt || '').localeCompare(String(b.startAt || '')); }
  function todayUpcoming(events, now) {
    return (events || []).filter(function (ev) {
      var s = toKst(ev.startAt);
      return isPublic(ev) && s && ymd(s) === ymd(now) && isUpcoming(ev, now);
    }).sort(byStart);
  }
  function futurePublic(events, now) {
    return (events || []).filter(function (ev) {
      var s = toKst(ev.startAt);
      return isPublic(ev) && s && ymd(s) >= ymd(now) && isUpcoming(ev, now);
    }).sort(byStart);
  }

  global.BabdodukFreeFood = {
    toKst: toKst,
    nowKst: nowKst,
    ymd: ymd,
    tri: tri,
    isPublic: isPublic,
    eventEnd: eventEnd,
    isUpcoming: isUpcoming,
    todayUpcoming: todayUpcoming,
    futurePublic: futurePublic
  };
})(window);
