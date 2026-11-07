"""Download roll-call votes and member lists from Voteview for each Congress.

Voteview (UCLA) publishes every House and Senate roll-call vote with each
member's position, so this covers 1973 to today without an API key.

Usage: python pipeline/fetch_votes.py [first_congress] [last_congress]
"""
import sys

from common import FIRST_CONGRESS, RAW, cached, current_congress

BASE = "https://voteview.com/static/data/out"


def main() -> None:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else FIRST_CONGRESS
    last = int(sys.argv[2]) if len(sys.argv) > 2 else current_congress()
    for congress in range(first, last + 1):
        refresh = congress == current_congress()  # the live Congress keeps changing
        for chamber in ("H", "S"):
            for kind in ("rollcalls", "votes", "members"):
                name = f"{chamber}{congress:03d}_{kind}.csv"
                path = RAW / "voteview" / name
                cached(path, f"{BASE}/{kind}/{name}", refresh=refresh)
        print(f"votes: Congress {congress} done")


if __name__ == "__main__":
    main()
