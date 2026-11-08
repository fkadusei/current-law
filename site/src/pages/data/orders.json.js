// Every executive order: [number, title, signed, president, headline].
import { executiveOrders } from "../../lib/data.js";
export function GET() {
  const rows = executiveOrders().map((e) => [e.number, e.title, e.signed, e.president?.name ?? "", e.summary?.headline ?? e.abstract?.slice(0, 200) ?? ""]);
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json" } });
}
