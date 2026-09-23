"""Robust amount baselines: median, MAD, robust deviation and empirical percentile.

The plan asks for median/MAD rather than mean/standard deviation, which one
outlier can distort. GSQL has no median, so ``get_card_baseline_v1`` returns
the raw amounts to the anchor and the statistics are computed here, where a
zero MAD can be handled explicitly instead of producing a division by zero or
an infinite score.

A zero MAD is common rather than exotic: a card that always spends the same
amount, or has only one or two transactions, has MAD 0. Its deviation score is
then undefined, and :class:`RobustAmountStats` says so with
``deviation_state="zero_mad"`` instead of inventing a number. Whether the
amount matches the constant history is reported separately, as a boolean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Scales MAD to the standard deviation of a normal distribution.
MAD_SCALE = 0.6745


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of an empty list")
    middle = n // 2
    return ordered[middle] if n % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def mad(values: list[float]) -> float:
    """Median absolute deviation from the median."""
    centre = median(values)
    return median([abs(value - centre) for value in values])


def empirical_percentile(history: list[float], value: float) -> float:
    """Mid-rank percentile of ``value`` in ``history``, in [0, 1].

    Ties count half, so an amount equal to every historical amount sits at 0.5
    rather than at 0 or 1.
    """
    if not history:
        raise ValueError("percentile against an empty history")
    below = sum(1 for item in history if item < value)
    equal = sum(1 for item in history if item == value)
    return (below + 0.5 * equal) / len(history)


@dataclass(frozen=True)
class RobustAmountStats:
    history_count: int
    amount: float
    median: float | None
    mad: float | None
    #: 0.6745 * (amount - median) / MAD. None when it is undefined.
    robust_deviation: float | None
    #: "defined", "zero_mad" or "no_history".
    deviation_state: str
    #: For a zero MAD: whether the amount equals the constant history median.
    amount_equals_constant_history: bool | None
    empirical_percentile: float | None


def amount_stats(history: list[float], amount: float) -> RobustAmountStats:
    """Robust statistics of ``amount`` against the card's prior amounts."""
    history = [abs(float(item)) for item in history if math.isfinite(float(item))]
    amount = abs(float(amount))
    if not history:
        return RobustAmountStats(0, amount, None, None, None, "no_history", None, None)
    centre = median(history)
    spread = mad(history)
    percentile = empirical_percentile(history, amount)
    if spread == 0.0:
        return RobustAmountStats(
            len(history),
            amount,
            centre,
            0.0,
            None,
            "zero_mad",
            math.isclose(amount, centre, abs_tol=0.005),
            percentile,
        )
    deviation = MAD_SCALE * (amount - centre) / spread
    return RobustAmountStats(
        len(history), amount, centre, spread, deviation, "defined", None, percentile
    )


def history_without_flagged(amounts: list[float], flagged_amount: float) -> list[float]:
    """Remove ONE occurrence of the flagged amount from the to-anchor amounts.

    The baseline query counts every transaction at or before the anchor, which
    includes the flagged transaction itself. Comparing a transaction with a
    history that contains it pulls the percentile towards the middle.
    """
    remaining = list(amounts)
    for index, value in enumerate(remaining):
        if math.isclose(abs(float(value)), abs(float(flagged_amount)), abs_tol=0.005):
            del remaining[index]
            break
    return remaining
