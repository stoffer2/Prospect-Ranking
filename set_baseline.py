#!/usr/bin/env python3
"""
set_baseline.py — Bake the current Rankle rankings into BAKED_BASELINE in index.html.

Run this after each weekly data update, before pushing:
    python3 set_baseline.py

Users will then see rank-change arrows vs this snapshot until you run it again.
To reset arrows (no baseline), run:
    python3 set_baseline.py --clear
"""

import json
import re
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
RANKINGS_JSON = os.path.join(ROOT, "rankings.json")
INDEX_HTML    = os.path.join(ROOT, "index.html")

PLACEHOLDER = "var BAKED_BASELINE = {};"


def load_rankings():
    with open(RANKINGS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data["players"], data["sources"]


def rankle_score(ranks, sources):
    """Mirrors computeProspect() in index.html exactly."""
    entries = [(key, val) for key, val in ranks.items() if val is not None and key in sources]
    n = len(entries)
    if n == 0:
        return 0, 0

    z_scores = []
    for key, rank in entries:
        list_len = sources[key]["listLength"]
        rank = min(rank, list_len)
        mean = (list_len + 1) / 2
        sd   = ((list_len ** 2 - 1) / 12) ** 0.5
        z_scores.append(-(rank - mean) / sd)

    z_avg = sum(z_scores) / n
    score = max(0, min(100, 50 + z_avg * 29.4))

    # Bayesian shrinkage for single-source players
    if n == 1:
        score = (score + 2 * 50) / 3

    return score, n


def build_baseline(players, sources):
    """Return {name: display_rank}, mirroring buildProspects() in index.html."""
    scored = []
    for p in players:
        score, n = rankle_score(p.get("ranks", {}), sources)
        if n > 1:
            scored.append((p["name"], score))

    scored.sort(key=lambda x: -x[1])
    return {name: i + 1 for i, (name, _) in enumerate(scored)}


BASELINE_RE = re.compile(r"var BAKED_BASELINE = \{[^;]*\};")


def patch_index(baseline):
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()

    if not BASELINE_RE.search(html):
        print("ERROR: Could not find BAKED_BASELINE line in index.html.")
        sys.exit(1)

    serialized = json.dumps(baseline, ensure_ascii=False, separators=(",", ":"))
    new_line = f"var BAKED_BASELINE = {serialized};"
    html = BASELINE_RE.sub(new_line, html, count=1)

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def clear_index():
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()

    html = BASELINE_RE.sub("var BAKED_BASELINE = {};", html, count=1)

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    clear = "--clear" in sys.argv

    if clear:
        clear_index()
        print("BAKED_BASELINE cleared — arrows will no longer show for anyone.")
        return

    print("Loading rankings.json...")
    players, sources = load_rankings()
    print(f"  {len(players)} players found.")

    baseline = build_baseline(players, sources)
    print(f"  {len(baseline)} eligible prospects in baseline.")

    print("Patching index.html...")
    patch_index(baseline)

    top5 = list(baseline.items())[:5]
    print(f"  Top 5: {top5}")
    print("\nDone. Commit and push to make arrows live for all users.")
    print("  git add index.html && git commit -m 'Set rank baseline' && git push")


if __name__ == "__main__":
    main()
