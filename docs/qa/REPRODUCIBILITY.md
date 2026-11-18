# Reproducing the QA results and the frozen study

## 1. Environment

Python 3.11, 3.12 or 3.13. Three ways to install, from most to least reproducible:

```bash
# (a) Exactly the environment that produced the published study (Python 3.13, Linux x86-64):
python3.13 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements/study-py313.txt && pip install --no-deps -e .

# (b) The tested, hash-locked environment (any supported Python):
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements/lock.txt && pip install --no-deps -e .

# (c) Newest compatible releases (what the main CI matrix tests):
pip install -e ".[data,app,dev,agent]"
```

`tools/verify_clean_env.sh python3.12 /tmp/work` does (b) from nothing and then runs `pip check`,
Ruff, the full suite and the study verification. It passed on Python 3.11.18, 3.12.3 and 3.13.18
on 2026-11-17. CI runs it on 3.11 and 3.13 (job `locked`) and runs (a) with a zero-difference
assertion (job `study-exact`). Regenerate the locks after changing dependencies with:

```bash
uv pip compile pyproject.toml --extra data --extra app --extra dev --extra agent --universal \
  --python-version 3.11 --generate-hashes --no-header -o requirements/lock.txt
uv pip compile pyproject.toml --extra data --extra dev --python-version 3.13 \
  --python-platform x86_64-manylinux_2_28 --generate-hashes --no-header \
  -c requirements/study-constraints.txt -o requirements/study-py313.txt
```

The build backend (`setuptools`, used by `pip install -e .`) is not hash-locked.

## 2. Run the checks

```bash
ruff check .                                   # lint
python -m pytest -q                            # everything: 669 passed (no expected failures remain)
python -m pytest -q tests/qa                   # QA and remediation suites (A-P)
python -m pytest -q tests/qa -rx               # list each expected failure with its backlog ID
python -m pytest -q tests/qa/test_d_math.py    # one suite
python -m build --wheel                        # package build (needs `pip install build`)
```

Everything is offline and deterministic: scripted data provider, settable clock, temporary cache
folders, fixed seeds, Hypothesis in `derandomize` mode. The suite never reads or writes the real
`.data_cache` folder. Expected time: about two minutes.

After the remediation campaign there are no strict expected failures: every confirmed defect that
was fixed has an ordinary acceptance test. A new confirmed defect should again be pinned with
`@pytest.mark.xfail(strict=True, reason="QA-0xx: ...")`. Any **FAILED** is new and needs triage.

## 3. Browser checks

Needs Node 20+ and Playwright with Chromium:

```bash
npm install --no-save playwright@1.63.0 && npx playwright install --with-deps chromium
tests/browser/run.sh                # starts a local server on synthetic data, runs 23 checks, stops it
tests/browser/run.sh shots/         # same, and writes screenshots and browser_results.json
```

Port: `QL_BROWSER_PORT` (default 8765). CI runs this as a separate `browser` job.

## 4. Reproduce the frozen study

```bash
python experiments/trend_vs_buyhold.py --verify
```

Expected output in the study environment (1a):

```
dataset fingerprint 76f294e718c47ee2 (matches the original snapshot)
429 numeric results compared; largest absolute difference 0
PASS: the committed record is reproduced
```

With other NumPy/pandas versions (1b, 1c) the largest difference is about 4e-14: floating-point
summation order differs between library versions. The script accepts differences up to 1e-9 as a
reproduction; only the study environment is bit for bit. This is the same on the untouched QA
baseline commit, so it is not caused by any later change (backlog QA-043).

This re-runs the whole protocol from `experiments/data/` and compares every number with
`experiments/results/trend_vs_buyhold_103ff696a37b.json`. `tests/qa/test_i_j_research_exports.py`
additionally checks that the record's file name equals the hash of its protocol and that each data
file matches the SHA-256 in `experiments/MANIFEST.json`.

## 4b. Reproduce a dashboard analysis

Every export records the dataset fingerprint, window, portfolio definition, settings and software
versions. The Investment Lab additionally offers:

- a **portfolio file** (definitions and assumptions; reload it in the Investment Lab), and
- for synthetic or user-supplied data only, a **price bundle** (`quantlab_prices.zip`): one CSV per
  instrument in the upload format plus the fingerprint. Upload the CSVs under "My own CSV files"
  and load the portfolio file: every number reproduces bit for bit (`test_o01_*`).

Prices from Yahoo Finance are never bundled (rights not established); the fingerprint identifies
them, and the dashboard reports when the provider has since revised history (QA-007).

## 4c. Cache location

Live data is cached in `.data_cache/` in the repository, or in the folder named by
`QUANTLAB_CACHE_DIR`. On a host whose application folder is read-only or wiped on deploy, point
it at a persistent writable volume. If the folder cannot be written, the dashboard serves the
verified data it already has and never contacts the provider.

## 5. Monte Carlo sensitivity experiment

```bash
python docs/qa/evidence/mc_sensitivity.py out.csv     # from the repository root; about 90 s
```

Compares with `docs/qa/evidence/mc_sensitivity.csv`. Needs the frozen dataset. The numbers are
measurements for the report, not test targets.

## 6. Limits on reproduction

| Limit | Effect |
|---|---|
| **The frozen dataset is private.** It was derived from Yahoo Finance and redistribution rights are not established (`MANIFEST.json`: `NOT ESTABLISHED`). It exists only in the private repository. | Without `experiments/data/` the study verification and the Monte Carlo experiment cannot run. CI skips the verification step when the folder is absent; the checksum test skips its file loop. All other tests use synthetic data and still run. |
| **The public candidate omits the dataset.** | A reader of the public candidate can run every test and read the record and report, but cannot independently reproduce the study's numbers. Downloading the same tickers again is not equivalent: providers revise adjusted history, so the fingerprint will differ. |
| **The dataset covers three tickers** (IWM, QQQ, SPY; 1993-01-01 to 2026-10-31). | Bonds, cash rates and other assets are not in it; examples involving BND use synthetic or user data. |
| **Bit-for-bit reproduction needs the study environment.** | `requirements/study-py313.txt` pins it; other versions agree to about 4e-14. |
| **Live data is not reproducible by nature.** | Analyses on Yahoo data are identified by a fingerprint; revisions are now reported (QA-007), but the prices cannot be packaged with exports until redistribution rights are established (QA-031, QA-035). |
| **Synthetic data is not market data.** | It is generated from a seed for tests and demos, is labelled as synthetic everywhere, and supports no market conclusion. |
| **Timings** | Measured on one shared container; indicative only. |
