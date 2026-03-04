"""
source_monitor.py — Check ranking source pages for content changes.

URLs are placeholders — fill in before deploying.
"""

import hashlib
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

# ── Source URLs ───────────────────────────────────────────────────────────────
# Fill in the direct URL to each source's top-100 prospect page.
SOURCES = {
    "MLB Pipeline":    "",   # TODO
    "Baseball America": "",  # TODO
    "FanGraphs":        "",  # TODO
    "ESPN":             "",  # TODO
    "RotoChamp":        "",  # TODO
    "RotoProspects":    "",  # TODO
    "Prospect361":      "",  # TODO
    "Bleacher Report":  "",  # TODO
    "Just Baseball":    "",  # TODO
}

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
HASHES_FILE = os.path.join(BASE_DIR, ".source_hashes.json")


# ── Helpers ───────────────────────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text content."""
    SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip:
            return
        t = data.strip()
        if t:
            self.chunks.append(t)


def _fetch_text(url: str, timeout: int = 20) -> str:
    """Fetch a URL and return its visible text content."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RankleBot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", errors="ignore")
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.chunks)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ── Hash store ────────────────────────────────────────────────────────────────
def _load_hashes() -> dict:
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE) as f:
            return json.load(f)
    return {}


def _save_hashes(hashes: dict):
    with open(HASHES_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


# ── Main check ────────────────────────────────────────────────────────────────
def check_for_updates() -> tuple[list[str], list[tuple[str, str]]]:
    """
    Fetch all configured sources and compare to stored hashes.

    Returns:
        changed: list of source names whose content has changed
        errors:  list of (source_name, error_message) for fetch failures

    On first run, stores baseline hashes without reporting changes.
    When a change is detected, updates the stored hash (so you're notified once).
    """
    hashes  = _load_hashes()
    changed = []
    errors  = []
    now     = datetime.now(timezone.utc).isoformat()

    for source, url in SOURCES.items():
        if not url:
            continue
        try:
            text     = _fetch_text(url)
            new_hash = _hash(text)
            old_hash = hashes.get(source, {}).get("hash")

            if old_hash is None:
                # First time — store baseline, don't flag as changed
                logging.info(f"[monitor] Baseline stored for {source}")
            elif new_hash != old_hash:
                changed.append(source)
                logging.info(f"[monitor] Change detected: {source}")

            hashes[source] = {"hash": new_hash, "checked": now}

        except Exception as e:
            logging.warning(f"[monitor] Error fetching {source}: {e}")
            errors.append((source, str(e)))

    _save_hashes(hashes)
    return changed, errors


def get_status() -> list[dict]:
    """
    Return current status for all sources without fetching.
    Used for the /checkupdates status display.
    """
    hashes = _load_hashes()
    rows = []
    for source, url in SOURCES.items():
        entry = hashes.get(source, {})
        rows.append({
            "source":    source,
            "url":       url,
            "checked":   entry.get("checked"),
            "has_hash":  "hash" in entry,
        })
    return rows
