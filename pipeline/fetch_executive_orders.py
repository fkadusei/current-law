"""Download executive orders from the Federal Register API (no key needed).

The Federal Register's API covers executive orders published since 1994.
Earlier orders (1973-1993) need a separate source; see README.

Usage: python pipeline/fetch_executive_orders.py
"""
import urllib.parse

from common import RAW, fetch_json, write_json

API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = [
    "executive_order_number", "title", "signing_date", "publication_date",
    "president", "html_url", "pdf_url", "abstract", "document_number",
    "citation", "disposition_notes", "full_text_xml_url",
]


def main() -> None:
    params = [
        ("conditions[presidential_document_type]", "executive_order"),
        ("per_page", "1000"),
        ("order", "oldest"),
    ] + [("fields[]", f) for f in FIELDS]
    url = API + "?" + urllib.parse.urlencode(params)
    orders = []
    while url:
        page = fetch_json(url)
        orders.extend(page.get("results", []))
        url = page.get("next_page_url")
    write_json(RAW / "federal_register" / "executive_orders.json", orders)
    print(f"executive orders: {len(orders)} downloaded")


if __name__ == "__main__":
    main()
