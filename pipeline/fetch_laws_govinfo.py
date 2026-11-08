"""Download public laws from GovInfo bulk data (no API key needed).

A fallback for fetch_laws.py when the Congress.gov API is slow or down. GovInfo
publishes public-law XML from the 113th Congress (2013) on, and bill status
records (titles, sponsors, official summaries, actions) from the 108th (2003).
Writes the same files as fetch_laws.py, so build.py works with either.

Usage: python pipeline/fetch_laws_govinfo.py [first_congress] [last_congress]
"""
import json
import re
import sys
import xml.etree.ElementTree as ET

from common import RAW, cached, current_congress, fetch, write_json

BULK = "https://www.govinfo.gov/bulkdata"
FIRST = 113
# The enacted bill appears as a bracketed side note, e.g. [<ref href="/us/bill/118/hr/2882">H.R. 2882</ref>]
BILL_REF = re.compile(r'\[<ref href="/us/bill/\d+/(hr|s|hjres|sjres)/(\d+)"')
# Some files carry plain text instead: [H.R.  670]
PLAIN_REF = re.compile(r"\[(H\.\s*R\.|S\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.)\s*(\d+)\]")


def listing(path: str) -> list[dict]:
    data = fetch(f"{BULK}/json/{path}", headers={"Accept": "application/json"})
    return json.loads(data).get("files", [])


def elem_to_dict(el: ET.Element):
    """Turn a bill status XML element into plain dicts and lists."""
    children = list(el)
    if not children:
        return el.text
    if all(c.tag == "item" for c in children) or el.tag in ("summaries",):
        return [elem_to_dict(c) for c in children]
    return {c.tag: elem_to_dict(c) for c in children}


def law_record(congress: int, pl_file: dict, refresh: bool) -> tuple[dict, dict] | None:
    pl_path = cached(RAW / "govinfo" / "PLAW" / str(congress) / pl_file["name"],
                     pl_file["link"], refresh=False)
    text = pl_path.read_text(errors="replace")
    ref = BILL_REF.search(text) or PLAIN_REF.search(text)
    date = re.search(r"<approvedDate>([\d-]+)</approvedDate>", text)
    number = re.search(r"publ(\d+)\.xml", pl_file["name"]).group(1)
    if not ref:
        print(f"  could not find bill for Public Law {congress}-{number}")
        return None
    btype = re.sub(r"[\s.]", "", ref.group(1)).upper()
    bnum = ref.group(2)
    bs_name = f"BILLSTATUS-{congress}{btype.lower()}{bnum}.xml"
    bs_path = cached(RAW / "govinfo" / "BILLSTATUS" / str(congress) / bs_name,
                     f"{BULK}/BILLSTATUS/{congress}/{btype.lower()}/{bs_name}", refresh=refresh)
    bill_el = ET.parse(bs_path).getroot().find("bill")
    bill = elem_to_dict(bill_el)
    summaries = [
        {"text": s.findtext("text") or s.findtext("cdata/text"), "actionDesc": s.findtext("actionDesc"),
         "actionDate": s.findtext("actionDate"), "updateDate": s.findtext("updateDate")}
        for s in bill_el.findall("summaries/summary")
    ]
    text_versions = [
        {"type": t.findtext("type"), "date": t.findtext("date"),
         "formats": [{"url": f.findtext("url")} for f in t.findall("formats/item")]}
        for t in bill_el.findall("textVersions/item")
    ]
    title = bill_el.findtext("title")
    approved = date.group(1) if date else ""
    if not approved or approved < "1789":  # some files carry a placeholder date
        approved = next((a.findtext("actionDate") for a in bill_el.findall("actions/item")
                         if "Became Public Law" in (a.findtext("text") or "")),
                        bill_el.findtext("latestAction/actionDate"))
    entry = {
        "type": btype, "number": bnum, "congress": congress, "title": title,
        "laws": [{"type": "Public Law", "number": f"{congress}-{number}"}],
        "latestAction": {"actionDate": approved,
                         "text": f"Became Public Law No: {congress}-{number}."},
    }
    detail = {"bill": {"title": title,
                       "policyArea": {"name": bill_el.findtext("policyArea/name")},
                       "sponsors": [{"fullName": bill_el.findtext("sponsors/item/fullName")}]},
              "summaries": summaries, "text": text_versions}
    return entry, detail


def main() -> None:
    first = max(int(sys.argv[1]) if len(sys.argv) > 1 else FIRST, FIRST)
    last = int(sys.argv[2]) if len(sys.argv) > 2 else current_congress()
    for congress in range(first, last + 1):
        refresh = congress == current_congress()
        files = [f for f in listing(f"PLAW/{congress}/public") if f["name"].endswith(".xml")]
        files.sort(key=lambda f: int(re.search(r"publ(\d+)", f["name"]).group(1)))
        out_dir = RAW / "congress_gov" / str(congress)
        laws = []
        for f in files:
            rec = law_record(congress, f, refresh)
            if rec:
                entry, detail = rec
                laws.append(entry)
                write_json(out_dir / f"{entry['type'].lower()}{entry['number']}.json", detail)
        write_json(out_dir / "laws.json", laws)
        print(f"laws (govinfo): Congress {congress} done ({len(laws)} of {len(files)} laws)")


if __name__ == "__main__":
    main()
