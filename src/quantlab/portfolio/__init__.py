from quantlab.portfolio.ledger import ConstraintViolation, Fill, Portfolio

__all__ = [
    "ConstraintViolation",
    "Fill",
    "Portfolio",
    "PortfolioSpec",
    "contribution_schedule",
    "simulate_portfolio",
]

_SPEC_NAMES = {"PortfolioSpec", "contribution_schedule", "simulate_portfolio"}


def __getattr__(name: str):
    # quantlab.portfolio.spec uses the backtesting engine, which itself uses the ledger in
    # this package. Loading it on first use avoids an import cycle.
    if name in _SPEC_NAMES:
        from quantlab.portfolio import spec

        return getattr(spec, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
