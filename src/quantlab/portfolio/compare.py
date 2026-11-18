"""Compare hypothetical portfolios fairly: one data window, one calendar, one cost model.

Every portfolio here is run through the transaction engine (next-open fills,
costs, contributions). Nothing is approximated with fixed daily weights.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quantlab.analytics.flows import flow_summary
from quantlab.analytics.metrics import performance_summary
from quantlab.backtesting.engine import BacktestResult
from quantlab.data.cleaning import InsufficientHistoryError
from quantlab.data.models import MarketData
from quantlab.execution.costs import ExecutionConfig
from quantlab.portfolio.spec import PortfolioSpec, simulate_portfolio
from quantlab.reporting.experiment import environment
from quantlab.reporting.exports import cost_summary

SCHEMA = "quantlab.investment_lab/1"
MIN_SESSIONS = 60
MAX_BENCHMARKS = 3


def common_window(data: MarketData, tickers: list[str]) -> MarketData:
    """The part of ``data`` from the first session on which every listed instrument has a price.

    Using one window for every portfolio in a comparison stops an instrument's
    longer history from flattering or penalising whichever portfolio holds it.
    """
    used = [t for t in dict.fromkeys(tickers)]
    if not used:
        raise ValueError("No instruments to compare")
    sub = data.select(used)
    complete = sub.close.notna().all(axis=1)
    if not complete.any():
        raise InsufficientHistoryError("The selected instruments have no session in common")
    window = sub.window(complete.idxmax(), None)
    if len(window.dates) < MIN_SESSIONS:
        raise InsufficientHistoryError(
            f"Only {len(window.dates)} sessions are common to all selected instruments; "
            f"at least {MIN_SESSIONS} are needed"
        )
    return window


def data_fingerprint(data: MarketData) -> str:
    """Short hash of the open and close panels: identifies the exact data behind a result."""
    payload = data.open.round(6).to_csv() + data.close.round(6).to_csv()
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def equivalence_key(spec: PortfolioSpec) -> tuple:
    """What determines a portfolio's simulated outcome, given shared funding and costs.

    Two specs with the same key produce identical results. Rebalancing cannot change
    a portfolio that holds a single instrument and no cash, so it is ignored there.
    """
    weights = tuple(sorted((t, round(w, 10)) for t, w in spec.weights.items() if w > 0))
    trivial = len(weights) == 1 and spec.cash_weight <= 1e-10
    return weights, None if trivial else spec.rebalance


def benchmark_specs(
    spec: PortfolioSpec, universe: list[str] | None = None
) -> dict[str, PortfolioSpec]:
    """Simple alternatives funded exactly like ``spec``, each genuinely different (QA-001).

    Candidates, in order:

    * everything in the largest holding, never rebalanced
    * equal weights across the held instruments, same rebalancing policy
    * the same weights with the opposite maintenance choice: never rebalanced if
      ``spec`` rebalances, rebalanced annually if it does not
    * only if fewer than two of those are distinct, and ``universe`` lists instruments the
      portfolio does not hold: equal weights across every loaded instrument (rebalanced
      annually), then 100% in each unheld instrument

    A candidate that would simulate identically to ``spec`` or to an earlier candidate
    (see :func:`equivalence_key`) is dropped, so no duplicate column is ever offered.
    At most ``MAX_BENCHMARKS`` are returned.
    """
    held = spec.tickers
    if not held:
        return {}
    largest = max(held, key=lambda t: (spec.weights[t], -held.index(t)))
    candidates = [
        replace(spec, weights={largest: 1.0}, rebalance=None, name=f"100% {largest}"),
        replace(spec, weights={t: 1.0 / len(held) for t in held}, name="Equal weight"),
    ]
    if spec.rebalance is None:
        candidates.append(replace(spec, rebalance="A", name="Same weights, rebalanced annually"))
    else:
        candidates.append(replace(spec, rebalance=None, name="Same weights, never rebalanced"))
    seen = {equivalence_key(spec)}
    out: dict[str, PortfolioSpec] = {}

    def offer(candidate: PortfolioSpec) -> None:
        key = equivalence_key(candidate)
        if key not in seen and candidate.name not in out and len(out) < MAX_BENCHMARKS:
            seen.add(key)
            out[candidate.name] = candidate

    for candidate in candidates:
        offer(candidate)
    others = [t for t in dict.fromkeys(universe or []) if t not in held]
    if len(out) < 2 and others:  # the portfolio is too simple for its own alternatives
        everything = list(dict.fromkeys([*held, *others]))
        equal = {t: 1.0 / len(everything) for t in everything}
        label = "Equal weight, all loaded instruments"
        offer(replace(spec, weights=equal, rebalance="A", name=label))
        for t in others:
            offer(replace(spec, weights={t: 1.0}, rebalance=None, name=f"100% {t}"))
    return out


def allocation_drift(result: BacktestResult, spec: PortfolioSpec) -> pd.Series:
    """Largest absolute gap between an actual and a target weight at each close (cash included).

    Measured from the first session on which the portfolio is invested.
    """
    weights = result.weights
    target = pd.Series(0.0, index=weights.columns)
    for ticker, w in spec.weights.items():
        if ticker in target.index:
            target[ticker] = w
    gaps = (weights - target).abs()
    cash_gap = ((1.0 - weights.sum(axis=1)) - spec.cash_weight).abs()
    drift = pd.concat([gaps, cash_gap.rename("cash")], axis=1).max(axis=1)
    invested = result.holdings.to_numpy().sum(axis=1) > 0
    if not invested.any():
        return drift.iloc[0:0]
    return drift.loc[result.equity.index[np.argmax(invested)] :].rename("drift")


@dataclass(frozen=True)
class Comparison:
    data: MarketData  # the common window every portfolio was simulated on
    specs: dict[str, PortfolioSpec]
    results: dict[str, BacktestResult]
    stats: dict[str, dict]
    config: ExecutionConfig
    risk_free: float
    fingerprint: str

    @property
    def window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.data.dates[0], self.data.dates[-1]

    def table(self, keys: list[str]) -> pd.DataFrame:
        return pd.DataFrame({name: {k: s.get(k) for k in keys} for name, s in self.stats.items()})

    def values(self) -> pd.DataFrame:
        """Portfolio value at each close (includes contributed money)."""
        return pd.DataFrame({name: r.equity for name, r in self.results.items()})

    def growth_of_one(self) -> pd.DataFrame:
        """Time-weighted growth of 1: what the holdings did, with contributions neutralised."""
        return pd.DataFrame({n: (1.0 + r.returns).cumprod() for n, r in self.results.items()})

    def contributed(self) -> pd.Series:
        """Cumulative money paid in. Identical for every portfolio in a comparison."""
        first = next(iter(self.results.values()))
        return (first.config.initial_capital + first.cash_flows.cumsum()).rename("Contributed")


def portfolio_stats(result: BacktestResult, spec: PortfolioSpec, risk_free: float = 0.0) -> dict:
    """Return, risk, funding, cost and drift figures for one simulated portfolio."""
    drift = allocation_drift(result, spec)
    costs = cost_summary(result)
    return {
        **performance_summary(result.returns, risk_free=risk_free, turnover=result.turnover,
                              trades=result.trades),  # fmt: skip
        **flow_summary(result),
        "trading_cost": costs["total_cost"],
        "trading_cost_pct_of_invested": costs["total_cost"] / (
            result.config.initial_capital + float(result.cash_flows.sum())
        ),
        "drift_average": float(drift.mean()) if len(drift) else float("nan"),
        "drift_max": float(drift.max()) if len(drift) else float("nan"),
        "worst_day": float(result.returns.min()),
        "cash_weight_target": spec.cash_weight,
    }


def compare_portfolios(
    data: MarketData,
    specs: dict[str, PortfolioSpec],
    config: ExecutionConfig | None = None,
    risk_free: float = 0.0,
) -> Comparison:
    """Simulate every portfolio on the same window, calendar and costs.

    The window starts at the first session on which every instrument held by
    ANY of the portfolios has a price. All portfolios must share one funding
    plan (initial amount, contribution, frequency); otherwise money-weighted
    figures and final values would not be comparable.
    """
    if not specs:
        raise ValueError("Nothing to compare")
    plans = {(s.initial_amount, s.contribution, s.contribution_frequency) for s in specs.values()}
    if len(plans) > 1:
        raise ValueError("Portfolios in one comparison must share the same funding plan")
    tickers = [t for spec in specs.values() for t in spec.tickers]
    window = common_window(data, tickers)
    cfg = config or ExecutionConfig()
    results = {
        name: simulate_portfolio(spec, window, cfg, own_calendar=False)
        for name, spec in specs.items()
    }
    stats = {name: portfolio_stats(results[name], specs[name], risk_free) for name in specs}
    return Comparison(window, dict(specs), results, stats, cfg, risk_free, data_fingerprint(window))


def analysis_record(comparison: Comparison, data_status: dict | None = None) -> dict:
    """A portable, reproducible description of a comparison. Holds no account or personal data."""
    start, end = comparison.window
    meta = comparison.data.metadata
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "portfolios": {name: spec.to_dict() for name, spec in comparison.specs.items()},
        "execution": asdict(comparison.config),
        "risk_free": comparison.risk_free,
        "timing": "decisions after a close; fills at the next session's open; contributions "
        "arrive at the open of the first session of each period and are normally invested at "
        "the following open (an order decided at the previous close that fills on the deposit's "
        "own open is sized including the deposit, so it can be invested that day)",
        "window": {"start": str(start.date()), "end": str(end.date()),
                   "sessions": len(comparison.data.dates)},  # fmt: skip
        "data": {**meta.to_dict(), "fingerprint": comparison.fingerprint},
        "data_status": data_status,
        "results": comparison.stats,
        "environment": environment(),
        "notes": [
            "Historical simulation on adjusted prices (a total-return proxy, not executable "
            "quotes). Not a forecast and not investment advice.",
            "Taxes, interest on cash and withdrawals are not modelled.",
        ],
    }


def portfolio_file(specs: dict[str, PortfolioSpec], config: ExecutionConfig, risk_free: float,
                   fingerprint: str | None = None, window: dict | None = None) -> dict:  # fmt: skip
    """The saved-portfolio document: definitions and assumptions only, no results."""
    return {
        "schema": SCHEMA,
        "portfolios": {name: spec.to_dict() for name, spec in specs.items()},
        "execution": asdict(config),
        "risk_free": risk_free,
        "saved_with": {"fingerprint": fingerprint, "window": window},
    }


def load_portfolio_file(payload: dict) -> tuple[dict[str, PortfolioSpec], ExecutionConfig, float]:
    """Validate and rebuild a saved-portfolio document. Raises ValueError with a clear reason."""
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("Not a Quant Lab portfolio file (missing or unknown 'schema')")
    portfolios = payload.get("portfolios")
    if not isinstance(portfolios, dict) or not portfolios:
        raise ValueError("The file contains no portfolios")
    if len(portfolios) > 3:
        raise ValueError("At most three portfolios can be loaded")
    try:
        specs = {str(name): PortfolioSpec.from_dict(body) for name, body in portfolios.items()}
        fields = ExecutionConfig.__dataclass_fields__
        execution = {k: v for k, v in payload.get("execution", {}).items() if k in fields}
        cfg = ExecutionConfig(**execution)
        risk_free = float(payload.get("risk_free", 0.0))
    except (TypeError, KeyError) as exc:
        raise ValueError(f"The portfolio file is malformed: {exc}") from exc
    for spec in specs.values():
        if len(spec.weights) > 10:
            raise ValueError("A portfolio may hold at most 10 instruments")
    return specs, cfg, risk_free


def reproduction_status(payload: dict, fingerprint: str) -> tuple[bool, str]:
    """Whether a loaded file was saved against exactly the data now in use."""
    saved = (payload.get("saved_with") or {}).get("fingerprint")
    if not saved:
        return False, "The file does not record which dataset it was saved with."
    if saved == fingerprint:
        return True, "Same dataset as when the file was saved: results reproduce exactly."
    return False, (
        f"Different dataset (saved with {saved}, now {fingerprint}): the definitions were "
        "loaded, but results will not match the saved analysis exactly."
    )
