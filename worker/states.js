// Official sources for state law, used to limit the chat assistant's web search.
// Each state lists its government portal and legislature/statute sites (subdomains
// are included automatically). NATIONAL sources carry every state's code.
export const NATIONAL = ["law.justia.com", "law.cornell.edu", "ncsl.org"];

export const STATE_SOURCES = {
  AL: ["Alabama", "alabama.gov", "legislature.state.al.us"],
  AK: ["Alaska", "alaska.gov", "akleg.gov"],
  AZ: ["Arizona", "az.gov", "azleg.gov"],
  AR: ["Arkansas", "arkansas.gov", "arkleg.state.ar.us"],
  CA: ["California", "ca.gov"],
  CO: ["Colorado", "colorado.gov"],
  CT: ["Connecticut", "ct.gov"],
  DE: ["Delaware", "delaware.gov"],
  FL: ["Florida", "myflorida.com", "flsenate.gov", "leg.state.fl.us", "myfloridahouse.gov"],
  GA: ["Georgia", "georgia.gov", "ga.gov"],
  HI: ["Hawaii", "hawaii.gov"],
  ID: ["Idaho", "idaho.gov"],
  IL: ["Illinois", "illinois.gov", "ilga.gov"],
  IN: ["Indiana", "in.gov"],
  IA: ["Iowa", "iowa.gov"],
  KS: ["Kansas", "kansas.gov", "kslegislature.gov", "kslegislature.org", "ksrevisor.gov"],
  KY: ["Kentucky", "ky.gov"],
  LA: ["Louisiana", "la.gov"],
  ME: ["Maine", "maine.gov"],
  MD: ["Maryland", "maryland.gov"],
  MA: ["Massachusetts", "mass.gov", "malegislature.gov"],
  MI: ["Michigan", "michigan.gov", "legislature.mi.gov"],
  MN: ["Minnesota", "mn.gov"],
  MS: ["Mississippi", "ms.gov"],
  MO: ["Missouri", "mo.gov"],
  MT: ["Montana", "mt.gov"],
  NE: ["Nebraska", "nebraska.gov", "nebraskalegislature.gov"],
  NV: ["Nevada", "nv.gov", "leg.state.nv.us"],
  NH: ["New Hampshire", "nh.gov", "gencourt.state.nh.us"],
  NJ: ["New Jersey", "nj.gov", "njleg.gov", "njleg.state.nj.us"],
  NM: ["New Mexico", "nm.gov", "nmlegis.gov"],
  NY: ["New York", "ny.gov", "nysenate.gov", "nyassembly.gov"],
  NC: ["North Carolina", "nc.gov", "ncleg.gov"],
  ND: ["North Dakota", "nd.gov", "ndlegis.gov"],
  OH: ["Ohio", "ohio.gov"],
  OK: ["Oklahoma", "oklahoma.gov", "oklegislature.gov", "oksenate.gov", "okhouse.gov"],
  OR: ["Oregon", "oregon.gov", "oregonlegislature.gov"],
  PA: ["Pennsylvania", "pa.gov", "palegis.us", "legis.state.pa.us"],
  RI: ["Rhode Island", "ri.gov", "rilegislature.gov"],
  SC: ["South Carolina", "sc.gov", "scstatehouse.gov"],
  SD: ["South Dakota", "sd.gov", "sdlegislature.gov"],
  TN: ["Tennessee", "tn.gov"],
  TX: ["Texas", "texas.gov"],
  UT: ["Utah", "utah.gov"],
  VT: ["Vermont", "vermont.gov"],
  VA: ["Virginia", "virginia.gov"],
  WA: ["Washington", "wa.gov"],
  WV: ["West Virginia", "wv.gov", "wvlegislature.gov"],
  WI: ["Wisconsin", "wisconsin.gov"],
  WY: ["Wyoming", "wyo.gov", "wyoleg.gov"],
  DC: ["District of Columbia", "dc.gov", "dccouncil.gov"],
  PR: ["Puerto Rico", "pr.gov"],
};

const AMBIGUOUS = new Set(["OK", "IN", "ME", "OR", "HI", "ID", "PA", "DE", "MA", "CO"]);

// States named in some text: full names, plus uppercase postal codes that aren't also common words;
// "Washington" counts as the state unless it's "Washington, D.C." / "DC".
export function statesIn(text) {
  const t = ` ${String(text).toLowerCase().replace(/[^a-z.]+/g, " ")} `;
  const found = new Set();
  for (const [code, [name]] of Object.entries(STATE_SOURCES)) {
    const n = name.toLowerCase();
    if (code === "WA") {
      if (/ washington state | state of washington /.test(t) || (t.includes(" washington ") && !/ washington d ?c| washington dc /.test(t.replace(/\./g, " ").replace(/ d c /g, " dc ")))) found.add(code);
      continue;
    }
    if (code === "VA" && /west virginia/.test(t) && !t.replace(/west virginia/g, "").includes(" virginia ")) continue;
    if (code === "KS" && t.includes(" arkansas ") && !t.replace(/arkansas/g, "").includes("kansas")) continue;
    if (t.includes(` ${n} `)) found.add(code);
  }
  // Uppercase postal codes ("does MD allow ..."), skipping ones that are also common words.
  for (const m of String(text).matchAll(/\b([A-Z]{2})\b/g)) if (STATE_SOURCES[m[1]] && !AMBIGUOUS.has(m[1])) found.add(m[1]);
  if (/ d ?c | washington d ?c /.test(t.replace(/\./g, " ").replace(/ d c /g, " dc "))) found.add("DC");
  return [...found];
}

// Domains the web search may use for these states (national legal-code sites always included).
export function domainsFor(codes) {
  const out = new Set(NATIONAL);
  for (const c of codes) (STATE_SOURCES[c] || []).slice(1).forEach((d) => out.add(d));
  return [...out];
}
