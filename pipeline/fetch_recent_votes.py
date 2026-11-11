"""Fetch House and Senate roll calls newer than Voteview's latest file.

Voteview usually lags the floor by a day or more. This fills the gap so a vote
taken today shows up on the site after the next build:
  House:  Congress.gov API (house-vote endpoints), plus the Clerk's vote page
          for the bill number when the API leaves it out.
  Senate: senate.gov roll-call XML.

Writes data/raw/recent/<congress>.json, a list of roll calls in the same shape
build_failed.py reads from Voteview (with member positions by bioguide id).
Rows already in Voteview are dropped at build time, so stale entries are harmless.

Usage: python pipeline/fetch_recent_votes.py [congress]
"""
import csv
import html
import re
import sys
import time
import xml.etree.ElementTree as ET

from common import RAW, congress_api_key, current_congress, fetch, fetch_json, write_json

API = "https://api.congress.gov/v3"
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (compatible; current-law-pipeline)"}
CAST = {"yea": "yea", "aye": "yea", "nay": "nay", "no": "nay", "present": "present",
        "not voting": "not voting"}
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}


def voteview_latest(congress: int, ch: str) -> tuple[int, dict]:
    """(highest clerk roll number in Voteview for each session, as {session: roll})."""
    path = RAW / "voteview" / f"{ch}{congress:03d}_rollcalls.csv"
    latest = {}
    if path.exists():
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                s, n = int(float(r["session"])), int(float(r["clerk_rollnumber"]))
                latest[s] = max(latest.get(s, 0), n)
    return latest


def bill_from_clerk(year: int, roll: int, question: str) -> tuple[str, str]:
    """Bill number and title from the Clerk's vote page (the API sometimes omits them)."""
    try:
        page = fetch(f"https://clerk.house.gov/Votes/{year}{roll}", headers=BROWSER_UA).decode("utf-8", "replace")
    except Exception:
        return "", ""
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", page, flags=re.S))))
    m = re.search(r"Bill Number: ([A-Za-z. ]+?)\s?(\d+)\b", text)
    bill = (m.group(1) + m.group(2)).upper().replace(".", "").replace(" ", "") if m else ""
    t = re.search(r"Vote Question: " + re.escape(question) + r" (.*?) Vote Type:", text)
    return bill, (t.group(1).strip() if t else "")


def house(congress: int, key: str) -> list[dict]:
    out = []
    latest = voteview_latest(congress, "H")
    for session in (1, 2):
        year = 1789 + 2 * (congress - 1) + session - 1
        roll = latest.get(session, 0) + 1
        while True:
            try:
                v = fetch_json(f"{API}/house-vote/{congress}/{session}/{roll}?format=json&api_key={key}",
                               retries=1)["houseRollCallVote"]
            except Exception:
                break  # no such roll call yet
            time.sleep(0.5)
            members = fetch_json(f"{API}/house-vote/{congress}/{session}/{roll}/members"
                                 f"?format=json&limit=500&api_key={key}")
            bill = f"{v.get('legislationType') or ''}{v.get('legislationNumber') or ''}".upper()
            # The API has no title and sometimes no bill number; the Clerk's page has both.
            clerk_bill, title = bill_from_clerk(year, roll, v.get("voteQuestion") or "")
            bill = bill or clerk_bill
            out.append({
                "chamber": "House", "session": session, "clerk_roll": roll,
                "date": v["startDate"][:10], "bill_number": bill,
                "vote_question": v.get("voteQuestion") or "", "vote_result": v.get("result") or "",
                "vote_desc": title, "majority_requirement": "2/3" if "2/3" in (v.get("voteType") or "") else "1/2",
                "positions": [
                    {"bioguide": m["bioguideID"], "name": f"{m['lastName'].upper()}, {m['firstName']}",
                     "party": m.get("voteParty") or "Other", "state": m.get("voteState") or "",
                     "vote": CAST.get((m.get("voteCast") or "").lower(), "not voting")}
                    for m in members["houseRollCallVoteMemberVotes"]["results"]],
            })
            print(f"recent: House {year} roll {roll} {bill} {v.get('voteQuestion')} {v.get('result')}")
            roll += 1
            time.sleep(0.5)
    return out


def senate(congress: int) -> list[dict]:
    out = []
    latest = voteview_latest(congress, "S")
    for session in (1, 2):
        roll = latest.get(session, 0) + 1
        while True:
            url = (f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/"
                   f"vote_{congress}_{session}_{roll:05d}.xml")
            try:
                root = ET.fromstring(fetch(url, retries=1, headers=BROWSER_UA))
            except Exception:
                break
            if root.tag != "roll_call_vote":
                break
            g = lambda p: (root.findtext(p) or "").strip()
            m = re.match(r"(\w+) (\d+), (\d{4})", g("vote_date"))
            date = f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}" if m else ""
            bill = (g("document/document_type") + g("document/document_number")).upper().replace(".", "").replace(" ", "")
            out.append({
                "chamber": "Senate", "session": session, "clerk_roll": roll, "date": date,
                "bill_number": bill, "vote_question": g("question"), "vote_result": g("vote_result"),
                "vote_desc": g("document/document_title") or g("vote_title"),
                "majority_requirement": g("majority_requirement") or "1/2",
                "positions": [
                    {"senate_id": x.findtext("lis_member_id"), "last_name": x.findtext("last_name"),
                     "name": f"{(x.findtext('last_name') or '').upper()}, {x.findtext('first_name')}",
                     "party": x.findtext("party") or "Other", "state": x.findtext("state") or "",
                     "vote": CAST.get((x.findtext("vote_cast") or "").lower(), "not voting")}
                    for x in root.iter("member")],
            })
            print(f"recent: Senate roll {roll} {bill} {g('question')} {g('vote_result')}")
            roll += 1
            time.sleep(0.5)
    return out


def main() -> None:
    congress = int(sys.argv[1]) if len(sys.argv) > 1 else current_congress()
    votes = house(congress, congress_api_key()) + senate(congress)
    write_json(RAW / "recent" / f"{congress}.json", votes)
    print(f"recent: {len(votes)} roll calls newer than Voteview for Congress {congress}")


if __name__ == "__main__":
    main()
