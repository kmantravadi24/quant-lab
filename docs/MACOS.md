# Running Quant Lab on macOS

**Status: not tested on macOS.** Development and all recorded verification ran
on Linux (Python 3.11, 3.12 and 3.13). The code uses only `pathlib` paths and
pure-Python or wheel-distributed dependencies, and no Linux-specific calls, so
it is expected to work, but that is a review finding, not a test result. Use
the checklist below to confirm.

## Install

```bash
# 1. Python 3.11 to 3.13 (check with: python3 --version). If needed:
brew install python@3.12

# 2. Get the code
git clone <repository-url> quant-lab && cd quant-lab

# 3. Virtual environment (zsh is the default shell; keep the quotes)
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[data,app,dev]"
```

Apple Silicon and Intel Macs both have prebuilt wheels for NumPy, pandas and
SciPy on these Python versions; no compiler is needed.

## Verify

| Step | Command | Expected |
|---|---|---|
| 1 | `python -m pytest -q` | `402 passed` in about a minute |
| 2 | `ruff check .` | `All checks passed!` |
| 3 | `python examples/quickstart.py` | prints statistics and four fills |
| 4 | `streamlit run app/main.py` | browser opens at http://localhost:8501 |
| 5 | Sidebar -> Source -> **Synthetic demo data** | amber badge; all eight pages render |
| 6 | Source -> **My own CSV files**, upload both files in `examples/sample_data/` | blue badge, DEMOA and DEMOB |
| 7 | Backtesting -> Export -> **Research summary (HTML)** | a file downloads and opens in Safari |
| 8 | Source -> **Yahoo Finance daily data** | green badge, or a clear error if Yahoo is rate limiting |
| 9 (private repository only) | `python experiments/trend_vs_buyhold.py --verify` | `PASS ... largest absolute difference 0` |

If step 1 fails, please record the failing test names: that is the macOS
evidence this project does not yet have.

## Known macOS points

- The first `streamlit run` may ask for an email address; press Enter to skip.
- macOS may ask to allow incoming connections for Python; the app only needs localhost.
- To stop the app press Ctrl+C in the terminal.
- Floating-point results can differ in the last digits between platforms and
  library builds. The test suite uses tolerances; `--verify` treats differences
  below 1e-9 as a pass.
