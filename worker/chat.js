// "Ask Current Law" chat assistant: answers questions from the site's own data.
// Cost safety: per-visitor hourly limit plus a hard daily spending cap, both kept
// in one Durable Object (ChatGuard). When the cap is reached the chat pauses until
// the next day (UTC); the rest of the site is unaffected.
import Anthropic from "@anthropic-ai/sdk";
import { DurableObject } from "cloudflare:workers";
import { holidaysBetween } from "../site/src/lib/holidays.js";

const MODEL = "claude-haiku-5-5";
const PRICE_IN = 0.10 / 1e6, PRICE_OUT = 0.50 / 1e6; // $ per token (Haiku 5.5, prompts under 100K)
const PER_VISITOR_PER_HOUR = 20;
const MAX_STEPS = 5;

const SYSTEM = `You are the help assistant on Current Law (usacurrentlaw.org), a nonpartisan site that explains every US federal law and executive order in plain English, shows how each member of Congress voted, and who signed it.

How to answer:
- Use the tools to look things up. Only state facts that come from the tools; never invent laws, votes or numbers.
- Write in plain, friendly English at about an 8th-grade level. Keep answers short: usually 2 to 5 sentences or a short list.
- Always link to the relevant page on this site with Markdown links using the "url" the tools return, for example [CHIPS and Science Act](/laws/pl-117-167/).
- Be strictly neutral. Describe what laws do and how people voted; never say whether a law, party or politician is good or bad, and never tell anyone how to vote.
- The site currently covers laws from 2013 onward (more years are being added) and executive orders from 1994 onward. Bills, resolutions and motions that failed a recorded floor vote since 2013 are in the "Didn't pass" section: use search_failed for those. If something is outside that, or isn't federal (for example a state law), say so plainly.
- For questions about dates ("what passed last March", "on my birthday"), use list_by_date and link its calendar_url. Today's date is given at the end of these instructions.
- If someone asks who represents them, ask for their state, then look up members by state.
- For anything not about US federal laws, votes, Presidents or executive orders, politely say you can only help with those.`;

const TOOLS = [
  { name: "search_laws", description: "Search federal laws on the site by keywords (title, topic, summary, bill or public law number). Returns up to 8 matches, newest first among equal matches.",
    input_schema: { type: "object", properties: {
      query: { type: "string", description: "Keywords, e.g. 'veterans health' or 'CHIPS'." },
      president: { type: "string", description: "Optional: last name of the signing President, e.g. 'Biden'." },
      year: { type: "integer", description: "Optional: year enacted." } }, required: ["query"], additionalProperties: false } },
  { name: "get_law", description: "Get details of one law: summary, who signed it, which party's votes passed it, vote totals by party. Pass 'politician' (a name and/or state) to also get how matching members voted.",
    input_schema: { type: "object", properties: {
      id: { type: "string", description: "Law id from search_laws, e.g. 'pl-118-31'." },
      politician: { type: "string", description: "Optional: member name or two-letter state, e.g. 'Pelosi' or 'OH'." } }, required: ["id"], additionalProperties: false } },
  { name: "list_by_date", description: "List the federal holidays, laws enacted and executive orders signed on a day or within a date range (inclusive). Use for questions like 'what passed on July 4, 2024' or 'laws signed in March 2023'.",
    input_schema: { type: "object", properties: {
      from: { type: "string", description: "Start date, YYYY-MM-DD." },
      to: { type: "string", description: "End date, YYYY-MM-DD. Same as from for a single day." } }, required: ["from", "to"], additionalProperties: false } },
  { name: "find_politicians", description: "Find members of Congress on the site by name or state. Returns their page url, party, state and chamber.",
    input_schema: { type: "object", properties: { query: { type: "string", description: "A name, a two-letter state code, or a state name." } }, required: ["query"], additionalProperties: false } },
  { name: "search_failed", description: "Search bills, resolutions and motions that failed a recorded House or Senate floor vote (voted down, blocked by filibuster, tabled, veto sustained). Returns up to 8 matches with how it failed, which party backed it and the vote by party.",
    input_schema: { type: "object", properties: {
      query: { type: "string", description: "Keywords or a bill number, e.g. 'impeach Hegseth' or 'H.R. 9340'. Empty for the most recent." },
      year: { type: "integer", description: "Optional: year of the failed vote." } }, required: ["query"], additionalProperties: false } },
  { name: "search_executive_orders", description: "Search executive orders by keywords, optionally by President's last name. Returns up to 8 matches.",
    input_schema: { type: "object", properties: {
      query: { type: "string" }, president: { type: "string" } }, required: ["query"], additionalProperties: false } },
];

const STATES = { alabama: "AL", alaska: "AK", arizona: "AZ", arkansas: "AR", california: "CA", colorado: "CO", connecticut: "CT", delaware: "DE", florida: "FL", georgia: "GA", hawaii: "HI", idaho: "ID", illinois: "IL", indiana: "IN", iowa: "IA", kansas: "KS", kentucky: "KY", louisiana: "LA", maine: "ME", maryland: "MD", massachusetts: "MA", michigan: "MI", minnesota: "MN", mississippi: "MS", missouri: "MO", montana: "MT", nebraska: "NE", nevada: "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", ohio: "OH", oklahoma: "OK", oregon: "OR", pennsylvania: "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", tennessee: "TN", texas: "TX", utah: "UT", vermont: "VT", virginia: "VA", washington: "WA", "west virginia": "WV", wisconsin: "WI", wyoming: "WY", "district of columbia": "DC", "puerto rico": "PR", guam: "GU" };
const STOP = new Set("a an and are did do does for from how in is it law laws of on or the to vote voted was what when which who with act bill".split(" "));
const words = (s) => (s || "").toLowerCase().match(/[a-z0-9-]+/g)?.filter((w) => !STOP.has(w)) ?? [];

let cache = {};
async function asset(env, path) {
  if (cache[path]) return cache[path];
  const res = await env.ASSETS.fetch(new Request(new URL(path, "https://assets.local")));
  if (!res.ok) return null;
  const data = await res.json();
  if (!path.startsWith("/data/laws/")) cache[path] = data;
  return data;
}

function score(terms, fields) {
  let s = 0;
  for (const t of terms) fields.forEach(([text, w]) => { if (text.includes(t)) s += w; });
  return s;
}

function stateFilter(q) {
  const lower = q.toLowerCase().trim();
  if (STATES[lower]) return STATES[lower];
  if (/^[A-Za-z]{2}$/.test(q.trim())) return q.trim().toUpperCase();
  return null;
}

async function runTool(env, name, input) {
  if (name === "search_laws") {
    const rows = await asset(env, "/laws-index.json");
    const terms = words(input.query);
    const pres = (input.president || "").toLowerCase();
    const hits = rows.filter((r) => (!pres || r[8].toLowerCase().includes(pres)) && (!input.year || r[3].includes(String(input.year))))
      .map((r) => ({ r, s: score(terms, [[r[1].toLowerCase(), 3], [r[5].toLowerCase(), 2], [r[4].toLowerCase(), 1], [`${r[2]} ${r[16]}`.toLowerCase(), 4]]) }))
      .filter((h) => h.s > 0 || !terms.length).sort((a, b) => b.s - a.s).slice(0, 8);
    return hits.map(({ r }) => ({ id: r[0], url: `/laws/${r[0]}/`, title: r[1], public_law: r[2], enacted: r[3], topic: r[4], headline: r[5] || null, signed_by: r[8], passed_by: r[13] }));
  }
  if (name === "get_law") {
    const id = String(input.id).replace(/[^a-z0-9-]/gi, "");
    const law = await asset(env, `/data/laws/${id}.json`);
    if (!law) return { error: "No law with that id. Use search_laws first." };
    const q = (input.politician || "").trim();
    const st = q ? stateFilter(q) : null;
    const nameTerms = st ? [] : words(q);
    law.votes = law.votes.map((v) => {
      const { members, ...rest } = v;
      if (!q) return rest;
      const matches = members.filter(([n, , s]) => (st ? s === st : nameTerms.every((t) => n.toLowerCase().includes(t)))).slice(0, 60)
        .map(([n, p, s, vote, bio]) => ({ name: n, party: p, state: s, vote, url: bio ? `/politicians/${bio}/` : null }));
      return { ...rest, matching_members: matches };
    });
    return law;
  }
  if (name === "list_by_date") {
    const from = String(input.from).slice(0, 10), to = String(input.to).slice(0, 10);
    const [laws, orders] = await Promise.all([asset(env, "/data/dates.json"), asset(env, "/data/orders.json")]);
    const inRange = (d) => d && d >= from && d <= to;
    const l = laws.filter((r) => inRange(r[1]));
    const o = orders.filter((r) => inRange(r[2]));
    return {
      federal_holidays: holidaysBetween(from, to).map((h) => ({ name: h.name, date: h.date, observed: h.observed, rule: h.rule, set_by: h.law, url: h.lawId ? `/laws/${h.lawId}/` : null })),
      laws_count: l.length, orders_count: o.length,
      calendar_url: `/calendar/?from=${from}&to=${to}`,
      laws: l.slice(0, 40).map((r) => ({ id: r[0], url: `/laws/${r[0]}/`, enacted: r[1], title: r[2], headline: r[3] || null })),
      executive_orders: o.slice(0, 40).map((r) => ({ number: r[0], url: `/executive-orders/${r[0]}/`, signed: r[2], title: r[1] })),
      note: l.length > 40 || o.length > 40 ? "Only the first 40 of each are listed; link the calendar_url for the full list." : undefined,
    };
  }
  if (name === "find_politicians") {
    const rows = await asset(env, "/data/members.json");
    const st = stateFilter(input.query);
    const terms = st ? [] : words(input.query);
    return rows.filter(([, n, , s]) => (st ? s === st : terms.length && terms.every((t) => n.toLowerCase().includes(t))))
      .sort((a, b) => Math.max(...b[6]) - Math.max(...a[6])).slice(0, st ? 60 : 8)
      .map(([bio, n, p, s, ch, d, cs]) => ({ name: n, url: `/politicians/${bio}/`, party: p, state: s, chamber: ch, district: d || null, congresses: cs }));
  }
  if (name === "search_failed") {
    const rows = await asset(env, "/data/failed.json");
    const terms = words(input.query);
    return rows.filter((r) => !input.year || r.failed_on.startsWith(String(input.year)))
      .map((r) => ({ r, s: score(terms, [[r.title.toLowerCase(), 3], [r.headline.toLowerCase(), 2], [r.topic.toLowerCase(), 1], [r.bill.toLowerCase().replace(/[. ]/g, ""), 4]]) }))
      .filter((h) => h.s > 0 || !terms.length).sort((a, b) => b.s - a.s || b.r.failed_on.localeCompare(a.r.failed_on)).slice(0, 8).map(({ r }) => r);
  }
  if (name === "search_executive_orders") {
    const rows = await asset(env, "/data/orders.json");
    const terms = words(input.query);
    const pres = (input.president || "").toLowerCase();
    return rows.filter((r) => !pres || r[3].toLowerCase().includes(pres))
      .map((r) => ({ r, s: score(terms, [[r[1].toLowerCase(), 3], [r[4].toLowerCase(), 2], [String(r[0]), 4]]) }))
      .filter((h) => h.s > 0).sort((a, b) => b.s - a.s).slice(0, 8)
      .map(({ r }) => ({ number: r[0], url: `/executive-orders/${r[0]}/`, title: r[1], signed: r[2], president: r[3], headline: r[4] || null }));
  }
  return { error: `Unknown tool ${name}` };
}

export class ChatGuard extends DurableObject {
  // Returns null if the visitor may ask, or a message explaining why not.
  async admit(visitor, capUsd) {
    const day = new Date().toISOString().slice(0, 10);
    const spent = (await this.ctx.storage.get(`spend:${day}`)) || 0;
    if (spent >= capUsd) return "The assistant has reached its limit for today. Please try again tomorrow. Everything else on the site still works.";
    const hour = new Date().toISOString().slice(0, 13);
    const key = `rate:${hour}:${visitor}`;
    const n = (await this.ctx.storage.get(key)) || 0;
    if (n >= PER_VISITOR_PER_HOUR) return "You've asked a lot of questions this hour. Please try again a little later.";
    await this.ctx.storage.put(key, n + 1);
    // Clean up old rate counters now and then.
    if (Math.random() < 0.02) {
      const old = await this.ctx.storage.list({ prefix: "rate:", end: `rate:${hour}` });
      await this.ctx.storage.delete([...old.keys()].slice(0, 128));
    }
    return null;
  }
  async record(costUsd) {
    const day = new Date().toISOString().slice(0, 10);
    const spent = (await this.ctx.storage.get(`spend:${day}`)) || 0;
    await this.ctx.storage.put(`spend:${day}`, spent + costUsd);
    return spent + costUsd;
  }
  async today() {
    return (await this.ctx.storage.get(`spend:${new Date().toISOString().slice(0, 10)}`)) || 0;
  }
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });

export async function handleAsk(request, env) {
  if (request.method !== "POST") return json({ error: "Use POST." }, 405);
  if (!env.ANTHROPIC_API_KEY) return json({ reply: "The assistant isn't switched on yet. Please check back soon." });
  let body;
  try { body = await request.json(); } catch { return json({ error: "Bad request." }, 400); }
  const history = (Array.isArray(body.messages) ? body.messages : []).slice(-8)
    .filter((m) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.slice(0, 1500) }));
  while (history.length && history[0].role !== "user") history.shift();
  if (!history.length || history[history.length - 1].role !== "user") return json({ error: "Ask a question." }, 400);

  const guard = env.CHAT_GUARD.get(env.CHAT_GUARD.idFromName("global"));
  const visitor = request.headers.get("CF-Connecting-IP") || "unknown";
  const cap = Number(env.CHAT_DAILY_CAP_USD || 2);
  const refusal = await guard.admit(visitor, cap);
  if (refusal) return json({ reply: refusal, limited: true });

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, baseURL: "https://api.anthropic.com" });
  const messages = [...history];
  let cost = 0, reply = "";
  try {
    for (let step = 0; step < MAX_STEPS; step++) {
      const res = await client.messages.create({
        model: MODEL, max_tokens: 2048,
        system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }, { type: "text", text: `Today is ${new Date().toISOString().slice(0, 10)}.` }],
        output_config: { effort: "low" },
        tools: TOOLS, messages,
      });
      const u = res.usage;
      cost += (u.input_tokens + (u.cache_creation_input_tokens || 0) * 1.25 + (u.cache_read_input_tokens || 0) * 0.1) * PRICE_IN + u.output_tokens * PRICE_OUT;
      const uses = res.content.filter((b) => b.type === "tool_use");
      if (res.stop_reason !== "tool_use" || !uses.length) {
        reply = res.content.filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
        if (res.stop_reason === "refusal") reply = "Sorry, I can't help with that. I can answer questions about federal laws, votes, Presidents and executive orders.";
        break;
      }
      messages.push({ role: "assistant", content: res.content });
      const results = [];
      for (const t of uses) {
        let out;
        try { out = await runTool(env, t.name, t.input); } catch (e) { out = { error: "Lookup failed." }; }
        results.push({ type: "tool_result", tool_use_id: t.id, content: JSON.stringify(out).slice(0, 30000) });
      }
      messages.push({ role: "user", content: results });
    }
  } catch (e) {
    if (cost) await guard.record(cost);
    const busy = e instanceof Anthropic.RateLimitError || e instanceof Anthropic.InternalServerError;
    return json({ reply: busy ? "The assistant is busy right now. Please try again in a minute." : "Sorry, something went wrong. Please try again." });
  }
  await guard.record(cost);
  return json({ reply: reply || "Sorry, I couldn't find an answer to that. Try asking another way, or use the search box at the top." });
}
