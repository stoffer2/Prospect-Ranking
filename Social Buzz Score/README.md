# Reddit Buzz Scraper for MLB Prospects

Tracks prospect mentions across Reddit and news, then calculates a **Buzz Score (0–100)** from engagement, recency, and sentiment.

---

## How to use it

1. **Install once:**  
   Double-click `setup.bat` or run:  
   `python -m pip install -r requirements.txt`

2. **Set up credentials** in `.env` (see Quick Start below).

3. **Provide your prospect list** (see “Your prospect list” below).

4. **Run the scraper:**
   ```powershell
   cd "c:\Users\stoff\Prospect-Ranking\Social Buzz Score"
   python reddit-buzz-scraper.py
   ```

5. **Check results:**
   - Scores print in the terminal (sorted by buzz score).
   - Full data (Reddit mentions + news + scores) is in **`buzz_results.json`**.

---

## Your prospect list

The script reads prospects from **`prospects.json`** in the same folder as the script.

- **If `prospects.json` is missing**, it uses 5 built-in test prospects (Holliday, Skenes, Langford, Cowser, Rafaela).
- **To use your own list**, create or edit `prospects.json` with this format:

```json
[
  {
    "id": "unique-slug",
    "first_name": "Jackson",
    "last_name": "Holliday",
    "team": "BAL",
    "position": "SS",
    "aliases": []
  }
]
```

**Fields:**

| Field         | Required | Example   | Notes                          |
|---------------|----------|-----------|---------------------------------|
| `id`          | Yes      | `"jackson-holliday"` | Unique slug, lowercase, hyphenated |
| `first_name`  | Yes      | `"Jackson"`         |                                |
| `last_name`   | Yes      | `"Holliday"`        |                                |
| `team`        | Yes      | `"BAL"`             | MLB team abbreviation          |
| `position`    | No       | `"SS"`               | Optional                       |
| `aliases`     | No       | `[]` or `["J-Holliday"]` | Other names to search for  |

There’s a full example in **`prospects.json.example`** — copy it to `prospects.json` and edit:

```powershell
copy prospects.json.example prospects.json
```

Then edit `prospects.json` with your prospects and run the script again.

---

## Quick Start (first-time setup)

1. **Double-click `setup.bat`** to install dependencies.
2. **Reddit API:** Go to https://www.reddit.com/prefs/apps → create a **script** app → Redirect URI: `http://localhost:8080`. Copy client ID and secret.
3. **Optional – News:** Get a key at https://gnews.io/register and add `GNEWS_API_KEY=...` to `.env`.
4. **Copy `.env.template` to `.env`** and fill in:
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
   - `REDDIT_USER_AGENT=ProspectBuzzTracker/1.0 by YourRedditUsername`
   - (Optional) `GNEWS_API_KEY`
5. **Run:** `python reddit-buzz-scraper.py`

---

## Files

- **`reddit-buzz-scraper.py`** – Main script (Reddit + news, buzz score).
- **`prospects.json`** – Your list of prospects (create from `prospects.json.example`).
- **`prospects.json.example`** – Example prospect list format.
- **`buzz_results.json`** – Output (created after each run).
- **`.env`** – Your API keys (never commit; see `.env.template`).

---

## Output example

```
============================================================
BUZZ SCORE RESULTS
============================================================
🔥 Jackson Holliday        | Score:  86.0 | 7d:   4 | 30d:  12 | News: 3
      📰 Headline about call-up... (positive)
      📰 Another story... (neutral)
📈 Paul Skenes             | Score:  72.3 | 7d:   2 | 30d:   8 | News: 2
...
```

Full details (every mention, every article, scores) are in **`buzz_results.json`**.