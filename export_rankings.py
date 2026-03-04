#!/usr/bin/env python3
"""
export_rankings.py — Parse RAW_DATA and SOURCES from index.html and write rankings.json.

Run this whenever the rankings data in index.html is updated.
The bot (team_graphic.py) reads rankings.json instead of the old per-source JSON files.
"""

import json
import re
import os

HERE      = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "index.html")
OUT_PATH  = os.path.join(HERE, "rankings.json")


def extract_js_block(html, var_name, opener, closer):
    """Extract a JS variable's value between opener and closer characters."""
    marker = f"var {var_name} = {opener}"
    idx = html.find(marker)
    if idx == -1:
        raise ValueError(f"Could not find '{marker}' in HTML")
    start = idx + len(marker) - 1  # position of opener
    depth = 0
    for i in range(start, len(html)):
        if html[i] == opener:
            depth += 1
        elif html[i] == closer:
            depth -= 1
            if depth == 0:
                return html[start:i+1]
    raise ValueError(f"Unmatched {opener} for var {var_name}")


def js_to_json(js):
    """Convert JS object/array literal to valid JSON."""
    # Quote unquoted object keys: word: → "word":
    js = re.sub(r'([{,\s])([a-zA-Z_][a-zA-Z0-9_]*)(\s*):', r'\1"\2"\3:', js)
    # Remove trailing commas before } or ]
    js = re.sub(r',(\s*[}\]])', r'\1', js)
    return js


def parse_sources(html):
    block = extract_js_block(html, "SOURCES", '{', '}')
    return json.loads(js_to_json(block))


def parse_raw_data(html):
    block = extract_js_block(html, "RAW_DATA", '[', ']')
    return json.loads(js_to_json(block))


def main():
    with open(HTML_PATH, encoding="utf-8") as f:
        html = f.read()

    sources  = parse_sources(html)
    players  = parse_raw_data(html)

    out = {"sources": sources, "players": players}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(players)} players, {len(sources)} sources → {OUT_PATH}")


if __name__ == "__main__":
    main()
