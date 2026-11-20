"""How much between-person signal a clock keeps when CpGs are missing.

Measured, not assumed. On 2026-11-19 the Horvath 2013 clock (353 CpGs) was run
over one cohort of 24 people at eight coverage levels, through biolearn 0.9.1
and pyaging 0.6.2. Both libraries fill missing sites from reference-cohort
medians, so predictions stay plausible while the spread between people
collapses: the clock stops measuring the person and reports the filler.

The pairs below are that experiment's between-person standard deviations.
Full detail: project doc 34; script clock_coverage.py.

LIMITS, and they matter: one clock, one synthetic cohort, one platform. Applying
this curve to any other clock is extrapolation, and every API response says so.
"""
from bisect import bisect_left

# (coverage, between-person sd in predicted years) - biolearn 0.9.1 column
MEASURED = [
    (0.000, 0.00),
    (0.003, 0.33),
    (0.048, 3.72),
    (0.099, 5.84),
    (0.300, 12.85),
    (0.708, 16.58),
    (0.901, 18.11),
    (1.000, 18.05),
]
FULL_SD = 18.05
SOURCE = "Horvath 2013, 353 CpGs, 24 synthetic samples, biolearn 0.9.1 / pyaging 0.6.2, 2026-11-19"


def retained_signal(coverage: float) -> float:
    """Fraction of the full-coverage between-person spread, by linear
    interpolation between measured points. 1.0 means no loss, 0.0 means the
    clock returns effectively the same number for everybody."""
    if coverage <= 0:
        return 0.0
    if coverage >= 1:
        return 1.0
    xs = [c for c, _ in MEASURED]
    i = bisect_left(xs, coverage)
    x0, y0 = MEASURED[i - 1]
    x1, y1 = MEASURED[i]
    sd = y0 + (y1 - y0) * (coverage - x0) / (x1 - x0)
    return min(1.0, sd / FULL_SD)


# Bands below are THIS TOOL'S rule of thumb, not a published standard. No
# minimum coverage is specified in Horvath 2013 or, as far as we found, anywhere
# else; the numbers come from the curve above, so they inherit its limits.
BANDS = [
    (0.95, "ok", "Coverage loses almost no between-person signal."),
    (0.80, "caution", "Some signal lost. Report coverage alongside any age you quote."),
    (0.50, "degraded", "Much of the spread between people is gone. Do not compare individuals."),
    (0.00, "unusable", "Predictions are driven by the filler values, not by this sample."),
]


def verdict(coverage: float, present: int) -> tuple[str, str]:
    if present == 0:
        return "refuse", ("No required site is present. biolearn still returns a number here; "
                          "pyaging raises an error. Neither number means anything.")
    r = retained_signal(coverage)
    for floor, name, note in BANDS:
        if r >= floor:
            return name, note
    return "unusable", BANDS[-1][2]
