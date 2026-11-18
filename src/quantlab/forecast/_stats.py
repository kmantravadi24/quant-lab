"""Three distribution functions, so the forecasting package needs only NumPy and pandas at
run time. Each is checked against SciPy in the test suite (SciPy is a development dependency).
"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta function (modified Lentz)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(log_front) * _betacf(b, a, 1.0 - x) / b


def t_cdf(x: float, df: float) -> float:
    """Student t cumulative distribution function."""
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + x * x))
    return 1.0 - tail if x >= 0 else tail


def binom_ppf(q: float, n: int, p: float) -> int:
    """Smallest k with P(Binomial(n, p) <= k) >= q (the binomial quantile)."""
    if not 0 <= q <= 1:
        raise ValueError("q must be in [0, 1]")
    if p <= 0:
        return 0
    if p >= 1:
        return n
    log_p, log_q = math.log(p), math.log1p(-p)
    total = 0.0
    for k in range(n + 1):
        log_pmf = (
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * log_p
            + (n - k) * log_q
        )
        total += math.exp(log_pmf)
        if total >= q - 1e-12:
            return k
    return n
