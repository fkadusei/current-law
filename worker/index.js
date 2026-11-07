// Cloudflare Worker for usacurrentlaw.org.
// Serves /api/headlines (a politics news ticker built from public RSS feeds)
// and hands every other request to the static site.

// A mix of outlets from across the spectrum, so the ticker isn't one-sided.
const FEEDS = [
  { source: "NPR", url: "https://feeds.npr.org/1014/rss.xml" },
  { source: "Fox News", url: "https://moxie.foxnews.com/google-publisher/politics.xml" },
  { source: "PBS NewsHour", url: "https://www.pbs.org/newshour/feeds/rss/politics" },
  { source: "The Hill", url: "https://thehill.com/homenews/feed/" },
  { source: "Politico", url: "https://rss.politico.com/politics-news.xml" },
  { source: "CBS News", url: "https://www.cbsnews.com/latest/rss/politics" },
];
const PER_FEED = 6;
const CACHE_SECONDS = 600;

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
function decode(s) {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/<[^>]+>/g, "")
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d))
    .replace(/&([a-z]+);/gi, (m, n) => ENTITIES[n.toLowerCase()] ?? m)
    .replace(/\s+/g, " ")
    .trim();
}
function tag(block, name) {
  const m = block.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)</${name}>`, "i"));
  return m ? decode(m[1]) : "";
}

export function parseFeed(xml, source) {
  const items = [];
  for (const m of xml.matchAll(/<(item|entry)[\s>][\s\S]*?<\/\1>/gi)) {
    const block = m[0];
    const title = tag(block, "title");
    let link = tag(block, "link");
    if (!link) link = (block.match(/<link[^>]*href="([^"]+)"/i) || [])[1] || "";
    const date = tag(block, "pubDate") || tag(block, "updated") || tag(block, "published") || tag(block, "dc:date");
    const time = Date.parse(date) || 0;
    if (title && /^https?:\/\//.test(link)) items.push({ title, link, source, time });
    if (items.length >= PER_FEED) break;
  }
  return items;
}

async function loadFeed(feed) {
  try {
    const res = await fetch(feed.url, {
      headers: { "User-Agent": "CurrentLawHeadlines/1.0 (+https://usacurrentlaw.org)", Accept: "application/rss+xml, application/xml, text/xml" },
      cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
      signal: AbortSignal.timeout(6000),
    });
    if (!res.ok) return [];
    return parseFeed(await res.text(), feed.source);
  } catch {
    return [];
  }
}

async function headlines(request, ctx) {
  const cache = caches.default;
  const key = new Request(new URL("/api/headlines", request.url).toString());
  const hit = await cache.match(key);
  if (hit) return hit;

  const lists = await Promise.all(FEEDS.map(loadFeed));
  // Interleave outlets (newest first within each) so no single source dominates.
  lists.forEach((l) => l.sort((a, b) => b.time - a.time));
  const out = [];
  for (let i = 0; i < PER_FEED; i++) for (const l of lists) if (l[i]) out.push(l[i]);

  const res = new Response(JSON.stringify({ updated: new Date().toISOString(), items: out }), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
    },
  });
  if (out.length) ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/headlines") return headlines(request, ctx);
    return env.ASSETS.fetch(request);
  },
};
