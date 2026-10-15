"""Fixed-income maths: cash flows, price from yield, YTM, duration, convexity.

Simplified conventions suitable for portfolio analytics (not trade
settlement): coupons on dates stepped back from maturity, actual/365 time,
yields compounded at the coupon frequency, prices as % of face value."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta


@dataclass
class BondTerms:
    coupon: float  # annual rate (0.0735 = 7.35%)
    maturity: date
    freq: int = 1  # coupons per year; 0 or coupon 0 => zero-coupon


def cashflows(b: BondTerms, settle: date) -> list[tuple[date, float]]:
    """Future cash flows per 100 face."""
    if b.maturity <= settle:
        return []
    freq = b.freq or 1
    if b.coupon <= 0:
        return [(b.maturity, 100.0)]
    step = relativedelta(months=12 // freq)
    cpn = 100.0 * b.coupon / freq
    dates = []
    d = b.maturity
    while d > settle:
        dates.append(d)
        d = d - step
    dates.reverse()
    flows = [(d, cpn) for d in dates]
    flows[-1] = (flows[-1][0], flows[-1][1] + 100.0)
    return flows


def _prev_coupon(b: BondTerms, settle: date) -> Optional[date]:
    if b.coupon <= 0:
        return None
    step = relativedelta(months=12 // (b.freq or 1))
    d = b.maturity
    while d > settle:
        d = d - step
    return d


def accrued(b: BondTerms, settle: date) -> float:
    prev = _prev_coupon(b, settle)
    if prev is None:
        return 0.0
    nxt = prev + relativedelta(months=12 // (b.freq or 1))
    period = (nxt - prev).days or 1
    return 100.0 * b.coupon / (b.freq or 1) * (settle - prev).days / period


def dirty_price(b: BondTerms, y: float, settle: date) -> float:
    freq = b.freq if (b.freq and b.coupon > 0) else 1
    total = 0.0
    for d, cf in cashflows(b, settle):
        t = (d - settle).days / 365.0
        total += cf / (1 + y / freq) ** (t * freq)
    return total


def clean_price(b: BondTerms, y: float, settle: date) -> float:
    return dirty_price(b, y, settle) - accrued(b, settle)


def ytm(b: BondTerms, clean: float, settle: date) -> Optional[float]:
    """Yield from clean price (% of face). Bisection; None if not bracketed."""
    if not cashflows(b, settle):
        return None
    target = clean + accrued(b, settle)
    lo, hi = -0.05, 0.60
    f_lo = dirty_price(b, lo, settle) - target
    f_hi = dirty_price(b, hi, settle) - target
    if f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = dirty_price(b, mid, settle) - target
        if abs(f_mid) < 1e-9:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def risk(b: BondTerms, y: float, settle: date) -> tuple[float, float]:
    """(modified duration in years, convexity) by finite differences."""
    h = 0.0001
    p0 = dirty_price(b, y, settle)
    if p0 <= 0:
        return 0.0, 0.0
    pu = dirty_price(b, y + h, settle)
    pd = dirty_price(b, y - h, settle)
    dur = (pd - pu) / (2 * p0 * h)
    conv = (pu + pd - 2 * p0) / (p0 * h * h)
    return dur, conv


def price_change_pct(mod_dur: float, convexity: float, dy: float) -> float:
    """Approximate % price change for a yield change dy (0.0025 = +25 bps)."""
    return -mod_dur * dy + 0.5 * convexity * dy * dy


# ---------------------------------------------------------------- yield curve

def interp_curve(curve: list[tuple[float, float]], tenor: float) -> float:
    """Linear interpolation on [(tenor_years, yield)], flat beyond the ends."""
    pts = sorted(curve)
    if tenor <= pts[0][0]:
        return pts[0][1]
    if tenor >= pts[-1][0]:
        return pts[-1][1]
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        if t0 <= tenor <= t1:
            return y0 + (y1 - y0) * (tenor - t0) / (t1 - t0)
    return pts[-1][1]


# Indicative credit spreads over the G-sec curve by rating bucket, used only
# when a bond has no recent traded price. Editable later in settings.
RATING_SPREADS = {
    "Sovereign": 0.0,
    "AAA": 0.0065,
    "AA": 0.0125,
    "A": 0.0250,
    "BBB": 0.0400,
    "Below BBB": 0.0700,
    "Unrated / unknown": 0.0350,
}
