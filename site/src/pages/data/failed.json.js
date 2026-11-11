// Compact list of measures that failed a floor vote, read by the site's chat assistant.
import { allFailed, failedLabel, supportLabel, failedPartyLine } from "../../lib/data.js";

export function GET() {
  const rows = allFailed().map((i) => {
    const v = i.votes.at(-1);
    return {
      id: i.id, url: `/did-not-pass/${i.id}/`, bill: i.bill, title: i.title, failed_on: i.failed_on,
      congress: i.congress, topic: i.policy_area ?? "", headline: i.summary?.headline ?? "",
      what_happened: failedLabel(i), backed_by: supportLabel(i), one_party_only: failedPartyLine(i),
      later_became_law: i.later_became_law ? `/laws/${i.later_became_law.id}/` : null,
      last_vote: { chamber: v.chamber, date: v.date, question: v.question, yea: v.yea, nay: v.nay, by_party: v.by_party },
    };
  });
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json" } });
}
