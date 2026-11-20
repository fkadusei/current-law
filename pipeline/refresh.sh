#!/usr/bin/env bash
# Refresh the current Congress: new roll-call votes (including today's), new laws,
# executive orders, failed measures, and summaries for anything new.
# Run from the repo root. Needs CONGRESS_API_KEY; summaries also need
# CURRENT_LAW_ANTHROPIC_KEY (skipped without it, so the votes still go out).
set -euo pipefail
C=$(python3 -c 'import sys; sys.path.insert(0, "pipeline"); from common import current_congress; print(current_congress())')
python3 pipeline/fetch_votes.py "$C" "$C"
python3 pipeline/fetch_recent_votes.py "$C"
python3 pipeline/fetch_laws.py "$C" "$C"
python3 pipeline/fetch_executive_orders.py
python3 pipeline/build.py "$C" "$C"
python3 pipeline/build_failed.py "$C" "$C"
if [ -n "${CURRENT_LAW_ANTHROPIC_KEY:-${ANTHROPIC_API_KEY:-}}" ]; then
  python3 pipeline/summarize.py --congress "$C" --orders
  python3 pipeline/summarize.py --failed
  # Put the new summaries into the built records.
  python3 pipeline/build.py "$C" "$C"
  python3 pipeline/build_failed.py "$C" "$C"
else
  echo "refresh: no Anthropic key, skipping summaries"
fi
