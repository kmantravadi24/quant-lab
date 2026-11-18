# Notices

## Licence

Quant Lab is (c) 2026 Kriti Mantravadi and is licensed under the Business Source
License 1.1 ([LICENSE](LICENSE)): source-available, not open source. Personal
non-commercial and academic production use is permitted; any other production use,
including hosted, subscription or embedded services, commercial products and client
services, requires a commercial licence from the Licensor. Each version converts to
the Apache License 2.0 on its Change Date (version 0.2.0: 2030-11-18). The licence
covers the code and documentation only and grants no rights in any market data.

## Third-party software

Quant Lab depends on, but does not bundle or modify, the following packages.
Each is installed from PyPI under its own licence.

| Package | Used for | Licence |
|---|---|---|
| NumPy | numerical arrays | BSD-3-Clause |
| pandas | time series and tables | BSD-3-Clause |
| Streamlit | dashboard | Apache-2.0 |
| Plotly | charts | MIT |
| yfinance | optional live data download | Apache-2.0 |
| exchange_calendars | exchange sessions, holidays and early closes (with live data) | Apache-2.0 |
| mcp | optional Research Copilot server (`[agent]` extra) | MIT |
| SciPy | independent cross-checks in tests only | BSD-3-Clause |
| pytest, Ruff | development | MIT |

Every package in the hash-locked environment (`requirements/lock.txt`, 70 packages
including transitive dependencies) was checked on 2026-11-18: all are under permissive
licences (MIT, BSD, Apache-2.0, PSF, Zlib, CC0), except certifi and hypothesis (MPL-2.0,
file-level copyleft; used unmodified, hypothesis in tests only). None is copied into
this repository. Licences are as published by each project; check again before
redistributing a bundled build.

## Market data

No market data is included. Data downloaded through `yfinance` comes from
Yahoo Finance and is subject to Yahoo's terms of service, which permit personal
use and do not grant redistribution rights. Quant Lab is not affiliated with or
endorsed by Yahoo. See [docs/DATA.md](docs/DATA.md).

## Disclaimer

For research and education. Not investment advice. Historical simulations do
not predict future results.
