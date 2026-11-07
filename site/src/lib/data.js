// Loads the pipeline's output (data/build) at build time.
import fs from "node:fs";
import path from "node:path";

const BUILD = path.resolve(process.cwd(), "../data/build");
const read = (p) => JSON.parse(fs.readFileSync(path.join(BUILD, p), "utf8"));

let _laws;
export function allLaws() {
  if (_laws) return _laws;
  const dir = path.join(BUILD, "laws");
  _laws = [];
  for (const congress of fs.readdirSync(dir)) {
    const cdir = path.join(dir, congress);
    if (!fs.statSync(cdir).isDirectory()) continue;
    for (const f of fs.readdirSync(cdir)) {
      _laws.push(JSON.parse(fs.readFileSync(path.join(cdir, f), "utf8")));
    }
  }
  _laws.sort((a, b) => (b.enacted || "").localeCompare(a.enacted || ""));
  return _laws;
}

export const executiveOrders = () =>
  read("executive_orders.json").sort((a, b) => (b.signed || "").localeCompare(a.signed || ""));

export const membersIndex = () => read("members/index.json");

// "ROGERS, Harold Dallas (Hal)" -> "Hal Rogers"
export function displayName(raw) {
  if (!raw) return "Unknown";
  const i = raw.indexOf(",");
  const last = (i < 0 ? raw : raw.slice(0, i)).trim();
  let rest = i < 0 ? "" : raw.slice(i + 1);
  const SUFFIX = /(?:^|[\s,])(Jr\.?|Sr\.?|II|III|IV)(?=$|[\s,])/;
  const sm = rest.match(SUFFIX);
  const suffix = sm ? sm[1].replace(/^(Jr|Sr)$/, "$1.") : "";
  if (sm) rest = rest.replace(SUFFIX, " ");
  rest = rest.replace(/,/g, " ").trim();
  const nick = rest.match(/\(([^)]+)\)/);
  const first = nick ? nick[1] : rest.split(/\s+/)[0];
  const title = (s) => s.toLowerCase().replace(/(^|[\s'-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())
    .replace(/\bMc(\p{L})/gu, (m, a) => "Mc" + a.toUpperCase());
  return `${title(first)} ${title(last)}${suffix ? " " + suffix : ""}`.trim();
}

export const PARTY_NAME = { R: "Republican", D: "Democratic", I: "Independent", Other: "Other" };
export const CHAMBER_NAME = { House: "House", Senate: "Senate" };

export function congressLabel(n) {
  const start = 1789 + 2 * (n - 1);
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${n}${s} Congress (${start}–${start + 1})`;
}

export function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00Z");
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

// Color for a law: red or blue by the party that supplied most yes votes,
// darker the more one-sided. Gray when there was no recorded vote.
export function lawColor(pc) {
  if (!pc || pc.side === "tie") return { cls: "none", bg: "var(--neutral-bg)", fg: "var(--text)" };
  const hue = pc.side === "R" ? 356 : 216;
  const light = Math.round(82 - pc.shade * 46); // 82% (even split) -> 36% (one party only)
  return {
    cls: pc.side,
    bg: `hsl(${hue} 72% ${light}%)`,
    fg: light < 58 ? "#fff" : "#111",
  };
}

export function passedByLabel(law) {
  const pc = law.party_color;
  if (!law.recorded_vote) return "Passed without a recorded vote";
  if (!pc || pc.side === "tie") return "Passed with equal support from both parties";
  return `Passed by a ${PARTY_NAME[pc.side]} majority (${Math.round(pc.share * 100)}% of yes votes)`;
}

export function controlLabel(law) {
  const c = law.control || {};
  return ["House", "Senate"].filter((ch) => c[ch]).map((ch) => `${PARTY_NAME[c[ch]]} ${ch}`).join(" · ");
}

export function partyLineLabel(law) {
  const pl = law.party_color?.party_line;
  if (pl === "D") return "No Republican voted yes";
  if (pl === "R") return "No Democrat voted yes";
  return null;
}

export function slugPresident(p) { return p?.id; }

export function lawTitle(law) {
  return law.summary?.headline && law.title?.length > 140 ? law.title.slice(0, 137) + "…" : law.title;
}

// Every recorded vote a member cast on a law, keyed by bioguide id.
let _records;
export function memberRecords() {
  if (_records) return _records;
  _records = new Map();
  for (const law of allLaws()) {
    for (const v of law.votes) {
      for (const m of v.members) {
        if (!m.bioguide) continue;
        if (!_records.has(m.bioguide)) _records.set(m.bioguide, []);
        _records.get(m.bioguide).push({ law, chamber: v.chamber, vote: m.vote });
      }
    }
  }
  return _records;
}

export const PRESIDENT_INFO = {
  nixon: { years: "1969–1974" }, ford: { years: "1974–1977" }, carter: { years: "1977–1981" },
  reagan: { years: "1981–1989" }, "bush-hw": { years: "1989–1993" }, clinton: { years: "1993–2001" },
  "bush-w": { years: "2001–2009" }, obama: { years: "2009–2017" }, "trump-1": { years: "2017–2021", note: "First term" },
  biden: { years: "2021–2025" }, "trump-2": { years: "2025–", note: "Second term" },
};
