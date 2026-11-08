// One compact JSON file per law, read by the site's chat assistant.
import { allLaws, displayName, passedByLabel, controlLabel, partyLineLabel } from "../../../lib/data.js";

export function getStaticPaths() {
  return allLaws().map((l) => ({ params: { id: l.id }, props: { l } }));
}

export function GET({ props: { l } }) {
  const body = {
    id: l.id, url: `/laws/${l.id}/`, title: l.title, public_law: l.public_law, bill: l.bill,
    enacted: l.enacted, congress: l.congress, topic: l.policy_area ?? null, sponsor: l.sponsor ?? null,
    signed_by: l.president?.name ?? null, how_it_became_law: l.became_law ?? null,
    passed_by: passedByLabel(l), chamber_control: controlLabel(l), one_party_alone: partyLineLabel(l) ?? null,
    summary: l.summary ? { headline: l.summary.headline, what_it_does: l.summary.what_it_does, who_it_affects: l.summary.who_it_affects } : null,
    official_summary: (l.official_summary || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 4000) || null,
    congress_gov_url: l.congress_gov_url ?? null,
    votes: (l.votes || []).map((v) => ({
      chamber: v.chamber, date: v.date, question: v.question, result: v.result, yea: v.yea, nay: v.nay, by_party: v.by_party,
      // [name, party, state, vote, politician page id]
      members: v.members.map((m) => [displayName(m.name), m.party, m.state, m.vote, m.bioguide || null]),
    })),
  };
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}
