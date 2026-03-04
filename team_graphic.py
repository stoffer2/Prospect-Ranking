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

# JSON data files live in Prospect-Ranking. If running from a sibling directory
# (e.g. rankle-bot), fall back to the Prospect-Ranking sibling.
_prospect_ranking_dir = os.path.join(os.path.dirname(BASE_DIR), "Prospect-Ranking")
DATA_DIR = BASE_DIR if os.path.exists(os.path.join(BASE_DIR, "mlb-pipeline.json")) \
           else _prospect_ranking_dir

RANKINGS_FILES = [
    "mlb-pipeline.json", "baseball-america.json", "fangraphs.json",
    "espn.json", "rotochamp.json", "rotoprospects.json",
    "prospect361.json", "bleacher-report.json", "just-baseball.json",
]

# ── Render scale ──────────────────────────────────────────────────────────────
# Render at 2× logical resolution, then downsample with LANCZOS → crisp text.
SCALE = 2

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
        path = os.path.join(DATA_DIR, filename)
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


def _draw_pos_badge(draw, cx, cy, pos, s=1):
    bg, fg = POS_COLORS.get(pos, ((80, 80, 80), (200, 200, 200)))
    bw, bh = 54*s, 26*s
    bx, by = int(cx - bw / 2), int(cy - bh / 2)
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5*s,
                            fill=(bg[0]//5, bg[1]//5, bg[2]//5))
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5*s, outline=fg, width=s)
    draw.text((cx, cy), pos, font=_fd(14*s), fill=fg, anchor="mm")


def _draw_vol_badge(draw, cx, cy, vol, s=1):
    bg, fg = VOL_COLORS.get(vol, VOL_COLORS["N/A"])
    label  = vol if vol != "N/A" else "—"
    bw     = {"Low": 54, "Moderate": 90, "High": 60, "Extreme": 80, "N/A": 30}.get(vol, 70) * s
    bh     = 26*s
    bx, by = int(cx - bw / 2), int(cy - bh / 2)
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5*s,
                            fill=(bg[0]//5, bg[1]//5, bg[2]//5))
    draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=5*s, outline=fg, width=s)
    draw.text((cx, cy), label, font=_fd(13*s), fill=fg, anchor="mm")


def _draw_consensus_dots(draw, left_x, cy, filled, total=6, s=1):
    dot_r  = 5 * s
    gap    = 8 * s
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

    S = SCALE  # all pixel values multiplied by S; canvas downsampled at the end

    team_name, team_rgb = TEAMS[team_code]

    # Compute full global prospect list, filter to this team
    all_prospects = _load_all_prospects()
    team_prospects = [p for p in all_prospects if p["team"] == team_code][:10]

    # ── Layout ────────────────────────────────────────────────────────────────
    W        = 1080 * S
    HEADER_H = 162  * S
    COL_H    = 46   * S
    ROW_H    = 126  * S
    PAD      = 14   * S
    n_rows   = max(len(team_prospects), 1)
    H        = HEADER_H + COL_H + n_rows * ROW_H + 130 * S + PAD * 2

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

    # Luminance guard: dark team colors fall back to TEAL for all colored elements
    acc_lum    = 0.299*ACCENT[0] + 0.587*ACCENT[1] + 0.114*ACCENT[2]
    BAR_COLOR  = ACCENT if acc_lum > 60 else TEAL
    RANK_COLOR = TEAL   # always high-contrast teal on dark pill

    # ── Top accent bar ────────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, 7*S], fill=BAR_COLOR)

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([0, 7*S, W, HEADER_H], fill=HDR_BG)

    abbr_font = _fb(100*S)
    # Team abbreviation in team color (BAR_COLOR handles dark-team fallback)
    draw.text((52*S, 14*S), team_code, font=abbr_font, fill=BAR_COLOR)

    # Underline accent below abbr
    abbr_w = int(draw.textlength(team_code, font=abbr_font))
    draw.rectangle([52*S, 120*S, 52*S + abbr_w, 122*S], fill=BAR_COLOR)
    draw.text((52*S, 132*S), team_name, font=_fd(20*S), fill=TEXT_MID)

    # "TOP PROSPECTS" — always legible: white on dark
    draw.text((W - 52*S, 32*S),  "TOP",        font=_fb(50*S), fill=WHITE_HI,  anchor="rt")
    draw.text((W - 52*S, 80*S),  "PROSPECTS",  font=_fb(50*S), fill=TEAL,      anchor="rt")
    draw.text((W - 52*S, 138*S), "RANKLE.DEV", font=_fb(26*S), fill=TEAL,      anchor="rt")

    # ── Measure rank column width first (needed for header alignment) ─────────
    rank_font = _fb(50*S)
    tmp_d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_rw = max(
        (tmp_d.textlength(str(p["displayRank"]), font=rank_font) for p in team_prospects),
        default=50*S,
    )
    RANK_RIGHT = 52*S + int(max_rw) + 8*S
    NAME_LEFT  = RANK_RIGHT + 16*S

    # Data column centers (used for both headers and row data)
    C_RANK = (46*S + RANK_RIGHT) // 2
    C_POS  = 607*S
    C_SCR  = 676*S
    C_VOL  = 800*S
    DOT_W  = (6 * 10 + 5 * 8) * S              # dots block width
    C_CONS = 876*S + DOT_W // 2                 # center of dots block

    # ── Column headers ────────────────────────────────────────────────────────
    COL_Y = HEADER_H + 12*S
    hf = _fd(13*S)
    HDR_COLOR = (190, 200, 215)
    draw.text((C_RANK,    COL_Y), "#",          font=hf, fill=HDR_COLOR, anchor="mm")
    draw.text((NAME_LEFT, COL_Y), "PLAYER",     font=hf, fill=HDR_COLOR, anchor="lm")
    draw.text((C_POS,     COL_Y), "POS",        font=hf, fill=HDR_COLOR, anchor="mm")
    draw.text((C_SCR,     COL_Y), "SCORE",      font=hf, fill=HDR_COLOR, anchor="mm")
    draw.text((C_VOL,     COL_Y), "VOLATILITY", font=hf, fill=HDR_COLOR, anchor="mm")
    draw.text((C_CONS,    COL_Y), "CONSENSUS",  font=hf, fill=HDR_COLOR, anchor="mm")
    draw.rectangle([38*S, COL_Y + 10*S, W - 38*S, COL_Y + 11*S], fill=(255, 255, 255, 18))

    # ── Prospect rows ─────────────────────────────────────────────────────────
    ROW_Y0 = COL_Y + 28*S

    if not team_prospects:
        draw.text((W // 2, ROW_Y0 + 60*S),
                  "No prospects in the consensus rankings.",
                  font=_fd(20*S), fill=TEXT_LO, anchor="mm")
    else:
        for i, p in enumerate(team_prospects):
            y         = ROW_Y0 + i * ROW_H
            row_fill  = (14, 20, 33) if i % 2 == 0 else (18, 26, 42)
            mid_y     = y + ROW_H // 2

            draw.rounded_rectangle([38*S, y, W - 38*S, y + ROW_H - 6*S],
                                   radius=10*S, fill=row_fill)
            draw.rounded_rectangle([38*S, y, 46*S, y + ROW_H - 6*S],
                                   radius=4*S, fill=TEAL_DIM)

            # Overall rank number — on a dark pill for contrast
            rank_str = str(p["displayRank"])
            rank_w   = int(tmp_d.textlength(rank_str, font=rank_font))
            pill_pad = 10*S
            pill_x0  = RANK_RIGHT - rank_w - pill_pad
            pill_x1  = RANK_RIGHT + pill_pad
            pill_y0  = mid_y - 34*S
            pill_y1  = mid_y + 22*S
            draw.rounded_rectangle([pill_x0, pill_y0, pill_x1, pill_y1],
                                   radius=8*S, fill=(6, 10, 18))
            draw.text((RANK_RIGHT, mid_y - 6*S), rank_str,
                      font=rank_font, fill=RANK_COLOR, anchor="rm")

            # Name
            draw.text((NAME_LEFT, y + 20*S), p["name"],
                      font=_fd(26*S), fill=(255, 255, 255))

            # Range subtext
            draw.text((NAME_LEFT, y + 56*S),
                      f"Range: #{p['minRank']}–#{p['maxRank']}",
                      font=_fd(17*S), fill=TEXT_MID)

            # POS badge
            _draw_pos_badge(draw, C_POS, mid_y - 2*S, p["pos"], s=S)

            # Rankle Score
            draw.text((C_SCR, mid_y - 2*S), f"{p['rankleScore']:.1f}",
                      font=_fd(22*S), fill=WHITE_HI, anchor="mm")

            # Volatility badge
            _draw_vol_badge(draw, C_VOL, mid_y - 2*S, p["volatility"], s=S)

            # Consensus dots — centered on C_CONS
            dots_left = C_CONS - DOT_W // 2
            _draw_consensus_dots(draw, dots_left, mid_y - 2*S,
                                 filled=p["consensusAgreement"], s=S)

            # Row separator
            if i < len(team_prospects) - 1:
                sy = y + ROW_H - 4*S
                draw.rectangle([54*S, sy, W - 54*S, sy + S], fill=(255, 255, 255, 8))

    # ── Footer / legend ───────────────────────────────────────────────────────
    FY = ROW_Y0 + n_rows * ROW_H + PAD + 10*S

    LEG_H  = 76 * S
    LBL_F  = _fd(13*S)
    HINT_F = _fd(12*S)
    LBL_C  = (210, 218, 228)
    HINT_C = (160, 174, 192)

    draw.rectangle([0, FY, W, FY + LEG_H], fill=(16, 22, 34))
    # Prominent top border
    draw.rectangle([0, FY, W, FY + 2*S], fill=(255, 255, 255, 30))

    # Fixed separator at canvas midpoint — never overlaps content
    SEP_X = W // 2
    TOP   = FY + 14*S
    MID   = FY + 40*S
    BOT   = FY + 62*S

    # ── Group 1: Volatility (left half, x=56*S … SEP_X) ──────────────────────
    GX = 56*S
    draw.text((GX, TOP), "Volatility", font=LBL_F, fill=LBL_C, anchor="lm")
    draw.text((GX, BOT), "How much experts disagree on ranking position",
              font=HINT_F, fill=HINT_C, anchor="lm")

    bx = GX
    for label, vol_key in [("Low","Low"),("Moderate","Moderate"),("High","High"),("Extreme","Extreme")]:
        bg_c, fg = VOL_COLORS[vol_key]
        bw = int(_fd(13*S).getlength(label)) + 16*S
        bh = 22*S
        by = MID - bh // 2
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4*S,
                                fill=(bg_c[0]//5, bg_c[1]//5, bg_c[2]//5))
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4*S,
                                outline=fg, width=S)
        draw.text((bx + bw // 2, MID), label, font=_fd(13*S), fill=fg, anchor="mm")
        bx += bw + 6*S

    # ── Separator at midpoint ─────────────────────────────────────────────────
    draw.rectangle([SEP_X, FY + 12*S, SEP_X + S, FY + LEG_H - 12*S],
                   fill=(255, 255, 255, 25))

    # ── Group 2: Consensus (right half, x=SEP_X+24*S …) ──────────────────────
    GX2 = SEP_X + 24*S
    draw.text((GX2, TOP), "Consensus", font=LBL_F, fill=LBL_C, anchor="lm")
    draw.text((GX2, BOT), "Pips show how many sources agree on position",
              font=HINT_F, fill=HINT_C, anchor="lm")
    _draw_consensus_dots(draw, GX2, MID, filled=6, s=S)

    # ── Branding strip ────────────────────────────────────────────────────────
    BRAND_H = 48 * S
    draw.rectangle([0, FY + LEG_H, W, FY + LEG_H + BRAND_H], fill=(10, 14, 22))
    draw.text((W // 2, FY + LEG_H + BRAND_H // 2),
              "RANKLE.DEV", font=_fb(32*S), fill=TEAL, anchor="mm")

    # ── Crop, downsample 2×→1×, return ───────────────────────────────────────
    content_h = FY + LEG_H + BRAND_H + 10*S
    final = img.crop((0, 0, W, content_h))
    final = final.resize((W // S, content_h // S), Image.Resampling.LANCZOS)

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
