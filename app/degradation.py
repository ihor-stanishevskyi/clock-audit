"""What a clock loses when CpGs are missing - spread between people, and years.

MEASURED, on real cohorts. Two runs on 2026-11-26, biolearn 0.9.1, Colab CPU:

  GSE40279  656 people, whole blood, ages 19-101
  GSE50660  464 people, whole blood, ages 38-67

Nineteen published age clocks, seven scenarios each: random dropout at six
levels, plus one real platform mask (only the probes an Illumina 27k array
carries). Project doc 43 has the per-clock table and the limits.

TWO NUMBERS, NOT ONE. A clock that keeps its spread is not thereby unbiased:
across both cohorts the rank correlation between retained spread and absolute
shift ran -0.14 to -0.45 and was never significant (p 0.085-0.629). They are
separate failures, so this module reports both.

NO PER-CLOCK PREDICTION. The obvious next step - say which clocks hold up
better - does not survive replication. Between the two cohorts the rank
correlation of retained spread across clocks ran -0.39 to +0.43 and was never
significant at any coverage level; at 70% it was negative. So a per-clock
robustness ranking would be noise dressed as advice. What this module gives is
a POPULATION expectation: what the median published clock did, and the range
the nineteen spanned. Per-clock COVERAGE is a different matter and is reliable
- it comes from the array manifest, not from this experiment.

That refusal now has a number behind it (project doc 44). The whole curve is one
power law, retained = coverage ** 0.73, which describes all 17 non-degenerate
clocks in both cohorts. Fit that exponent PER CLOCK on one cohort and predict the
other, and it loses to the single pooled value: the per-clock fit won 35 of 102
cells one way and 34 of 102 the other. A per-clock parameter overfits its own
cohort and costs accuracy on the next one. So this is a measured result, not
caution.
"""
from bisect import bisect_left

# coverage -> (median retained spread in GSE40279, in GSE50660)
# 17 clocks: degenerate ones (1-8 sites) excluded, AND the two clocks handed
# chronological age and sex as model inputs. Corrected 2026-11-26: this table
# used to include GrimAge V1/V2, which keep 0.79-0.83 of their spread at 5%
# coverage because they are given the answer, not because they survive the loss.
# That inflated every row by 0.001-0.029 - always in the optimistic direction,
# which is the wrong direction for a tool whose job is to warn. SHIFT_YEARS had
# always excluded them, so the two tables described different clock sets; the
# inconsistency surfaced when the power-law fit of doc 44 disagreed with the
# table it was fitted to.
RETAINED = [
    (0.00, (0.000, 0.000)),
    (0.05, (0.099, 0.149)),
    (0.15, (0.231, 0.295)),
    (0.30, (0.349, 0.470)),
    (0.50, (0.519, 0.607)),
    (0.70, (0.723, 0.770)),
    (0.90, (0.901, 0.922)),
    (1.00, (1.000, 1.000)),
]

# coverage -> (median ABSOLUTE shift in years, per cohort)
# 16 clocks: in_years, and not handed chronological age as an input. Clocks
# that return a rate (DunedinPACE, DunedinPoAm38) are excluded - for them a
# "shift in years" is meaningless, and the raw field is populated anyway.
SHIFT_YEARS = [
    (0.00, (24.0, 17.0)),   # floor: no measurement below 5%, held at the 5% value
    (0.05, (21.66, 15.38)),
    (0.15, (18.31, 13.57)),
    (0.30, (15.88, 9.93)),
    (0.50, (12.02, 8.87)),
    (0.70, (7.53, 4.48)),
    (0.90, (2.69, 2.21)),
    (1.00, (0.00, 0.00)),
]

SOURCE = ("19 published clocks on GSE40279 (656 people) and GSE50660 (464), "
          "biolearn 0.9.1, 2026-11-26; shift from the 16 that return years and "
          "are not given age as an input")

# For comparison, and the reason the shift number matters: the biological
# effects these clocks are used to detect are the same size. Measured on our
# own data: smoking +2.70 years on PhenoAge (GSE50660), ovarian cancer +2.28
# (GSE19711). Losing a tenth of the probes moves the median clock 2.7 years.
EFFECT_SIZE_REFERENCE = 2.7

# The same measurement as RETAINED, written as one power law (project doc 44,
# fitted through (1,1) because retained is 1 at full coverage by definition).
# It is NOT used to answer queries - the table is the measurement and is more
# accurate. It is kept here so that the two descriptions of one experiment have
# to keep agreeing: test_law_agrees_with_the_measured_table pins them together,
# and it is what caught GrimAge inflating the table above.
LAW_EXPONENT = 0.728
LAW_MEDIAN_TOLERANCE = 0.10


def _interp(table: list, coverage: float) -> tuple[float, float]:
    if coverage <= 0:
        return table[0][1]
    if coverage >= 1:
        return table[-1][1]
    xs = [c for c, _ in table]
    i = bisect_left(xs, coverage)
    x0, y0 = table[i - 1]
    x1, y1 = table[i]
    f = (coverage - x0) / (x1 - x0)
    return tuple(a + (b - a) * f for a, b in zip(y0, y1))


def retained_signal(coverage: float) -> float:
    """Fraction of between-person spread the median clock kept. The WORSE of
    the two cohorts, because a tool that warns should not round in its own
    favour. retained_range() gives both."""
    return min(_interp(RETAINED, coverage))


def retained_range(coverage: float) -> tuple[float, float]:
    """(worse cohort, better cohort). The gap between them is real: the same
    coverage cost more in the cohort with the wider age range."""
    lo, hi = sorted(_interp(RETAINED, coverage))
    return lo, hi


def shift_years(coverage: float) -> float:
    """Expected absolute shift of the median clock, in years. The LARGER of the
    two cohorts, same reason as above."""
    return max(_interp(SHIFT_YEARS, coverage))


def shift_range(coverage: float) -> tuple[float, float]:
    lo, hi = sorted(_interp(SHIFT_YEARS, coverage))
    return lo, hi


# Bands are THIS TOOL'S rule of thumb, not a published standard. No minimum
# coverage is specified anywhere we found. They now sit on measured numbers
# rather than on one interpolated clock, but where to put the lines is still
# a judgement call.
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
            if name != "ok":
                note = f"{note} Expect the answer to sit about {shift_years(coverage):.1f} years off."
            return name, note
    return "unusable", BANDS[-1][2]
