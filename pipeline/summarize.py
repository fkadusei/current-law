"""Write plain-language summaries of laws and executive orders with Claude.

Reads data/build (from build.py) and writes data/summaries/<id>.json, which
build.py merges into each record. Summaries already written are skipped, so
reruns only cover new laws.

Uses the Message Batches API (half price, results usually within an hour).
Needs CURRENT_LAW_ANTHROPIC_KEY (or ANTHROPIC_API_KEY) and `pip install -r pipeline/requirements.txt`.
In GitHub Actions it can sign in without a key, through Workload Identity
Federation: set ANTHROPIC_FEDERATION_RULE_ID and ANTHROPIC_ORGANIZATION_ID and
give the job `id-token: write` (see make_client).

Usage:
  python pipeline/summarize.py [--model MODEL] [--limit N] [--congress 118] [--orders]
  python pipeline/summarize.py --failed              # bills and resolutions that failed a floor vote
  python pipeline/summarize.py --collect BATCH_ID   # fetch results of an earlier batch
"""
import argparse
import os
import json
import re
import time
import urllib.request

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from common import BUILD, ROOT, write_json

SUMMARIES = ROOT / "data" / "summaries"
# Model for new summaries. Change it here, or set CURRENT_LAW_SUMMARY_MODEL.
DEFAULT_MODEL = os.environ.get("CURRENT_LAW_SUMMARY_MODEL", "claude-opus-5-5")
# Ceremonial laws (post office names, commemorations) read the same on any
# model, so they go to the cheaper one.
CEREMONIAL_MODEL = "claude-haiku-5-5"
CEREMONIAL = re.compile(r"designate the (facility|building|federal building|courthouse)|post office|"
                        r"to (re)?name |commemorat|congressional gold medal|award a congressional", re.I)

SYSTEM = """You explain US federal laws and executive orders to everyday voters.

Write in plain English at about an 8th-grade reading level. Be strictly neutral:
describe what the measure does and who it affects, never whether it is good or
bad, and never use either party's framing or slogans. Stick to what the official
title and summary support. If the source material is thin, say less rather than
guessing, and set "confidence" to "low".

Focus on concrete effects on people: money, rights, services, rules, deadlines.
Name specific groups (for example "veterans", "small businesses", "people who
buy health insurance on their own") rather than vague ones. Ceremonial measures
such as naming a post office should get a one-sentence summary and an empty
"who_it_affects" list."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, under 25 words."},
        "what_it_does": {"type": "string", "description": "2 to 4 short sentences."},
        "who_it_affects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group": {"type": "string"},
                    "how": {"type": "string", "description": "One sentence."},
                },
                "required": ["group", "how"],
                "additionalProperties": False,
            },
        },
        "when_it_takes_effect": {"type": ["string", "null"]},
        "ceremonial": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["headline", "what_it_does", "who_it_affects", "when_it_takes_effect",
                 "ceremonial", "confidence"],
    "additionalProperties": False,
}


def strip_html(text: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def law_prompt(law: dict) -> str:
    official = strip_html(law.get("official_summary")) or "(no official summary available)"
    return (f"Law: Public Law {law.get('public_law')} ({law.get('bill')}), enacted {law.get('enacted')}\n"
            f"Title: {law.get('title')}\n"
            f"Policy area: {law.get('policy_area') or 'unknown'}\n\n"
            f"Official summary from the Congressional Research Service:\n{official}")


KIND_TEXT = {
    "defeated": "it was voted down", "blocked": "the Senate refused to take it up or end debate on it",
    "set_aside": "the House voted to table it or send it back to committee",
    "veto_sustained": "Congress failed to override the President's veto", "acquitted": "the Senate voted to acquit",
}


def failed_prompt(item: dict) -> str:
    official = strip_html(item.get("official_summary")) or "(no official summary available)"
    last = item["votes"][-1]
    how = KIND_TEXT[item["kind"]]
    if item["kind"] == "set_aside":
        how = ("the House voted to refer it to committee, which set it aside" if "refer" in last["question"].lower()
               else "the House voted to table it, which killed it")
    return (f"This measure did NOT pass: on {item['failed_on']} in the {item['chamber']}, {how} "
            f"({last['question']}: {last['yea']} yes, {last['nay']} no).\n"
            f"Describe what it WOULD have done if adopted (use \"would\"), not what it does. "
            f"Put \"Did not take effect\" in when_it_takes_effect.\n\n"
            f"Measure: {item['bill']} ({item['congress']}th Congress)\n"
            f"Title: {item.get('title')}\n"
            f"Policy area: {item.get('policy_area') or 'unknown'}\n\n"
            f"Official summary from the Congressional Research Service:\n{official}")


def order_prompt(order: dict) -> str:
    return (f"Executive Order {order['number']}, signed {order['signed']} by {order['president']['name'] if order['president'] else 'unknown'}\n"
            f"Title: {order['title']}\n"
            f"Abstract: {order.get('abstract') or '(none provided; work from the title only)'}")


def request(custom_id: str, prompt: str, model: str) -> Request:
    return Request(custom_id=custom_id, params=MessageCreateParamsNonStreaming(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    ))


def pending_items(args) -> list[tuple[str, str]]:
    items = []
    laws_dir = BUILD / "laws"
    congresses = [str(args.congress)] if args.congress else sorted(
        p.name for p in laws_dir.iterdir() if p.is_dir())
    for c in congresses:
        for path in sorted((laws_dir / c).glob("*.json")):
            law = json.loads(path.read_text())
            if not (SUMMARIES / f"{law['id']}.json").exists():
                items.append((law["id"], law_prompt(law), bool(CEREMONIAL.search(law.get("title") or ""))))
    if args.failed:
        for path in sorted((BUILD / "failed").glob("*/*.json")):
            item = json.loads(path.read_text())
            if args.congress and item["congress"] != args.congress:
                continue
            if not (SUMMARIES / f"failed-{item['id']}.json").exists():
                # Same policy as laws: the current model from 2023 on, Haiku before that.
                old = item["congress"] < 118
                items.append((f"failed-{item['id']}", failed_prompt(item),
                              old or bool(CEREMONIAL.search(item.get("title") or ""))))
        return items[: args.limit] if args.limit else items
    if args.orders:
        for order in json.loads((BUILD / "executive_orders.json").read_text()):
            if not (SUMMARIES / f"{order['id']}.json").exists():
                items.append((order["id"], order_prompt(order), False))
    return items[: args.limit] if args.limit else items


def collect(client: anthropic.Anthropic, batch_id: str, model: str) -> None:
    while (batch := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
        print(f"  waiting: {batch.request_counts.processing} still processing")
        time.sleep(60)
    done = failed = 0
    for result in client.messages.batches.results(batch_id):
        if result.result.type != "succeeded":
            failed += 1
            print(f"  {result.custom_id}: {result.result.type}")
            continue
        msg = result.result.message
        if msg.stop_reason != "end_turn":
            failed += 1
            print(f"  {result.custom_id}: stopped with {msg.stop_reason}")
            continue
        text = next((b.text for b in msg.content if b.type == "text"), "")
        summary = json.loads(text)
        summary.update({"ai_generated": True, "model": msg.model,
                        "written": time.strftime("%Y-%m-%d")})
        write_json(SUMMARIES / f"{result.custom_id}.json", summary)
        done += 1
    print(f"summaries: {done} written, {failed} failed (rerun to retry failures)")



API = "https://api.anthropic.com"
GITHUB_OIDC_AUDIENCE = "https://api.anthropic.com"


def github_oidc_token() -> str:
    """A fresh GitHub Actions identity token for each exchange.

    Anthropic accepts each token only once (JTI replay protection) and the
    minted access token lasts about ten minutes, so a long batch poll needs a
    new GitHub token every time the SDK refreshes."""
    req = urllib.request.Request(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + GITHUB_OIDC_AUDIENCE,
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["value"]


def make_client() -> anthropic.Anthropic:
    # Always talk to the public API directly, even if ANTHROPIC_BASE_URL is set.
    rule = os.environ.get("ANTHROPIC_FEDERATION_RULE_ID")
    if rule and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        creds = anthropic.WorkloadIdentityCredentials(
            identity_token_provider=github_oidc_token,
            federation_rule_id=rule,
            organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
            service_account_id=os.environ.get("ANTHROPIC_SERVICE_ACCOUNT_ID") or None,
            workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
        )
        print("summaries: signing in with GitHub Actions workload identity")
        return anthropic.Anthropic(credentials=creds, base_url=API)
    key = os.environ.get("CURRENT_LAW_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("Set CURRENT_LAW_ANTHROPIC_KEY to your Anthropic API key.")
    return anthropic.Anthropic(api_key=key, base_url=API)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--congress", type=int)
    ap.add_argument("--orders", action="store_true", help="also summarize executive orders")
    ap.add_argument("--failed", action="store_true", help="summarize bills that failed a floor vote (only those)")
    ap.add_argument("--collect", metavar="BATCH_ID")
    ap.add_argument("--same-model", action="store_true", help="use --model for ceremonial laws too")
    ap.add_argument("--dry-run", action="store_true", help="count what would be sent, send nothing")
    args = ap.parse_args()
    if args.dry_run:
        items = pending_items(args)
        print(f"would summarize {len(items)} items, {sum(1 for *_, c in items if c)} ceremonial")
        return
    client = make_client()
    if args.collect:
        return collect(client, args.collect, args.model)
    items = pending_items(args)
    if not items:
        print("summaries: nothing new to summarize")
        return
    cer = sum(1 for *_, c in items if c)
    batch = client.messages.batches.create(requests=[
        request(cid, prompt, CEREMONIAL_MODEL if c and not args.same_model else args.model)
        for cid, prompt, c in items])
    print(f"summaries: submitted {len(items)} ({cer} ceremonial on {CEREMONIAL_MODEL}) as batch {batch.id}")
    collect(client, batch.id, args.model)


if __name__ == "__main__":
    main()
