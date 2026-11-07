// Compact list of every law, loaded by the home page for search and filtering.
import { allLaws, lawColor, passedByLabel, controlLabel, partyLineLabel, formatDate } from "../lib/data.js";

export function GET() {
  const rows = allLaws().map((l) => {
    const c = lawColor(l.party_color);
    return [
      l.id, l.title, l.public_law, formatDate(l.enacted), l.policy_area ?? "", l.summary?.headline ?? "",
      l.party_color?.side ?? "none", l.president?.id ?? "", l.president?.name ?? "", l.congress,
      l.recorded_vote ? 1 : 0, c.bg, c.fg, passedByLabel(l), partyLineLabel(l) ?? "", controlLabel(l), l.bill, l.party_color?.d_yeas ?? 0, l.party_color?.r_yeas ?? 0,
      l.president?.party?.[0] ?? "", l.control ?? {},
    ];
  });
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json" } });
}
