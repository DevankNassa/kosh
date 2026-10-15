"""Government bond yield curve.

The official G-sec valuation curve is published by FBIL. Until that feed is
integrated, Kosh derives an indicative curve from G-secs traded on NSE that
day (prices and coupons are in the bhavcopy), and falls back to a configured
curve when there are too few trades."""

from datetime import date

from ..analytics.bonds import BondTerms, interp_curve, ytm
from ..analytics.classify import bond_terms_from_name
from .nse import BhavRow

TENORS = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40]

# Fallback curve (tenor years, yield). Replace via settings when stale.
DEFAULT_CURVE = [(0.25, 0.0560), (1, 0.0575), (2, 0.0600), (3, 0.0615), (5, 0.0635),
                 (7, 0.0650), (10, 0.0665), (15, 0.0690), (20, 0.0705), (30, 0.0715), (40, 0.0720)]

_WINDOWS = {0.25: (0, 0.4), 0.5: (0.3, 0.75), 1: (0.6, 1.5), 2: (1.5, 2.5), 3: (2.5, 4),
            5: (4, 6), 7: (6, 8.5), 10: (8.5, 12), 15: (12, 17.5), 20: (17.5, 25),
            30: (25, 35), 40: (35, 60)}


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """pairs of (value, weight)."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def derive_curve(rows: list[BhavRow], asof: date) -> tuple[list[tuple[float, float]], int]:
    """Returns (curve points, number of securities used).

    Exchange names give only the maturity year, and short-dated retail trades
    are thin, so only G-secs with 4+ years left and meaningful volume are used.
    The short end keeps the shape of the default curve, shifted to meet the
    derived 5-year point."""
    pts: list[tuple[float, float, float]] = []
    for r in rows:
        if r.series != "GS" or r.volume < 100:
            continue
        t = bond_terms_from_name(r.name, default_freq=2)
        if "coupon" not in t or "maturity" not in t:
            continue
        tenor = (t["maturity"] - asof).days / 365.25
        if tenor < 4:
            continue
        y = ytm(BondTerms(t["coupon"], t["maturity"], 2), r.close, asof)
        if y is None or not (0.03 < y < 0.12):
            continue
        pts.append((tenor, y, r.volume))
    long_end = []
    for ten in TENORS:
        lo, hi = _WINDOWS[ten]
        if ten < 5:
            continue
        sel = [(y, v) for t, y, v in pts if lo <= t < hi]
        if sel:
            long_end.append((float(ten), _weighted_median(sel)))
    if len(long_end) < 3:
        return DEFAULT_CURVE, 0
    anchor_t, anchor_y = long_end[0]
    shift = anchor_y - interp_curve(DEFAULT_CURVE, anchor_t)
    short_end = [(t, y + shift) for t, y in DEFAULT_CURVE if t < anchor_t]
    return short_end + long_end, len(pts)
