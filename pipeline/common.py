"""Shared helpers for the Current Law data pipeline (standard library only)."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BUILD = ROOT / "data" / "build"
USER_AGENT = "current-law-pipeline/0.1 (+https://github.com/fkadusei/current-law)"

FIRST_CONGRESS = 93  # 1973-1974, where Congress.gov bill data begins


def congress_years(congress: int) -> tuple[int, int]:
    start = 1789 + 2 * (congress - 1)
    return start, start + 1


def current_congress(year: int | None = None) -> int:
    year = year or time.gmtime().tm_year
    return (year - 1789) // 2 + 1


def fetch(url: str, *, retries: int = 4, timeout: int = 60) -> bytes:
    """GET a URL with simple exponential backoff on rate limits and network errors."""
    delay = 2
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw))


def cached(path: Path, url: str, *, refresh: bool = False) -> Path:
    """Download url to path unless it already exists."""
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = fetch(url)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def congress_api_key() -> str:
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        raise SystemExit(
            "CONGRESS_API_KEY is not set. Get a free key at https://api.data.gov/signup/"
        )
    return key


# Presidents since 1969, with the date each term began (inauguration day).
PRESIDENTS = [
    ("nixon", "Richard Nixon", "Republican", "1969-01-20"),
    ("ford", "Gerald Ford", "Republican", "1974-08-09"),
    ("carter", "Jimmy Carter", "Democratic", "1977-01-20"),
    ("reagan", "Ronald Reagan", "Republican", "1981-01-20"),
    ("bush-hw", "George H. W. Bush", "Republican", "1989-01-20"),
    ("clinton", "Bill Clinton", "Democratic", "1993-01-20"),
    ("bush-w", "George W. Bush", "Republican", "2001-01-20"),
    ("obama", "Barack Obama", "Democratic", "2009-01-20"),
    ("trump-1", "Donald Trump", "Republican", "2017-01-20"),
    ("biden", "Joe Biden", "Democratic", "2021-01-20"),
    ("trump-2", "Donald Trump", "Republican", "2025-01-20"),
]


def president_on(date: str) -> dict:
    """Return the president in office on an ISO date (YYYY-MM-DD)."""
    current = PRESIDENTS[0]
    for p in PRESIDENTS:
        if p[3] <= date:
            current = p
    pid, name, party, _ = current
    return {"id": pid, "name": name, "party": party}
