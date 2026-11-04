/* Where an event sits on the campus map (docs/CAMPUS_MAP.md): the first building code in its building
   or place name, else the longest building name or alias found there; never a guess. The same rule as
   scripts/campus3d/buildings.py place(), checked on the same cases (tests/test_campus_buildings.py). */
const CODE = /(?:^|[^A-Za-z0-9])([EWNS]\d{1,2}(?:-\d)?)(?![0-9])/g;

export function place(location, table) {
  const loc = location || {};
  const text = [loc.building, loc.name].map((s) => String(s || '')).join(' ');
  const known = new Map();
  table.buildings.forEach((row) => known.set(row.code, true));
  table.unplaced.forEach((row) => known.set(row.code, false));
  const codes = [];
  for (const m of text.matchAll(CODE)) if (!codes.includes(m[1])) codes.push(m[1]);
  if (codes.length) {
    const first = codes[0];
    return { code: known.has(first) ? first : null, placed: known.get(first) === true, others: codes.length - 1 };
  }
  let best = null;
  for (const row of table.buildings.concat(table.unplaced)) {
    for (const name of [row.name, ...row.aliases]) {
      if (name !== row.code && text.includes(name) && (!best || name.length > best[0].length)) best = [name, row.code];
    }
  }
  if (best) return { code: best[1], placed: known.get(best[1]) === true, others: 0 };
  return { code: null, placed: false, others: 0 };
}
