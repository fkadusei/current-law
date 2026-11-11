# Current Law

A plain-language guide to every US federal law since 1973: what it does, how each
member of the House and Senate voted, and which President signed it. Executive
orders are included too.

## Data sources

| What | Source | Key needed |
|---|---|---|
| Laws, bill details, official (CRS) summaries, text links | [Congress.gov API](https://api.congress.gov/) | Yes, `CONGRESS_API_KEY` ([free](https://api.data.gov/signup/)) |
| Every House and Senate roll-call vote, by member | [Voteview](https://voteview.com/data) | No |
| Public laws and bill status, 2013 onward (fallback, used when the Congress.gov API is down) | [GovInfo bulk data](https://www.govinfo.gov/bulkdata) | No |
| Executive orders (1994 onward) | [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | No |

## Pipeline

Python 3.10+. Fetching and building use only the standard library; summaries need
`pip install -r pipeline/requirements.txt`.

```sh
python pipeline/fetch_votes.py 118 118          # roll-call votes for one Congress
python pipeline/fetch_laws.py 118 118           # laws for one Congress (needs the key)
python pipeline/fetch_laws_govinfo.py 118 118   # same, from GovInfo (2013 onward, no key)
python pipeline/fetch_executive_orders.py       # all executive orders
python pipeline/summarize.py --congress 118     # plain-language summaries (needs ANTHROPIC_API_KEY)
python pipeline/build.py 118 118                # join into data/build/
python pipeline/fetch_recent_votes.py           # House/Senate votes too new for Voteview (today's votes)
python pipeline/build_failed.py                 # bills and motions that failed a floor vote -> data/build/failed/
python pipeline/summarize.py --failed           # plain-language summaries of those
```

Leave off the Congress numbers to process everything from the 93rd Congress (1973) to today.
Downloads are cached in `data/raw/` (not committed), so reruns only fetch what's new.

## How votes are matched to laws

Each law is matched to the last deciding roll call in each chamber (final passage,
passing under suspension, agreeing to a conference report, concurring in the other
chamber's changes, or overriding a veto). Amendment, cloture and procedural votes are
left out. Many laws pass by voice vote or unanimous consent, which records no
individual votes; those laws are marked `recorded_vote: false` and the site says so.

## Bills that didn't pass

`build_failed.py` lists every bill, resolution or motion (2013 onward) that got a recorded
floor vote and failed: voted down, blocked in the Senate (cloture, motion to proceed or
discharge rejected), shelved by the House (a motion to table or refer passed), a veto that
stood, or an impeachment acquittal. Amendments, motions to recommit and other procedural
votes are left out. Each measure is colored by the party that supplied most of the votes
for it on its last failed vote. On a motion to table or refer, "for it" means voting no.

Voteview usually lags by a day or more, so `fetch_recent_votes.py` fills the gap from the
Congress.gov API (House) and senate.gov XML (Senate).

## Known gaps

- Executive orders from 1973 to 1993 are not in the Federal Register API yet and need another source.
- When the House passes a Senate bill's contents as separate bills (as with the April 2024
  foreign aid package), the House vote is not linked automatically.
