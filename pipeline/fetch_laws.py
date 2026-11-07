"""Download every public law for each Congress from the Congress.gov API.

For each law we keep the bill record, its CRS summaries, and its text links.
Responses are cached under data/raw/congress_gov so reruns are cheap.
Needs CONGRESS_API_KEY (free from https://api.data.gov/signup/).

Usage: python pipeline/fetch_laws.py [first_congress] [last_congress]
"""
import sys
import time

from common import (FIRST_CONGRESS, RAW, congress_api_key, current_congress,
                    fetch_json, write_json)
import json

API = "https://api.congress.gov/v3"
PAUSE = 0.8  # stay under the 5,000 requests/hour limit


def get(path: str, key: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in {"format": "json", **params, "api_key": key}.items())
    time.sleep(PAUSE)
    return fetch_json(f"{API}{path}?{query}")


def list_laws(congress: int, key: str) -> list[dict]:
    laws, offset = [], 0
    while True:
        page = get(f"/law/{congress}", key, limit=250, offset=offset)
        batch = page.get("bills", [])
        laws.extend(batch)
        if len(batch) < 250:
            return laws
        offset += 250


def main() -> None:
    key = congress_api_key()
    first = int(sys.argv[1]) if len(sys.argv) > 1 else FIRST_CONGRESS
    last = int(sys.argv[2]) if len(sys.argv) > 2 else current_congress()
    for congress in range(first, last + 1):
        out_dir = RAW / "congress_gov" / str(congress)
        index_path = out_dir / "laws.json"
        if index_path.exists() and congress != current_congress():
            laws = json.loads(index_path.read_text())
        else:
            laws = list_laws(congress, key)
            write_json(index_path, laws)
        for law in laws:
            btype, number = law["type"].lower(), law["number"]
            path = out_dir / f"{btype}{number}.json"
            if path.exists():
                continue
            base = f"/bill/{congress}/{btype}/{number}"
            record = {
                "bill": get(base, key).get("bill", {}),
                "summaries": get(f"{base}/summaries", key).get("summaries", []),
                "text": get(f"{base}/text", key).get("textVersions", []),
            }
            write_json(path, record)
        print(f"laws: Congress {congress} done ({len(laws)} laws)")


if __name__ == "__main__":
    main()
