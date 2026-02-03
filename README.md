# ProspectRank

Consensus MLB prospect rankings from 6+ sources using Borda Count.

## How it works

Percentile Normalization - ranks mapped to 0-100 so list length does not matter.
Borda Score - mean of normalized scores across all sources.
Median Rank - median of raw ranks, robust to outliers.
Volatility - sample standard deviation. Low SD means sources agree.

## Running locally

Open index.html in any browser. No build step needed.
