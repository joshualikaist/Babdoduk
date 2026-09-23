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
  function isPublic(ev) { return tri((ev.food || {}).provided) === 'true' && !ev.needs_review && !ev.needsReview; }
  function eventEnd(ev) { return toKst(ev.endAt) || toKst(ev.startAt); }
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
