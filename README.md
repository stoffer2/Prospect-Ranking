# Rankle

Data-driven MLB prospect rankings that aggregate expert lists from 9+ sources into a single consensus view using the Rankle Score.

## How it works

- **Percentile normalization** – Raw ranks are converted to a 0–100 scale so list length doesn't matter. #1 on a Top-100 list scores the same as #1 on a Top-500 list.

- **Rankle Score** – Each source's rankings are converted to Z-scores (using the theoretical mean and standard deviation of a 1..N uniform distribution), averaged across sources, then scaled to 0–100. Bayesian shrinkage is applied for single-source prospects.

- **Volatility** – Sample standard deviation of Z-scores across sources. Low (&lt;0.3) = sources agree. Moderate (0.3–0.7) = some disagreement. High (0.7–0.85) = significant divergence. Extreme (≥0.85) = major outlier or stark disagreement.

- **Sources** – MLB Pipeline, Baseball America, FanGraphs, Bleacher Report, ESPN, Just Baseball, RotoProspects, Prospect361, RotoChamp.

## Features

- **Filters** – Search by player name, filter by position, team, and volatility (Low, Moderate, High, Extreme)
- **Consensus indicators** – Visual dots show how many sources ranked each prospect
- **Single-source warning** – Prospects with only one source are flagged
- **Responsive layout** – Works on desktop, tablet, and mobile

## Design

- Dark theme with navy backgrounds and blue accents
- Two-column hero with left-aligned content and Top 5 preview card
- Oswald font for headlines; DM Sans for body text
- Gold/silver/bronze rank badges for top tiers

## Running locally

Open `index.html` in any browser. No build step required.

### Roster upload

Use **Upload your league's roster** in the header to import a fantasy league CSV (e.g. Fantrax export). The parser accepts Player + Owner/Status columns and supports both comma- and tab-delimited files.

### FA prospects list

```bash
node fa-prospects.js [path-to-roster.csv]
```

Outputs prospects who are free agents in your league. Defaults to `roster.csv` in the project root.
