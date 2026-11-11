"""Find bills, resolutions and motions that failed a recorded floor vote.

Covers three ways a measure can fail on the floor:
  defeated  a vote to pass it (or agree to it, or override a veto) failed
  blocked   the Senate refused to end debate on it, take it up, or discharge it
  set aside the House voted to table it or send it to committee (a privileged
            resolution such as an impeachment or censure is usually killed this way)
Amendments, motions to recommit and other procedural votes are left out.

Reads Voteview (data/raw/voteview) plus votes too new for Voteview
(data/raw/recent, from fetch_recent_votes.py), and bill details from the
Congress.gov API (cached in data/raw/congress_gov/<congress>/bills/).
Writes:
  data/build/failed/<congress>/<id>.json   one file per measure, with every member's vote
  data/build/failed/index.json             lightweight list

Usage: python pipeline/build_failed.py [first_congress] [last_congress]
"""
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict

from build import CAST, PARTY, chamber_control, load_summary, num, read_csv, tally
from common import BUILD, RAW, current_congress, fetch_json, write_json

FIRST = 113  # matches the laws on the site (2013 onward)

FAILED_RESULT = re.compile(r"fail|reject|defeat|not agreed|veto sustained|not guilty", re.I)
SKIP_QUESTION = re.compile(r"amendment|amdt|recommit|commit|instruct|adjourn|previous question|reconsider|appeal|"
                           r"point of order|attendance|decision of the chair|ruling|waive|quorum|"
                           r"close|conferees|conference\b(?! report)|consideration of the resolution|nomination", re.I)
FINAL = re.compile(r"passage|pass\b|on agreeing to the (resolution|concurrent resolution|conference report)|"
                   r"^on the (joint |concurrent )?resolution|^on the bill|conference report|concur|"
                   r"overrid|objections of the president|guilty|ratification", re.I)
BLOCK = re.compile(r"cloture|motion to proceed|motion to discharge|on motion to discharge", re.I)
SET_ASIDE = re.compile(r"^on (the )?motion to (table|refer)( the resolution.*)?$", re.I)
BILL_TYPES = {"HR": "house-bill", "S": "senate-bill", "HRES": "house-resolution", "SRES": "senate-resolution",
              "HJRES": "house-joint-resolution", "SJRES": "senate-joint-resolution",
              "HCONRES": "house-concurrent-resolution", "SCONRES": "senate-concurrent-resolution"}
LABEL = {"HR": "H.R.", "S": "S.", "HRES": "H.Res.", "SRES": "S.Res.", "HJRES": "H.J.Res.", "SJRES": "S.J.Res.",
         "HCONRES": "H.Con.Res.", "SCONRES": "S.Con.Res."}


def split_bill(bill: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"([A-Z]+)(\d+)", bill or "")
    return (m.group(1), m.group(2)) if m and m.group(1) in BILL_TYPES else None


def classify(chamber: str, question: str, result: str, bill: str) -> str | None:
    """Return how the measure failed on this vote, or None if the vote doesn't count."""
    if not split_bill(bill):
        return None  # nominations, treaties, votes not on a measure
    q = question.strip()
    if chamber == "House" and SET_ASIDE.match(q) and not FAILED_RESULT.search(result) and bill.startswith("HRES"):
        return "set_aside"  # the motion to table/refer passed, so the resolution was shelved
    if not FAILED_RESULT.search(result) or SKIP_QUESTION.search(q) and not re.search(r"conference report|cloture", q, re.I):
        return None
    if re.search(r"overrid|objections of the president", q, re.I) or "veto sustained" in result.lower():
        return "veto_sustained"
    if re.search(r"guilty", q, re.I):
        return "acquitted"
    if BLOCK.search(q):
        return "blocked"
    if FINAL.search(q):
        return "defeated"
    return None


def load_congress(congress: int):
    """Members, roll calls and positions from Voteview plus the newer 'recent' votes."""
    members, by_bioguide, senate_by_name = {}, {}, {}
    rollcalls, positions = [], defaultdict(dict)
    for ch, chamber in (("H", "House"), ("S", "Senate")):
        for m in read_csv(f"{ch}{congress:03d}_members.csv"):
            if m["chamber"] == "President":
                continue
            key = num(m["icpsr"])
            members[key] = {"icpsr": key, "bioguide": m["bioguide_id"], "name": m["bioname"],
                            "party": PARTY.get(num(m["party_code"]), "Other"), "state": m["state_abbrev"],
                            "chamber": chamber}
            if m["bioguide_id"]:
                by_bioguide[m["bioguide_id"]] = key
            if chamber == "Senate":
                senate_by_name[(m["bioname"].split(",")[0].strip().upper(), m["state_abbrev"])] = key
        seen = set()
        for r in read_csv(f"{ch}{congress:03d}_rollcalls.csv"):
            seen.add((int(float(r["session"])), int(float(r["clerk_rollnumber"]))))
            kind = classify(chamber, r["vote_question"], r["vote_result"], r["bill_number"].upper())
            if kind:
                rollcalls.append({"chamber": chamber, "key": (chamber, int(float(r["rollnumber"]))),
                                  "roll": int(float(r["clerk_rollnumber"])), "session": int(float(r["session"])),
                                  "date": r["date"], "bill": r["bill_number"].upper(), "kind": kind,
                                  "question": r["vote_question"], "result": r["vote_result"],
                                  "required": r["majority_requirement"] or "1/2", "desc": r["vote_desc"],
                                  "yea": int(r["yea_count"] or 0), "nay": int(r["nay_count"] or 0)})
        wanted = {c["key"] for c in rollcalls if c["chamber"] == chamber}
        for v in read_csv(f"{ch}{congress:03d}_votes.csv"):
            key = (chamber, int(float(v["rollnumber"])))
            cast = num(v["cast_code"])
            if key in wanted and cast in CAST and num(v["icpsr"]) in members:
                positions[key][num(v["icpsr"])] = CAST[cast]
        # Votes newer than Voteview.
        recent = RAW / "recent" / f"{congress}.json"
        for r in (json.loads(recent.read_text()) if recent.exists() else []):
            if r["chamber"] != chamber or (r["session"], r["clerk_roll"]) in seen:
                continue
            kind = classify(chamber, r["vote_question"], r["vote_result"], r["bill_number"])
            if not kind:
                continue
            key = (chamber, f"recent-{r['session']}-{r['clerk_roll']}")
            for p in r["positions"]:
                if chamber == "House":
                    icpsr = by_bioguide.get(p["bioguide"])
                else:
                    icpsr = senate_by_name.get(((p.get("last_name") or "").upper(), p["state"]))
                if not icpsr:  # a member Voteview doesn't list yet
                    icpsr = f"new-{p.get('bioguide') or p.get('senate_id')}"
                    members[icpsr] = {"icpsr": icpsr, "bioguide": p.get("bioguide"), "name": p["name"],
                                      "party": p["party"] if p["party"] in ("D", "R", "I") else "Other",
                                      "state": p["state"], "chamber": chamber}
                positions[key][icpsr] = p["vote"]
            counts = defaultdict(int)
            for v in positions[key].values():
                counts[v] += 1
            rollcalls.append({"chamber": chamber, "key": key, "roll": r["clerk_roll"], "session": r["session"],
                              "date": r["date"], "bill": r["bill_number"], "kind": kind,
                              "question": r["vote_question"], "result": r["vote_result"],
                              "required": r["majority_requirement"], "desc": r["vote_desc"],
                              "yea": counts["yea"], "nay": counts["nay"]})
    return members, rollcalls, positions


def bill_details(congress: int, btype: str, number: str) -> dict:
    """Bill record and CRS summaries from Congress.gov, cached on disk."""
    path = RAW / "congress_gov" / str(congress) / "bills" / f"{btype.lower()}{number}.json"
    if path.exists():
        return json.loads(path.read_text())
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        return {}
    base = f"https://api.congress.gov/v3/bill/{congress}/{btype.lower()}/{number}"
    try:
        record = {"bill": fetch_json(f"{base}?format=json&api_key={key}").get("bill", {}),
                  "summaries": fetch_json(f"{base}/summaries?format=json&api_key={key}").get("summaries", [])}
    except Exception as e:  # keep going; the vote description still gives a title
        print(f"failed: no Congress.gov details for {congress} {btype}{number}: {e}")
        return {}
    time.sleep(0.8)
    write_json(path, record)
    return record


def support_color(votes: list[dict]) -> dict | None:
    """Which party supplied most of the votes FOR the measure on its last failed vote.

    Same idea as a law's color: red or blue by the party behind it, darker the more
    one-sided. "For" means yes, except on a motion to table or refer, where voting
    no is the vote to keep the measure alive.
    """
    v = votes[-1]
    side = v["support"]
    r = v["by_party"].get("R", {}).get(side, 0)
    d = v["by_party"].get("D", {}).get(side, 0)
    if r + d == 0:
        return None
    r_share = r / (r + d)
    share = max(r_share, 1 - r_share)
    return {"side": "R" if r_share > 0.5 else "D" if r_share < 0.5 else "tie", "share": round(share, 3),
            "r_support": r, "d_support": d, "shade": round((share - 0.5) * 2, 3),
            "party_line": "D" if r == 0 else "R" if d == 0 else None}


def build_congress(congress: int, enacted_bills: dict) -> list[dict]:
    members, rollcalls, positions = load_congress(congress)
    by_bill = defaultdict(list)
    for c in rollcalls:
        by_bill[c["bill"]].append(c)
    index = []
    for bill, calls in by_bill.items():
        btype, number = split_bill(bill)
        calls.sort(key=lambda c: (c["date"], c["session"], c["roll"]))
        detail = bill_details(congress, btype, number)
        info = detail.get("bill", {})
        votes = []
        for c in calls:
            pos = positions.get(c["key"], {})
            if not pos:
                continue
            votes.append({
                "chamber": c["chamber"], "roll": c["roll"], "date": c["date"], "kind": c["kind"],
                "question": c["question"], "result": c["result"], "required": c["required"],
                "yea": c["yea"], "nay": c["nay"], "support": "nay" if c["kind"] == "set_aside" else "yea",
                "by_party": tally(pos, members), "majority_party": chamber_control(pos, members, c["date"]),
                "members": [{"icpsr": i, "bioguide": members[i]["bioguide"], "name": members[i]["name"],
                             "party": members[i]["party"], "state": members[i]["state"], "vote": v}
                            for i, v in sorted(pos.items())],
            })
        if not votes:
            continue
        item_id = f"{congress}-{btype.lower()}{number}"
        summaries = sorted(detail.get("summaries", []), key=lambda s: (s.get("actionDate") or "", s.get("updateDate", "")))
        law = enacted_bills.get((congress, f"{btype} {number}"))
        last = votes[-1]
        record = {
            "id": item_id,
            "congress": congress,
            "bill": f"{LABEL[btype]} {number}",
            "bill_type": btype,
            "title": info.get("title") or calls[-1]["desc"] or f"{LABEL[btype]} {number}",
            "policy_area": (info.get("policyArea") or {}).get("name"),
            "sponsor": (info.get("sponsors") or [{}])[0].get("fullName"),
            "latest_action": info.get("latestAction"),
            "official_summary": summaries[-1]["text"] if summaries else None,
            "congress_gov_url": f"https://www.congress.gov/bill/{congress}th-congress/{BILL_TYPES[btype]}/{number}",
            "failed_on": last["date"],
            "kind": last["kind"],
            "chamber": last["chamber"],
            "later_became_law": law,  # {"id", "public_law"} when the bill passed after all
            "votes": votes,
            "support_color": support_color(votes),
            "control": {last["chamber"]: last["majority_party"]},
            "summary": load_summary(f"failed-{item_id}"),
        }
        write_json(BUILD / "failed" / str(congress) / f"{item_id}.json", record)
        index.append({k: record[k] for k in ("id", "congress", "bill", "title", "policy_area", "failed_on",
                                             "kind", "chamber", "later_became_law", "support_color", "control")})
    print(f"failed: Congress {congress}: {len(index)} measures failed a floor vote")
    return index


def main() -> None:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else FIRST
    last = int(sys.argv[2]) if len(sys.argv) > 2 else current_congress()
    enacted = {}
    laws_index = BUILD / "laws" / "index.json"
    for law in json.loads(laws_index.read_text()) if laws_index.exists() else []:
        enacted[(law["congress"], law["bill"])] = {"id": law["id"], "public_law": law["public_law"]}
    index = []
    for congress in range(first, last + 1):
        index += build_congress(congress, enacted)
    write_json(BUILD / "failed" / "index.json", sorted(index, key=lambda i: i["failed_on"], reverse=True))


if __name__ == "__main__":
    main()
