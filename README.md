\# ProspectRank



Consensus MLB prospect rankings aggregated from 6+ sources using a normalized Borda Count algorithm.



\## How it works



\- \*\*Percentile Normalization\*\* - ranks are mapped to a 0-100 score so that #1 on a Top-500 list equals #1 on a Top-100 list.

\- \*\*Borda Score\*\* - mean of normalized scores across all sources that ranked a prospect.

\- \*\*Median Rank\*\* - median of raw ranks, robust to outliers.

\- \*\*Volatility\*\* - sample standard deviation of normalized scores. Low SD = sources agree.



\## Running locally



Open index.html in any browser. No build step, no dependencies.

