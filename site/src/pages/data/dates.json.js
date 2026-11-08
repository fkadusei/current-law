// Every law with its enactment date, oldest first: [id, enacted, title, headline, side, signer].
import { allLaws } from "../../lib/data.js";
export function GET() {
  const rows = allLaws().slice().sort((a, b) => (a.enacted || "").localeCompare(b.enacted || ""))
    .map((l) => [l.id, l.enacted, l.title, l.summary?.headline ?? "", l.party_color?.side ?? "none", l.president?.name ?? ""]);
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json" } });
}
