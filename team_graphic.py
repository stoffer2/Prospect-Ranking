"""
team_graphic.py — Generate a shareable MLB team prospects graphic.

Usage:
    from team_graphic import generate_team_graphic
    img_bytes = generate_team_graphic("CHW")  # returns BytesIO

Standalone:
    python3 team_graphic.py CHW
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BEBAS_PATH = os.path.join(BASE_DIR, "BebasNeue.ttf")
DM_PATH    = os.path.join(BASE_DIR, "DMSans.ttf")

RANKINGS_FILES = [
    "mlb-pipeline.json", "baseball-america.json", "fangraphs.json",
    "espn.json", "rotochamp.json", "rotoprospects.json",
    "prospect361.json", "bleacher-report.json", "just-baseball.json",
]

# ── Team metadata ─────────────────────────────────────────────────────────────
TEAMS = {
    "ARI": ("Arizona Diamondbacks",   (167, 25,  48)),
    "ATL": ("Atlanta Braves",         (206, 17,  65)),
    "BAL": ("Baltimore Orioles",      (223, 70,   1)),
    "BOS": ("Boston Red Sox",         (189, 48,  57)),
    "CHC": ("Chicago Cubs",           (14,  51, 134)),
    "CHW": ("Chicago White Sox",      (39,  37,  31)),
    "CIN": ("Cincinnati Reds",        (198,  1,  31)),
    "CLE": ("Cleveland Guardians",    (0,   56,  93)),
    "COL": ("Colorado Rockies",       (51,  51, 102)),
    "DET": ("Detroit Tigers",         (12,  35,  64)),
    "HOU": ("Houston Astros",         (0,   45, 98)),
    "KC":  ("Kansas City Royals",     (0,   70, 135)),
    "LAA": ("Los Angeles Angels",     (186,  0,  33)),
    "LAD": ("Los Angeles Dodgers",    (0,   90, 156)),
    "MIA": ("Miami Marlins",          (0,  163, 224)),
    "MIL": ("Milwaukee Brewers",      (18,  40,  75)),
    "MIN": ("Minnesota Twins",        (0,   43, 92)),
    "NYM": ("New York Mets",          (0,   45, 114)),
    "NYY": ("New York Yankees",       (12,  35,  64)),
    "ATH": ("Oakland Athletics",      (0,   56,  49)),
    "PHI": ("Philadelphia Phillies",  (232, 24,  40)),
    "PIT": ("Pittsburgh Pirates",     (39,  37,  31)),
    "SD":  ("San Diego Padres",       (47,  36,  29)),
    "SF":  ("San Francisco Giants",   (253, 90,  30)),
    "SEA": ("Seattle Mariners",       (0,   92,  92)),
    "STL": ("St. Louis Cardinals",    (196, 30,  58)),
    "TB":  ("Tampa Bay Rays",         (9,   44,  92)),
    "TEX": ("Texas Rangers",          (0,   50, 120)),
    "TOR": ("Toronto Blue Jays",      (19, 74, 142)),
    "WAS": ("Washington Nationals",   (171,  0,  3)),
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


def _fb(size):
    return ImageFont.truetype(BEBAS_PATH, size)


def _fd(size):
    return ImageFont.truetype(DM_PATH, size)


# ── Data loading ──────────────────────────────────────────────────────────────
def _load_team_prospects(team_code):
    """Aggregate prospect data for a team across all ranking sources."""
    player_data = defaultdict(lambda: {"ranks": [], "positions": [], "ages": [], "etas": []})
    source_count = 0

    for filename in RANKINGS_FILES:
        path = os.path.join(BASE_DIR, filename)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        if "list" not in data:
            continue
        source_count += 1
        for p in data["list"]:
            if p.get("team") == team_code:
                name = p["player_name"]
                player_data[name]["ranks"].append(p["rank"])
                player_data[name]["positions"].append(p.get("position", "?"))
                player_data[name]["ages"].append(p.get("age", 0))
                player_data[name]["etas"].append(p.get("ETA", "—"))

    results = []
    for name, d in player_data.items():
        avg_rank = sum(d["ranks"]) / len(d["ranks"])
        pos = max(set(d["positions"]), key=d["positions"].count)
        age = max(set(d["ages"]), key=d["ages"].count)
        eta = max(set(d["etas"]), key=d["etas"].count)
        results.append({
            "name": name,
            "avg_rank": avg_rank,
            "n_lists": len(d["ranks"]),
            "best": min(d["ranks"]),
            "worst": max(d["ranks"]),
            "pos": pos,
            "age": age,
            "eta": eta,
        })

    results.sort(key=lambda x: x["avg_rank"])
    return results, source_count


# ── Badge colors ──────────────────────────────────────────────────────────────
POS_COLORS = {
    "SP": ((14, 165, 160), (94, 234, 212)),
    "RP": ((20, 148, 142), (80, 220, 200)),
    "OF": ((37,  99, 235), (129, 176, 255)),
    "CF": ((37,  99, 235), (129, 176, 255)),
    "RF": ((37,  99, 235), (129, 176, 255)),
    "LF": ((37,  99, 235), (129, 176, 255)),
    "SS": ((160, 120,  0), (250, 204,  21)),
    "2B": ((140, 100,  0), (240, 185,  20)),
    "3B": ((160,  80,  0), (245, 160,  20)),
    "1B": ((124,  58, 237), (196, 181, 253)),
    "C":  ((107,  33, 168), (216, 180, 254)),
    "DH": ((80,   80,  80), (180, 180, 180)),
}


def _badge(draw, cx, cy, pos):
    bg, fg = POS_COLORS.get(pos, ((80, 80, 80), (200, 200, 200)))
    bw, bh = 58, 28
    bx, by = int(cx - bw / 2), int(cy - bh / 2)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6,
                            fill=(bg[0] // 5, bg[1] // 5, bg[2] // 5))
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6,
                            outline=fg, width=1)
    draw.text((cx, cy), pos, font=_fd(15), fill=fg, anchor="mm")


# ── Coverage label ────────────────────────────────────────────────────────────
def _coverage(n):
    if n >= 7:
        return "Very high coverage"
    if n >= 5:
        return "High coverage"
    if n >= 3:
        return "Good coverage"
    if n == 2:
        return "Moderate coverage"
    return "Limited coverage"


# ── Graphic renderer ──────────────────────────────────────────────────────────
def generate_team_graphic(team_code: str) -> BytesIO:
    """
    Generate a shareable prospects graphic for the given team code.
    Returns a BytesIO containing the PNG image.
    Raises ValueError if team_code is not recognised.
    """
    team_code = team_code.upper()
    if team_code not in TEAMS:
        raise ValueError(f"Unknown team code: {team_code}")

    _ensure_fonts()

    team_name, team_rgb = TEAMS[team_code]
    prospects, _n_sources = _load_team_prospects(team_code)

    # Clamp display list to top 10
    prospects = prospects[:10]

    # ── Layout constants ──────────────────────────────────────────────────────
    W         = 1080
    HEADER_H  = 168
    COL_H     = 48       # column-header area height
    ROW_H     = 140 if len(prospects) <= 6 else 118
    FOOTER_H  = 108
    PADDING   = 16
    n_rows    = max(len(prospects), 1)
    H         = HEADER_H + COL_H + n_rows * ROW_H + FOOTER_H + PADDING * 2

    img  = Image.new("RGB", (W, H), (10, 14, 22))

    # Gradient bg
    try:
        import numpy as np
        arr = np.full((H, W, 3), [10, 14, 22], dtype=np.uint8)
        for y in range(H // 2):
            frac = 1 - y / (H // 2)
            arr[y, :, 0] = min(255, 10 + int(frac * 20))
            arr[y, :, 1] = min(255, 14 + int(frac * 26))
            arr[y, :, 2] = min(255, 22 + int(frac * 48))
        img.paste(Image.fromarray(arr), (0, 0))
    except ImportError:
        pass  # numpy optional; fall back to flat bg

    draw = ImageDraw.Draw(img)

    # ── Colors ────────────────────────────────────────────────────────────────
    TEAL      = (14, 165, 160)
    ACCENT    = team_rgb          # team color for rank numbers + top bar
    WHITE_HI  = (230, 237, 243)
    TEXT_MID  = (160, 174, 192)
    TEXT_LO   = (107, 122, 141)
    SOX_BLACK = (10,  12,  16)
    TEAL_DIM  = (10, 110, 106)

    # ── Top accent bar (team color) ────────────────────────────────────────────
    draw.rectangle([0, 0, W, 7], fill=ACCENT)

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([0, 7, W, HEADER_H], fill=SOX_BLACK)

    abbr_font = _fb(104)
    draw.text((52, 16), team_code, font=abbr_font, fill=(240, 240, 240))
    draw.rectangle([52, 126, min(52 + len(team_code) * 62, 420), 128], fill=ACCENT)
    draw.text((52, 136), team_name, font=_fd(21), fill=TEXT_MID)

    draw.text((W - 52, 36),  "TOP",        font=_fb(50), fill=ACCENT,    anchor="rt")
    draw.text((W - 52, 84),  "PROSPECTS",  font=_fb(50), fill=WHITE_HI,  anchor="rt")
    draw.text((W - 52, 140), "Ranked by",  font=_fd(17), fill=TEXT_LO,   anchor="rt")
    draw.text((W - 52, 155), "RANKLE.DEV", font=_fb(24), fill=TEAL,      anchor="rt")

    # ── Column headers ────────────────────────────────────────────────────────
    COL_Y = HEADER_H + 14
    hf = _fd(15)
    draw.text((52,  COL_Y), "#",      font=hf, fill=TEXT_LO)
    draw.text((162, COL_Y), "PLAYER", font=hf, fill=TEXT_LO)
    draw.text((622, COL_Y), "POS",    font=hf, fill=TEXT_LO)
    draw.text((714, COL_Y), "AGE",    font=hf, fill=TEXT_LO)
    draw.text((812, COL_Y), "ETA",    font=hf, fill=TEXT_LO)
    draw.rectangle([38, COL_Y + 22, W - 38, COL_Y + 23], fill=(255, 255, 255, 12))

    # ── Measure rank column width ─────────────────────────────────────────────
    rank_font = _fb(56 if ROW_H >= 140 else 48)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_rw = max(
        (tmp.textlength(str(p["best"]), font=rank_font) for p in prospects),
        default=60,
    )
    RANK_RIGHT = 52 + int(max_rw) + 10
    NAME_LEFT  = RANK_RIGHT + 18

    # ── Rows ──────────────────────────────────────────────────────────────────
    ROW_Y0 = COL_Y + 30

    if not prospects:
        draw.text((W // 2, ROW_Y0 + 60),
                  "No prospects found in the consensus rankings.",
                  font=_fd(22), fill=TEXT_LO, anchor="mm")
    else:
        for i, p in enumerate(prospects):
            y = ROW_Y0 + i * ROW_H
            row_fill = (14, 20, 33) if i % 2 == 0 else (18, 26, 42)
            draw.rounded_rectangle([38, y, W - 38, y + ROW_H - 8],
                                   radius=10, fill=row_fill)
            draw.rounded_rectangle([38, y, 46, y + ROW_H - 8],
                                   radius=4, fill=TEAL_DIM)

            # Rank (use best rank = highest placement)
            draw.text((RANK_RIGHT, y + ROW_H // 2 - 8),
                      str(p["best"]), font=rank_font, fill=ACCENT, anchor="rm")

            # Player info
            name_y_offset = 22 if ROW_H >= 140 else 16
            draw.text((NAME_LEFT, y + name_y_offset), p["name"],
                      font=_fd(28 if ROW_H >= 140 else 24), fill=WHITE_HI)

            detail_y = name_y_offset + 36 if ROW_H >= 140 else name_y_offset + 30
            cov_y    = detail_y + 28 if ROW_H >= 140 else detail_y + 24

            draw.text((NAME_LEFT, y + detail_y),
                      f"Consensus range: #{p['best']}–#{p['worst']}",
                      font=_fd(19 if ROW_H >= 140 else 16), fill=TEXT_LO)

            if ROW_H >= 140:
                draw.text((NAME_LEFT, y + cov_y),
                          _coverage(p["n_lists"]),
                          font=_fd(19), fill=TEXT_MID)

            # Badge / age / eta
            mid_y = y + ROW_H // 2 - 4
            _badge(draw, 648, mid_y, p["pos"])
            draw.text((726, mid_y), str(p["age"]),
                      font=_fd(26 if ROW_H >= 140 else 22), fill=TEXT_MID, anchor="mm")
            draw.text((826, mid_y), p["eta"],
                      font=_fd(26 if ROW_H >= 140 else 22), fill=TEXT_MID, anchor="mm")

            if i < len(prospects) - 1:
                sy = y + ROW_H - 6
                draw.rectangle([54, sy, W - 54, sy + 1], fill=(255, 255, 255, 8))

    # ── Footer ────────────────────────────────────────────────────────────────
    FY = ROW_Y0 + n_rows * ROW_H + PADDING
    draw.rectangle([38, FY, W - 38, FY + 1], fill=(255, 255, 255, 16))
    draw.text((W // 2, FY + 20),
              "Consensus rankings aggregated from top prospect analysts.",
              font=_fd(18), fill=TEXT_LO, anchor="mm")
    draw.text((W // 2, FY + 50), "RANKLE.DEV",
              font=_fb(40), fill=TEAL, anchor="mm")
    draw.text((W // 2, FY + 84),
              "Full rankings • Volatility scores • Consensus metrics",
              font=_fd(18), fill=TEXT_LO, anchor="mm")

    # ── Crop and return ───────────────────────────────────────────────────────
    content_h = FY + FOOTER_H
    final = img.crop((0, 0, W, content_h))

    buf = BytesIO()
    final.save(buf, "PNG")
    buf.seek(0)
    return buf


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    code = sys.argv[1].upper() if len(sys.argv) > 1 else "CHW"
    out_path = os.path.join(BASE_DIR, f"{code.lower()}_prospects.png")
    buf = generate_team_graphic(code)
    with open(out_path, "wb") as f:
        f.write(buf.read())
    print(f"Saved: {out_path}")
