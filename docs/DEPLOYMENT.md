# Deployment readiness: Streamlit Community Cloud

> **What the hosted app is.** The Streamlit dashboard, including the Investment Lab's
> Future Wealth mode. The **Quant Research Copilot is not a web feature**: it is an MCP server
> for Claude Code or Claude Desktop, run locally from a checkout (`docs/copilot.md`).

**Not deployed.** This document records what was verified and the exact steps
to deploy once the owner approves.

## Steps

1. Publish the **public candidate** (fresh history, no dataset) as its own
   GitHub repository. Never deploy from the private repository: it contains
   the restricted dataset (see [DATA.md](DATA.md)).
2. At share.streamlit.io choose **Create app**, select the repository and branch.
3. Main file path: `app/main.py`.
4. Advanced settings: Python 3.12 (3.11 and 3.13 also pass the test suite).
5. No secrets are required. In **Advanced settings → Secrets** (Streamlit exposes
   top-level entries as environment variables) add:

   ```toml
   QUANTLAB_DEFAULT_SOURCE = "synthetic"   # first visit always works, clearly labelled
   QUANTLAB_PUBLIC_DEMO = "1"              # visitors cannot write to the server
   ```

   `QUANTLAB_PUBLIC_DEMO` makes the shared server read-only for visitors and keeps
   third-party data off it:
   - Future Wealth's "Record this forecast" is switched off (it would append to a
     shared, ephemeral server file any visitor could fill);
   - the data sources are synthetic data and the visitor's own CSV files only. Live
     Yahoo Finance data is not offered, because Yahoo's terms permit personal use and
     grant no redistribution, and a public server would be relaying it.
6. Optionally set `QUANTLAB_CACHE_DIR` to a persistent, writable folder for the
   live-data cache (default `.data_cache/` next to the app). If the folder cannot
   be written the app serves the verified data it has and never contacts Yahoo.
7. Deploy. Dependencies come from `requirements.txt`. For a fully pinned,
   hash-checked install use `requirements/lock.txt` instead (see
   [qa/REPRODUCIBILITY.md](qa/REPRODUCIBILITY.md)).

## Checklist

| Requirement | Status | Evidence |
|---|---|---|
| Entry point | PASS | `streamlit run app/main.py` serves HTTP 200 and `/_stcore/health` returns `ok` |
| Dependencies | PASS | Fresh virtual environment with only `pip install -r requirements.txt` (package not installed): app starts and all 8 pages render in a browser |
| Python version | PASS | Test suite passes on 3.11, 3.12 and 3.13 |
| No credentials needed | PASS | No secrets, tokens or keys anywhere in the code or history |
| Startup behaviour | PASS | First page in about 4 s with live data, under 1 s with synthetic data |
| Resource use | PASS, modest | Largest page run about 3 s of CPU; default Monte Carlo is 1,000 x 252 values; uploads capped at 20 MB |
| Caching | PASS | Live data cached for one hour in memory and 12 hours on disk; synthetic and snapshot data cached per input; no user data is cached across sessions |
| Offline / provider failure | PASS | In a network-isolated namespace: live source shows a clear error and a one-click switch to synthetic data; synthetic mode renders every page |
| Data-source labels | PASS | Badge on every page; synthetic warning on every page (tested) |
| Error handling | PASS | Invalid tickers, impossible parameters, short history, leverage: message, never a traceback (tested) |
| Restricted data not exposed | PARTIAL | The app never serves raw files, but if `experiments/data/` is in the deployed repository the "Frozen research snapshot" source displays and exports those prices. Deploy from a copy without that folder; the option then disappears automatically |
| Behaviour on Community Cloud itself | **UNVERIFIED** | Nothing was deployed. Yahoo may rate-limit shared cloud addresses more aggressively than was seen here |
| Exports on the hosted app | **UNVERIFIED** | Downloads are generated in memory and worked in local browser tests |
| Disk cache on an ephemeral host | PARTIAL | `.data_cache/` is written next to the app unless `QUANTLAB_CACHE_DIR` names another folder; on Community Cloud it is lost at restart, which only costs a re-download. A read-only folder no longer crashes the app (QA-006) |
| Pinned dependencies | PASS | `requirements/lock.txt` (hash-locked) installs and passes the suite on 3.11, 3.12, 3.13 from a fresh environment (`tools/verify_clean_env.sh`, CI job `locked`) |
| Dependency vulnerabilities | PASS (2026-11-17) | `pip-audit` of both lock files: none known; re-run weekly in CI |

Overall: **technically prepared; hosting behaviour is UNVERIFIED until a first
real deployment.** Deploy only from the public candidate, which contains no
restricted dataset.

## Local versus hosted: expected differences

| Topic | Local | Community Cloud |
|---|---|---|
| Live Yahoo data | Usually works; occasional rate limit | Shared addresses are rate limited more often. The app then shows an error and a button for synthetic data; it never substitutes silently |
| Disk cache (`.data_cache/`) | Persists between runs, including the record of the last request | Lost on every restart: data is re-downloaded and the retry cooldowns start again, so a restart can cause an extra request |
| Refresh | Runs when someone opens or refreshes the app | Same: no scheduler. An app that is asleep does not check anything |
| Frozen research snapshot | Offered if the private folder exists | Not offered: the folder is not in the public candidate |
| First load | About 4 s | Slower after the app has been asleep |
| Memory | Not constrained | About 1 GB; workloads are far below this; the Monte Carlo page refuses requests above 5,000,000 simulated values (about 120 MB) |
| Python | Whatever you installed | Chosen in Advanced settings; use 3.12 |
