"""Join laws, votes, presidents and executive orders into site-ready JSON.

Reads data/raw (from the fetch_* scripts) and writes data/build:
  data/build/laws/<congress>/<id>.json   one file per law, with every member's vote
  data/build/laws/index.json             lightweight list for search and browsing
  data/build/members/index.json          every member of Congress seen
  data/build/executive_orders.json       executive orders with the signing president

Usage: python pipeline/build.py [first_congress] [last_congress]
"""
import csv
import json
import re
import sys
from collections import defaultdict

from common import BUILD, FIRST_CONGRESS, RAW, current_congress, president_on, write_json

PARTY = {"100": "D", "200": "R", "328": "I"}
CAST = {**dict.fromkeys("123", "yea"), **dict.fromkeys("456", "nay"), "7": "present",
        "8": "not voting", "9": "not voting"}

# Roll-call questions that decide whether a chamber passes a bill. Amendments,
# cloture, procedural motions and the like are left out.
FINAL_QUESTIONS = re.compile(
    r"passage|suspend the rules and (pass|agree|concur)|concur|conference report|"
    r"^on the joint resolution$|^on agreeing to the resolution|^on the resolution$|"
    r"^on the motion$|overrid|objections of the president",
    re.I,
)
NOT_FINAL = re.compile(r"^on (agreeing to )?the amendment|cloture|table|proceed|recommit|refer|reconsider|"
                       r"previous question|instruct|attendance|discharge|point of order", re.I)
CONCUR_RES = re.compile(r"concurrence by the (?:House|Senate) in the (?:Senate|House) "
                        r"amendments? to (H\.\s?R\.|S\.|H\.J\.\s?Res\.|S\.J\.\s?Res\.)\s?(\d+)", re.I)


def read_csv(name: str) -> list[dict]:
    path = RAW / "voteview" / name
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_votes(congress: int):
    """Return (members by icpsr, final roll calls by bill, positions by roll call)."""
    members, finals, positions = {}, defaultdict(list), defaultdict(dict)
    for ch, chamber in (("H", "House"), ("S", "Senate")):
        for m in read_csv(f"{ch}{congress:03d}_members.csv"):
            if m["chamber"] == "President":
                continue
            members[m["icpsr"]] = {
                "icpsr": m["icpsr"],
                "bioguide": m["bioguide_id"],
                "name": m["bioname"],
                "party": PARTY.get(m["party_code"], "Other"),
                "state": m["state_abbrev"],
                "district": m["district_code"] if chamber == "House" else None,
                "chamber": chamber,
            }
        for r in read_csv(f"{ch}{congress:03d}_rollcalls.csv"):
            q = r["vote_question"]
            bill = r["bill_number"].upper()
            # The House often concurs in Senate changes through a separate resolution
            # ("Providing for the concurrence by the House in the Senate amendment to H.R. 2882").
            m = CONCUR_RES.search(r["vote_desc"] or "")
            if m:
                bill = (m.group(1) + m.group(2)).upper().replace(".", "").replace(" ", "")
            if bill and FINAL_QUESTIONS.search(q) and not NOT_FINAL.search(q):
                finals[bill].append({
                    "chamber": chamber,
                    "roll": int(r["rollnumber"]),
                    "date": r["date"],
                    "question": q,
                    "result": r["vote_result"],
                    "yea": int(r["yea_count"] or 0),
                    "nay": int(r["nay_count"] or 0),
                })
        wanted = {(c["chamber"], c["roll"]) for calls in finals.values() for c in calls}
        for v in read_csv(f"{ch}{congress:03d}_votes.csv"):
            key = (chamber, int(v["rollnumber"]))
            if key in wanted and v["cast_code"] in CAST:
                positions[key][v["icpsr"]] = CAST[v["cast_code"]]
    return members, finals, positions


def deciding_votes(calls: list[dict]) -> list[dict]:
    """Keep the last deciding roll call per chamber (a veto override counts too)."""
    by_chamber = {}
    for c in sorted(calls, key=lambda c: (c["date"], c["roll"])):
        by_chamber[c["chamber"]] = c
    return [by_chamber[ch] for ch in ("House", "Senate") if ch in by_chamber]


def tally(positions: dict, members: dict) -> dict:
    out = defaultdict(lambda: defaultdict(int))
    for icpsr, pos in positions.items():
        party = members.get(icpsr, {}).get("party", "Other")
        out[party][pos] += 1
    return {p: dict(v) for p, v in out.items()}


def build_congress(congress: int, member_index: dict) -> list[dict]:
    src = RAW / "congress_gov" / str(congress)
    if not (src / "laws.json").exists():
        print(f"build: no law data for Congress {congress}, skipping")
        return []
    members, finals, positions = load_votes(congress)
    index = []
    for law in json.loads((src / "laws.json").read_text()):
        btype, number = law["type"].upper(), law["number"]
        detail_path = src / f"{btype.lower()}{number}.json"
        detail = json.loads(detail_path.read_text()) if detail_path.exists() else {}
        bill = detail.get("bill", {})
        pl = next((l["number"] for l in law.get("laws", []) if "Public" in l.get("type", "")),
                  (law.get("laws") or [{}])[0].get("number"))
        enacted = (law.get("latestAction") or {}).get("actionDate", "")
        votes = []
        for call in deciding_votes(finals.get(f"{btype}{number}", [])):
            pos = positions.get((call["chamber"], call["roll"]), {})
            votes.append({**call, "by_party": tally(pos, members), "members": [
                {"icpsr": i, "vote": v} for i, v in sorted(pos.items())]})
        overridden = any(re.search(r"overrid|objections", v["question"], re.I) for v in votes)
        law_id = f"pl-{pl}" if pl else f"{congress}-{btype.lower()}{number}"
        summaries = sorted(detail.get("summaries", []), key=lambda s: s.get("updateDate", ""))
        record = {
            "id": law_id,
            "congress": congress,
            "public_law": pl,
            "bill": f"{btype} {number}",
            "title": law.get("title") or bill.get("title"),
            "enacted": enacted,
            "president": None if overridden else president_on(enacted),
            "became_law": "veto override" if overridden else "signed",
            "policy_area": (bill.get("policyArea") or {}).get("name"),
            "sponsor": (bill.get("sponsors") or [{}])[0].get("fullName"),
            "official_summary": summaries[-1]["text"] if summaries else None,
            "text_links": [f for t in detail.get("text", []) for f in t.get("formats", [])],
            "congress_gov_url": f"https://www.congress.gov/bill/{congress}th-congress/"
                                f"{'house' if btype.startswith('H') else 'senate'}-"
                                f"{'joint-resolution' if 'JRES' in btype else 'bill'}/{number}",
            "votes": votes,
            "recorded_vote": bool(votes),  # False means voice vote or unanimous consent
            "summary": None,  # filled in by step 2 (plain-language summaries)
        }
        write_json(BUILD / "laws" / str(congress) / f"{law_id}.json", record)
        index.append({k: record[k] for k in (
            "id", "congress", "public_law", "bill", "title", "enacted",
            "president", "became_law", "policy_area", "recorded_vote")})
    for m in members.values():
        entry = member_index.setdefault(m["bioguide"] or m["icpsr"], {**m, "congresses": []})
        entry["congresses"].append(congress)
    print(f"build: Congress {congress}: {len(index)} laws, "
          f"{sum(1 for i in index if i['recorded_vote'])} with recorded votes")
    return index


def build_executive_orders() -> None:
    path = RAW / "federal_register" / "executive_orders.json"
    if not path.exists():
        return
    orders = []
    for o in json.loads(path.read_text()):
        signed = o.get("signing_date") or o.get("publication_date")
        orders.append({
            "id": f"eo-{o.get('executive_order_number')}",
            "number": o.get("executive_order_number"),
            "title": o.get("title"),
            "signed": signed,
            "president": president_on(signed),
            "url": o.get("html_url"),
            "pdf": o.get("pdf_url"),
            "citation": o.get("citation"),
            "status_notes": o.get("disposition_notes"),
            "summary": None,
        })
    write_json(BUILD / "executive_orders.json", orders)
    print(f"build: {len(orders)} executive orders")


def main() -> None:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else FIRST_CONGRESS
    last = int(sys.argv[2]) if len(sys.argv) > 2 else current_congress()
    members: dict = {}
    index = []
    for congress in range(first, last + 1):
        index += build_congress(congress, members)
    write_json(BUILD / "laws" / "index.json", sorted(index, key=lambda l: l["enacted"], reverse=True))
    write_json(BUILD / "members" / "index.json", list(members.values()))
    build_executive_orders()


if __name__ == "__main__":
    main()
