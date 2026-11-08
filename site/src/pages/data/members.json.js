// Every member of Congress on the site: [page id, name, party, state, chamber, district, congresses].
import { membersIndex, displayName } from "../../lib/data.js";
export function GET() {
  const rows = membersIndex().filter((m) => m.bioguide)
    .map((m) => [m.bioguide, displayName(m.name), m.party, m.state, m.chamber, m.district ?? "", m.congresses ?? []]);
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json" } });
}
