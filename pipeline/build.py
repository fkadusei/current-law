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


def load_summary(item_id: str) -> dict | None:
    path = RAW.parent / "summaries" / f"{item_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def num(value: str) -> str:
    """Voteview writes some codes as floats ("200.0"); normalize to "200"."""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return value


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
            members[num(m["icpsr"])] = {
                "icpsr": num(m["icpsr"]),
                "bioguide": m["bioguide_id"],
                "name": m["bioname"],
                "party": PARTY.get(num(m["party_code"]), "Other"),
                "state": m["state_abbrev"],
                "district": num(m["district_code"]) if chamber == "House" else None,
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
                    "roll": int(float(r["rollnumber"])),
                    "date": r["date"],
                    "question": q,
                    "result": r["vote_result"],
                    "yea": int(r["yea_count"] or 0),
                    "nay": int(r["nay_count"] or 0),
                })
        wanted = {(c["chamber"], c["roll"]) for calls in finals.values() for c in calls}
        for v in read_csv(f"{ch}{congress:03d}_votes.csv"):
            key = (chamber, int(float(v["rollnumber"])))
            cast = num(v["cast_code"])
            # Skip the President's row: Voteview records his stated position, not a vote.
            if key in wanted and cast in CAST and num(v["icpsr"]) in members:
                positions[key][num(v["icpsr"])] = CAST[cast]
    return members, finals, positions


def chamber_control(positions: dict, members: dict, date: str) -> str:
    """Which party held the majority in the chamber on the day of the vote.

    Counted from everyone on the roll (voting or not). Independents are counted
    with Democrats, since nearly every independent since 1973 caucused with them.
    A tie (like the 50-50 Senate of 2021-22) goes to the Vice President's party,
    which is the President's party.
    """
    seats = defaultdict(int)
    for icpsr in positions:
        party = members.get(icpsr, {}).get("party")
        if party in ("D", "I"):
            seats["D"] += 1
        elif party == "R":
            seats["R"] += 1
    if seats["D"] == seats["R"]:
        return president_on(date)["party"][0]
    return "D" if seats["D"] > seats["R"] else "R"


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


def party_color(votes: list[dict]) -> dict | None:
    """Which party supplied most of the "yes" votes, across both chambers.

    The site colors a law red (Republican) or blue (Democratic) by this side, and
    shades it by share: 50% is the lightest shade, 100% the darkest. Laws with no
    recorded vote (voice vote or unanimous consent) get no color.
    """
    yeas = defaultdict(int)
    for v in votes:
        for party, counts in v["by_party"].items():
            yeas[party] += counts.get("yea", 0)
    r, d = yeas.get("R", 0), yeas.get("D", 0)
    if r + d == 0:
        return None
    r_share = r / (r + d)
    side = "R" if r_share > 0.5 else "D" if r_share < 0.5 else "tie"
    share = max(r_share, 1 - r_share)
    # "No Republican (or Democrat) voted yes": the site shows this as a clear badge.
    party_line = "D" if r == 0 else "R" if d == 0 else None
    return {"side": side, "share": round(share, 3), "r_yeas": r, "d_yeas": d,
            "shade": round((share - 0.5) * 2, 3),  # 0 = even split, 1 = one party only
            "party_line": party_line,
            "zero_yeas_by_chamber": {
                v["chamber"]: [pt for pt in ("R", "D") if v["by_party"].get(pt, {}).get("yea", 0) == 0]
                for v in votes}}


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
            votes.append({**call, "by_party": tally(pos, members),
                          "majority_party": chamber_control(pos, members, call["date"]),
                          "members": [
                {"icpsr": i, "bioguide": members[i]["bioguide"], "name": members[i]["name"],
                 "party": members[i]["party"], "state": members[i]["state"], "vote": v}
                for i, v in sorted(pos.items())]})
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
            "recorded_vote": bool(votes),
            "party_color": party_color(votes),
            # Who controlled each chamber, shown next to who actually passed it, e.g.
            # "Republican-controlled House, passed mostly by Democratic votes".
            "control": {v["chamber"]: v["majority_party"] for v in votes},  # False means voice vote or unanimous consent
            "summary": load_summary(law_id),  # written by summarize.py
        }
        write_json(BUILD / "laws" / str(congress) / f"{law_id}.json", record)
        index.append({k: record[k] for k in (
            "id", "congress", "public_law", "bill", "title", "enacted",
            "president", "became_law", "policy_area", "recorded_vote", "party_color", "control")})
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
    orders, seen = [], set()
    for o in json.loads(path.read_text()):
        number = o.get("executive_order_number")
        # Skip corrections, republished copies and unnumbered documents.
        if not number or number in seen or (o.get("title") or "").startswith("Correction"):
            continue
        seen.add(number)
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
            "abstract": o.get("abstract"),
            "summary": load_summary(f"eo-{o.get('executive_order_number')}"),
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
