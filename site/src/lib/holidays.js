// US federal holidays (5 U.S.C. 6103), with the law behind each one.
// Used by the calendar page and the chat assistant.

const nth = (y, m, weekday, n) => { // nth weekday (0=Sun) of month m (0-based); n=-1 for last
  if (n > 0) { const d = new Date(Date.UTC(y, m, 1)); d.setUTCDate(1 + ((weekday - d.getUTCDay() + 7) % 7) + 7 * (n - 1)); return d; }
  const d = new Date(Date.UTC(y, m + 1, 0)); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() - weekday + 7) % 7)); return d;
};
const fixed = (y, m, day) => new Date(Date.UTC(y, m, day));
const iso = (d) => d.toISOString().slice(0, 10);
// When a fixed-date holiday falls on a weekend, federal workers get the nearest weekday off.
const observed = (d) => { const w = d.getUTCDay(); const o = new Date(d); if (w === 6) o.setUTCDate(d.getUTCDate() - 1); if (w === 0) o.setUTCDate(d.getUTCDate() + 1); return o; };

export const HOLIDAYS = [
  { key: "new-year", name: "New Year's Day", rule: "January 1", date: (y) => fixed(y, 0, 1), fixedDate: true,
    about: "One of the first four federal holidays, set by Congress in 1870 for federal workers in Washington, D.C., and later extended nationwide.", law: "Act of June 28, 1870" },
  { key: "mlk", name: "Birthday of Martin Luther King, Jr.", rule: "Third Monday in January", date: (y) => nth(y, 0, 1, 3), since: 1986,
    about: "Honors the civil rights leader. Signed into law by President Reagan in 1983 and first observed in 1986.", law: "Public Law 98-144 (1983)" },
  { key: "inauguration", name: "Inauguration Day", rule: "January 20 after each presidential election (Washington, D.C. area only)", date: (y) => (y - 2021) % 4 === 0 ? fixed(y, 0, 20) : null, fixedDate: true, local: true,
    about: "A paid holiday only for federal workers in and around Washington, D.C., in the years a President is sworn in. If it falls on a Sunday, the holiday moves to Monday.", law: "5 U.S.C. 6103(c)" },
  { key: "washington", name: "Washington's Birthday (Presidents' Day)", rule: "Third Monday in February", date: (y) => nth(y, 1, 1, 3),
    about: "Created to honor George Washington. Since 1971 it falls on a Monday, and it's often called Presidents' Day, though its legal name is still Washington's Birthday.", law: "Act of 1879; moved to a Monday by the Uniform Monday Holiday Act, Public Law 90-363 (1968)" },
  { key: "memorial", name: "Memorial Day", rule: "Last Monday in May", date: (y) => nth(y, 4, 1, -1),
    about: "Honors members of the military who died in service. Moved to the last Monday in May starting in 1971.", law: "Uniform Monday Holiday Act, Public Law 90-363 (1968)" },
  { key: "juneteenth", name: "Juneteenth National Independence Day", rule: "June 19", date: (y) => fixed(y, 5, 19), fixedDate: true, since: 2021,
    about: "Marks June 19, 1865, when news of the end of slavery reached Galveston, Texas. The newest federal holiday, signed by President Biden in 2021.", law: "Public Law 117-17 (2021)", lawId: "pl-117-17" },
  { key: "independence", name: "Independence Day", rule: "July 4", date: (y) => fixed(y, 6, 4), fixedDate: true,
    about: "Celebrates the Declaration of Independence, adopted July 4, 1776. One of the first four federal holidays.", law: "Act of June 28, 1870" },
  { key: "labor", name: "Labor Day", rule: "First Monday in September", date: (y) => nth(y, 8, 1, 1),
    about: "Honors American workers and the labor movement. Made a federal holiday in 1894.", law: "Act of June 28, 1894" },
  { key: "columbus", name: "Columbus Day", rule: "Second Monday in October", date: (y) => nth(y, 9, 1, 2),
    about: "Its legal name is Columbus Day. Many states and cities also mark the day as Indigenous Peoples' Day.", law: "Uniform Monday Holiday Act, Public Law 90-363 (1968)" },
  { key: "veterans", name: "Veterans Day", rule: "November 11", date: (y) => fixed(y, 10, 11), fixedDate: true,
    about: "Began as Armistice Day, marking the end of World War I fighting on November 11, 1918. Renamed in 1954 to honor all veterans.", law: "Act of May 13, 1938; renamed by Public Law 83-380 (1954)" },
  { key: "thanksgiving", name: "Thanksgiving Day", rule: "Fourth Thursday in November", date: (y) => nth(y, 10, 4, 4),
    about: "A national day of thanks. Congress fixed it to the fourth Thursday in November in 1941.", law: "Public Law 77-379 (1941)" },
  { key: "christmas", name: "Christmas Day", rule: "December 25", date: (y) => fixed(y, 11, 25), fixedDate: true,
    about: "One of the first four federal holidays, set by Congress in 1870.", law: "Act of June 28, 1870" },
];

// All holidays in a year: [{ key, name, date, observed (if different), ... }]
export function holidaysIn(year) {
  const out = [];
  for (const h of HOLIDAYS) {
    if (h.since && year < h.since) continue;
    const d = h.date(year);
    if (!d) continue;
    let obs = h.fixedDate ? observed(d) : d;
    if (h.key === "inauguration" && d.getUTCDay() === 0) obs = new Date(Date.UTC(year, 0, 21));
    if (h.key === "inauguration" && d.getUTCDay() === 6) obs = d; // no holiday moved for a Saturday
    out.push({ key: h.key, name: h.name, rule: h.rule, about: h.about, law: h.law, lawId: h.lawId ?? null, local: !!h.local,
      date: iso(d), observed: iso(obs) !== iso(d) ? iso(obs) : null });
  }
  return out;
}

// Holidays (by actual or observed date) between two YYYY-MM-DD dates, inclusive.
export function holidaysBetween(from, to) {
  const out = [];
  for (let y = Number(from.slice(0, 4)); y <= Number(to.slice(0, 4)); y++)
    for (const h of holidaysIn(y)) if ((h.date >= from && h.date <= to) || (h.observed && h.observed >= from && h.observed <= to)) out.push(h);
  return out;
}
