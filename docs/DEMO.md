# Five-minute demo

Works with no internet connection. Start with `streamlit run app/main.py` and
choose **Synthetic demo data** in the sidebar (amber badge: simulated series).

| Minute | Page | Do | Point to make |
|---|---|---|---|
| 0:00 | Overview | Read the badge and the three-line description | Every page says which data it is using |
| 0:15 | Investment Lab | Change a weight; switch on portfolio C; open Compare and Risk insights | Portfolios are simulated with real transactions and compared on one window; history and estimates are labelled separately |
| 0:30 | Strategy Lab | Set fast 20, slow 100 | Green bands show exactly when the rule holds the asset; a decision dated T trades at the open of T+1 |
| 1:30 | Backtesting | Look at the five cards, then the drawdown chart | Strategy and benchmark run through the same engine and costs |
| 2:15 | Backtesting -> Trades & costs | Open the ledger | Every fill is dated after its decision; fees and slippage are itemised |
| 2:45 | Backtesting -> Export | Download the HTML summary | Exports describe the run on screen, including the data source |
| 3:15 | Risk Analytics | Set one weight to 0 | Capital share versus risk share |
| 3:45 | Monte Carlo | Change the seed, then change it back | Same seed, same fingerprint: reproducible; the note explains why this is not a forecast |
| 4:15 | Research & Reporting | Read the result table and the yellow note | A pre-specified study that reports a negative result with its limits |

Then, if online, switch the source to **Yahoo Finance daily data**, or upload the
two sample files from `examples/sample_data/` under **My own CSV files**.
