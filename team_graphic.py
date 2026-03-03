"""
team_graphic.py — Shareable MLB team prospects graphic using the real Rankle algorithm.

Usage:
    from team_graphic import generate_team_graphic
    buf = generate_team_graphic("CHW")   # returns BytesIO (PNG)

CLI:
    python3 team_graphic.py CHW          # saves chw_prospects.png
"""

import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
BEBAS_PATH = os.path.join(BASE_DIR, "BebasNeue.ttf")
DM_PATH    = os.path.join(BASE_DIR, "DMSans.ttf")

RANKINGS_FILES = [
    "mlb-pipeline.json", "baseball-america.json", "fangraphs.json",
    "espn.json", "rotochamp.json", "rotoprospects.json",
    "prospect361.json", "bleacher-report.json", "just-baseball.json",
]

# ── Team metadata ─────────────────────────────────────────────────────────────
TEAMS = {
    "ARI": ("Arizona Diamondbacks",    (167,  25,  48)),
    "ATL": ("Atlanta Braves",          (206,  17,  65)),
    "BAL": ("Baltimore Orioles",       (223,  70,   1)),
    "BOS": ("Boston Red Sox",          (189,  48,  57)),
    "CHC": ("Chicago Cubs",            ( 14,  51, 134)),
    "CHW": ("Chicago White Sox",       ( 80,  80,  90)),   # near-black → use neutral silver
    "CIN": ("Cincinnati Reds",         (198,   1,  31)),
    "CLE": ("Cleveland Guardians",     (  0,  56,  93)),
    "COL": ("Colorado Rockies",        ( 51,  51, 102)),
    "DET": ("Detroit Tigers",          ( 12,  35,  64)),
    "HOU": ("Houston Astros",          (  0,  45,  98)),
    "KC":  ("Kansas City Royals",      (  0,  70, 135)),
    "LAA": ("Los Angeles Angels",      (186,   0,  33)),
    "LAD": ("Los Angeles Dodgers",     (  0,  90, 156)),
    "MIA": ("Miami Marlins",           (  0, 163, 224)),
    "MIL": ("Milwaukee Brewers",       ( 18,  40,  75)),
    "MIN": ("Minnesota Twins",         (  0,  43,  92)),
    "NYM": ("New York Mets",           (  0,  45, 114)),
    "NYY": ("New York Yankees",        ( 12,  35,  64)),
    "ATH": ("Oakland Athletics",       (  0,  56,  49)),
    "PHI": ("Philadelphia Phillies",   (232,  24,  40)),
    "PIT": ("Pittsburgh Pirates",      (255, 198,  30)),
    "SD":  ("San Diego Padres",        ( 47,  36,  29)),
    "SF":  ("San Francisco Giants",    (253,  90,  30)),
    "SEA": ("Seattle Mariners",        (  0,  92,  92)),
    "STL": ("St. Louis Cardinals",     (196,  30,  58)),
    "TB":  ("Tampa Bay Rays",          (  9,  44,  92)),
    "TEX": ("Texas Rangers",           (  0,  50, 120)),
    "TOR": ("Toronto Blue Jays",       ( 19,  74, 142)),
    "WAS": ("Washington Nationals",    (171,   0,   3)),
}

# ── Font helpers ──────────────────────────────────────────────────────────────
def _ensure_fonts():
    def dl(url, path):
        if not os.path.exists(path):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r, open(path, "wb") as f:
                f.write(r.read())
    dl("https://fonts.gstatic.com/s/bebasneue/v14/JTUSjIg69CK48gW7PXooxW5rygbi49c.ttf", BEBAS_PATH)
    dl("https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriCZa4ET-DNl0.ttf", DM_PATH)

def _fb(size): return ImageFont.truetype(BEBAS_PATH, size)
def _fd(size): return ImageFont.truetype(DM_PATH, size)

# ── Rankle scoring algorithm (mirrors index.html JS exactly) ─────────────────
def _source_stats(list_length):
    mean = (list_length + 1) / 2
    sd   = math.sqrt((list_length ** 2 - 1) / 12)
    return mean, sd

def _compute_prospect(meta, source_rankings):
    """
    source_rankings: list of {"rank": int, "list_length": int}
    Returns dict with rankleScore, volatility, consensusAgreement, sourceCount, minRank, maxRank.
    """
    n = len(source_rankings)
    if n == 0:
        return {**meta, "sourceCount": 0, "rankleScore": 0,
                "volatility": "N/A", "consensusAgreement": 0,
                "minRank": None, "maxRank": None}

    # Cap rank at list_length
    capped = [{"rank": min(s["rank"], s["list_length"]),
               "list_length": s["list_length"]} for s in source_rankings]

    # Z-scores (negated: rank 1 = highest Z)
    z_scores = []
    for s in capped:
        mean, sd = _source_stats(s["list_length"])
        z_scores.append(-(s["rank"] - mean) / sd)

    raw_ranks = [s["rank"] for s in capped]
    z_avg = sum(z_scores) / n

    # Rankle Score 0–100
    rankle = max(0.0, min(100.0, 50 + z_avg * 29.4))
    if not all(r == 1 for r in raw_ranks) and rankle >= 99.95:
        rankle = 99.9

    # Volatility (sample stddev of Z-scores)
    volatility = "N/A"
    if n >= 2:
        variance = sum((z - z_avg) ** 2 for z in z_scores) / (n - 1)
        sd_val = math.sqrt(variance)
        if   sd_val < 0.30: volatility = "Low"
        elif sd_val < 0.70: volatility = "Moderate"
        elif sd_val < 0.85: volatility = "High"
        else:               volatility = "Extreme"

    # Consensus agreement: sources within ±10% of median percentile
    percentiles = [100 * (1 - (s["rank"] - 1) / max(s["list_length"] - 1, 1))
                   for s in capped]
    sorted_p = sorted(percentiles)
    mid = len(sorted_p) // 2
    if len(sorted_p) % 2 != 0:
        median_p = sorted_p[mid]
    else:
        median_p = (sorted_p[mid - 1] + sorted_p[mid]) / 2
    consensus = sum(1 for p in percentiles if abs(p - median_p) <= 10)

    # Bayesian shrinkage (single-source only; multi-source filtered out anyway)
    K = 2
    penalized = (rankle + K * 50) / (1 + K) if n == 1 else rankle

    return {
        **meta,
        "sourceCount":        n,
        "rankleScore":        round(penalized * 10) / 10,
        "volatility":         volatility,
        "consensusAgreement": min(consensus, 6),
        "minRank":            min(raw_ranks),
        "maxRank":            max(raw_ranks),
    }


def _load_all_prospects():
    """
    Load every player from all ranking sources, compute Rankle metrics,
    filter to sourceCount > 1, sort by rankleScore desc, assign displayRank.
    Returns list of prospect dicts with .team, .displayRank, etc.
    """
    # Aggregate raw rankings per player
    player_sources = defaultdict(list)   # name → [{rank, list_length, pos, age, eta, team}]

    for filename in RANKINGS_FILES:
        path = os.path.join(BASE_DIR, filename)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        if "list" not in data:
            continue
        src_list  = data["list"]
        list_len  = len(src_list)
        for p in src_list:
            name = p["player_name"]
            player_sources[name].append({
                "rank":        p["rank"],
                "list_length": list_len,
                "pos":         p.get("position", "?"),
                "age":         p.get("age", 0),
                "eta":         p.get("ETA", "—"),
                "team":        p.get("team", ""),
            })

    prospects = []
    for name, sources in player_sources.items():
        # Derive meta fields from most-common values across sources
        pos  = max(set(s["pos"]  for s in sources), key=[s["pos"]  for s in sources].count)
        age  = max(set(s["age"]  for s in sources), key=[s["age"]  for s in sources].count)
        eta  = max(set(s["eta"]  for s in sources), key=[s["eta"]  for s in sources].count)
        team = max(set(s["team"] for s in sources), key=[s["team"] for s in sources].count)
        meta = {"name": name, "pos": pos, "age": age, "eta": eta, "team": team}
        ranking_inputs = [{"rank": s["rank"], "list_length": s["list_length"]} for s in sources]
        prospects.append(_compute_prospect(meta, ranking_inputs))

    # Mirror site: filter single-source, sort by Rankle Score desc, assign display rank
    prospects = [p for p in prospects if p["sourceCount"] > 1]
    prospects.sort(key=lambda p: p["rankleScore"], reverse=True)
    for i, p in enumerate(prospects):
        p["displayRank"] = i + 1

    return prospects


# ── Position badge colors ─────────────────────────────────────────────────────
POS_COLORS = {
    "SP": ((14, 165, 160), (94,  234, 212)),
    "RP": ((20, 148, 142), (80,  220, 200)),
    "OF": ((37,  99, 235), (129, 176, 255)),
    "CF": ((37,  99, 235), (129, 176, 255)),
    "RF": ((37,  99, 235), (129, 176, 255)),
    "LF": ((37,  99, 235), (129, 176, 255)),
    "SS": ((160, 120,  0), (250, 204,  21)),
    "2B": ((140, 100,  0), (240, 185,  20)),
    "3B": ((160,  80,  0), (245, 160,  20)),
    "1B": ((124,  58, 237), (196, 181, 253)),
    "C":  ((107,  33, 168), (216, 180, 254)),
    "DH": (( 80,  80,  80), (180, 180, 180)),
}

VOL_COLORS = {
    "Low":      ((14, 165, 160), (94,  234, 212)),
    "Moderate": ((180, 120,  0), (252, 200,  40)),
    "High":     ((180,  30,  30), (252, 130, 130)),
    "Extreme":  ((100,  40, 200), (196, 160, 255)),
    "N/A":      (( 60,  60,  60), (140, 140, 140)),
}

GOLD_FULL  = (212, 164,  23)
GOLD_EMPTY = ( 45,  40,  25)


def _draw_pos_badge(draw, cx, cy, pos):
    bg, fg = POS_COLORS.get(pos, ((80, 80, 80), (200, 200, 200)))
    bw, bh = 54, 26
    bx, by = int(cx - bw / 2), int(cy - bh / 2)
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5,
                            fill=(bg[0]//5, bg[1]//5, bg[2]//5))
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5, outline=fg, width=1)
    draw.text((cx, cy), pos, font=_fd(14), fill=fg, anchor="mm")


def _draw_vol_badge(draw, cx, cy, vol):
    bg, fg = VOL_COLORS.get(vol, VOL_COLORS["N/A"])
    label  = vol if vol != "N/A" else "—"
    bw     = {"Low": 54, "Moderate": 90, "High": 60, "Extreme": 80, "N/A": 30}.get(vol, 70)
    bh     = 26
    bx, by = int(cx - bw / 2), int(cy - bh / 2)
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5,
                            fill=(bg[0]//5, bg[1]//5, bg[2]//5))
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5, outline=fg, width=1)
    draw.text((cx, cy), label, font=_fd(13), fill=fg, anchor="mm")


def _draw_consensus_dots(draw, left_x, cy, filled, total=6):
    dot_r  = 5
    gap    = 8
    for i in range(total):
        cx = left_x + i * (dot_r * 2 + gap) + dot_r
        color = GOLD_FULL if i < filled else GOLD_EMPTY
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)


# ── Main generator ────────────────────────────────────────────────────────────
def generate_team_graphic(team_code: str) -> BytesIO:
    team_code = team_code.upper()
    if team_code not in TEAMS:
        raise ValueError(f"Unknown team code: {team_code}")

    _ensure_fonts()

    team_name, team_rgb = TEAMS[team_code]

    # Compute full global prospect list, filter to this team
    all_prospects = _load_all_prospects()
    team_prospects = [p for p in all_prospects if p["team"] == team_code][:10]

    # ── Layout ────────────────────────────────────────────────────────────────
    W        = 1080
    HEADER_H = 162
    COL_H    = 46
    ROW_H    = 126
    FOOTER_H = 102
    PAD      = 14
    n_rows   = max(len(team_prospects), 1)
    H        = HEADER_H + COL_H + n_rows * ROW_H + FOOTER_H + PAD * 2

    img = Image.new("RGB", (W, H), (10, 14, 22))

    # Subtle gradient bg
    try:
        import numpy as np
        arr = np.full((H, W, 3), [10, 14, 22], dtype=np.uint8)
        for y in range(H // 2):
            f = 1 - y / (H // 2)
            arr[y, :, 0] = min(255, 10 + int(f * 18))
            arr[y, :, 1] = min(255, 14 + int(f * 24))
            arr[y, :, 2] = min(255, 22 + int(f * 44))
        img.paste(Image.fromarray(arr), (0, 0))
    except ImportError:
        pass

    draw = ImageDraw.Draw(img)

    # ── Palette ───────────────────────────────────────────────────────────────
    TEAL     = (14, 165, 160)
    ACCENT   = team_rgb
    WHITE_HI = (230, 237, 243)
    TEXT_MID = (160, 174, 192)
    TEXT_LO  = (107, 122, 141)
    HDR_BG   = (10,  12,  16)
    TEAL_DIM = (10, 110, 106)

    # Ensure accent is visible on dark bg (min luminance guard)
    acc_lum = 0.299*ACCENT[0] + 0.587*ACCENT[1] + 0.114*ACCENT[2]
    RANK_COLOR = ACCENT if acc_lum > 60 else TEAL

    # ── Top accent bar ────────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, 7], fill=ACCENT if acc_lum > 60 else TEAL)

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([0, 7, W, HEADER_H], fill=HDR_BG)

    abbr_font = _fb(100)
    draw.text((52, 14), team_code, font=abbr_font, fill=(240, 240, 240))

    # Underline accent below abbr
    abbr_w = int(draw.textlength(team_code, font=abbr_font))
    draw.rectangle([52, 120, 52 + abbr_w, 122], fill=ACCENT if acc_lum > 60 else TEAL)
    draw.text((52, 132), team_name, font=_fd(20), fill=TEXT_MID)

    # "TOP PROSPECTS" — always legible: white on dark
    draw.text((W - 52, 32),  "TOP",        font=_fb(50), fill=WHITE_HI,  anchor="rt")
    draw.text((W - 52, 80),  "PROSPECTS",  font=_fb(50), fill=TEAL,      anchor="rt")
    draw.text((W - 52, 138), "Ranked by",  font=_fd(16), fill=TEXT_LO,   anchor="rt")
    draw.text((W - 52, 153), "RANKLE.DEV", font=_fb(22), fill=TEAL,      anchor="rt")

    # ── Column headers ────────────────────────────────────────────────────────
    COL_Y = HEADER_H + 12
    hf = _fd(13)
    # Columns: # | PLAYER | POS | SCORE | VOLATILITY | CONSENSUS
    draw.text(( 52, COL_Y), "#",          font=hf, fill=TEXT_LO)
    draw.text((162, COL_Y), "PLAYER",     font=hf, fill=TEXT_LO)
    draw.text((580, COL_Y), "POS",        font=hf, fill=TEXT_LO)
    draw.text((654, COL_Y), "SCORE",      font=hf, fill=TEXT_LO)
    draw.text((748, COL_Y), "VOLATILITY", font=hf, fill=TEXT_LO)
    draw.text((876, COL_Y), "CONSENSUS",  font=hf, fill=TEXT_LO)
    draw.rectangle([38, COL_Y + 20, W - 38, COL_Y + 21], fill=(255, 255, 255, 10))

    # ── Measure rank column width (handles up to 3-digit ranks) ──────────────
    rank_font = _fb(50)
    tmp_d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_rw = max(
        (tmp_d.textlength(str(p["displayRank"]), font=rank_font) for p in team_prospects),
        default=50,
    )
    RANK_RIGHT = 52 + int(max_rw) + 8
    NAME_LEFT  = RANK_RIGHT + 16

    # ── Prospect rows ─────────────────────────────────────────────────────────
    ROW_Y0 = COL_Y + 28

    if not team_prospects:
        draw.text((W // 2, ROW_Y0 + 60),
                  "No prospects in the consensus rankings.",
                  font=_fd(20), fill=TEXT_LO, anchor="mm")
    else:
        for i, p in enumerate(team_prospects):
            y         = ROW_Y0 + i * ROW_H
            row_fill  = (14, 20, 33) if i % 2 == 0 else (18, 26, 42)
            mid_y     = y + ROW_H // 2

            draw.rounded_rectangle([38, y, W - 38, y + ROW_H - 6],
                                   radius=10, fill=row_fill)
            draw.rounded_rectangle([38, y, 46, y + ROW_H - 6],
                                   radius=4, fill=TEAL_DIM)

            # Overall rank number
            draw.text((RANK_RIGHT, mid_y - 6), str(p["displayRank"]),
                      font=rank_font, fill=RANK_COLOR, anchor="rm")

            # Name
            draw.text((NAME_LEFT, y + 20), p["name"],
                      font=_fd(26), fill=WHITE_HI)

            # Range subtext
            draw.text((NAME_LEFT, y + 56),
                      f"Range: #{p['minRank']}–#{p['maxRank']}",
                      font=_fd(17), fill=TEXT_LO)

            # POS badge
            _draw_pos_badge(draw, 607, mid_y - 2, p["pos"])

            # Rankle Score
            draw.text((676, mid_y - 2), f"{p['rankleScore']:.1f}",
                      font=_fd(22), fill=WHITE_HI, anchor="mm")

            # Volatility badge
            _draw_vol_badge(draw, 800, mid_y - 2, p["volatility"])

            # Consensus dots (centered block)
            dot_block_w = 6 * 10 + 5 * 8   # 6 dots × 10px + 5 gaps × 8px
            dots_left   = 876 + (104 - dot_block_w) // 2
            _draw_consensus_dots(draw, dots_left, mid_y - 2,
                                 filled=p["consensusAgreement"])

            # Row separator
            if i < len(team_prospects) - 1:
                sy = y + ROW_H - 4
                draw.rectangle([54, sy, W - 54, sy + 1], fill=(255, 255, 255, 8))

    # ── Footer ────────────────────────────────────────────────────────────────
    FY = ROW_Y0 + n_rows * ROW_H + PAD
    draw.rectangle([38, FY, W - 38, FY + 1], fill=(255, 255, 255, 16))
    draw.text((W // 2, FY + 18),
              "Consensus rankings aggregated from top prospect analysts.",
              font=_fd(17), fill=TEXT_LO, anchor="mm")
    draw.text((W // 2, FY + 46), "RANKLE.DEV",
              font=_fb(38), fill=TEAL, anchor="mm")
    draw.text((W // 2, FY + 78),
              "Full rankings • Volatility scores • Consensus metrics",
              font=_fd(17), fill=TEXT_LO, anchor="mm")

    # ── Crop and return ───────────────────────────────────────────────────────
    content_h = FY + FOOTER_H
    final = img.crop((0, 0, W, content_h))

    buf = BytesIO()
    final.save(buf, "PNG")
    buf.seek(0)
    return buf


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    code     = sys.argv[1].upper() if len(sys.argv) > 1 else "CHW"
    out_path = os.path.join(BASE_DIR, f"{code.lower()}_prospects.png")
    buf = generate_team_graphic(code)
    with open(out_path, "wb") as f:
        f.write(buf.read())
    print(f"Saved: {out_path}")
