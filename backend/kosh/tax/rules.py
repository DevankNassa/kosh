"""Capital gains rules for resident individuals, versioned by transfer date.

Working model for the product, not tax advice. Must be verified by a CA
against the current Finance Act and the Income-tax Act, 2025 before use with
real clients (see docs/SPEC.md §7)."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta

# Gain buckets
STCG_111A = "STCG_111A"    # equity, short term, special rate
LTCG_112A = "LTCG_112A"    # equity, long term, special rate above exemption
STCG_SLAB = "STCG_SLAB"    # other short-term gains, at slab
LTCG_112 = "LTCG_112"      # other long-term gains, flat rate, no indexation
SLAB_50AA = "SLAB_50AA"    # specified debt MFs (post 1-Apr-2023) / unlisted bonds: always short-term at slab

SHORT_BUCKETS = (STCG_111A, STCG_SLAB, SLAB_50AA)
LONG_BUCKETS = (LTCG_112A, LTCG_112)

BUCKET_LABELS = {
    STCG_111A: "Short-term (equity, s.111A)",
    LTCG_112A: "Long-term (equity, s.112A)",
    STCG_SLAB: "Short-term (at slab)",
    LTCG_112: "Long-term (other, s.112)",
    SLAB_50AA: "Debt fund / unlisted bond gains (at slab, s.50AA)",
}


@dataclass(frozen=True)
class RuleSet:
    name: str
    effective_from: date
    effective_to: Optional[date]
    equity_stcg_rate: float
    equity_ltcg_rate: float
    equity_ltcg_exemption: float
    other_ltcg_rate: float
    equity_lt_months: int = 12
    listed_lt_months: int = 12
    other_lt_months: int = 24
    specified_debt_from: date = date(2023, 4, 1)
    cess: float = 0.04
    special_surcharge_cap: float = 0.15
    note: str = ""


RULESETS = [
    RuleSet(
        name="Transfers before 23 Jul 2024",
        effective_from=date(2018, 4, 1),
        effective_to=date(2024, 7, 22),
        equity_stcg_rate=0.15,
        equity_ltcg_rate=0.10,
        equity_ltcg_exemption=100_000,
        other_ltcg_rate=0.20,
        other_lt_months=36,
        note="Non-equity long-term gains were taxed at 20% with indexation; "
             "Kosh does not compute indexation, so these figures are approximate.",
    ),
    RuleSet(
        name="Transfers on or after 23 Jul 2024",
        effective_from=date(2024, 7, 23),
        effective_to=None,
        equity_stcg_rate=0.20,
        equity_ltcg_rate=0.125,
        equity_ltcg_exemption=125_000,
        other_ltcg_rate=0.125,
    ),
]


def ruleset_for(d: date) -> RuleSet:
    for rs in RULESETS:
        if rs.effective_from <= d and (rs.effective_to is None or d <= rs.effective_to):
            return rs
    return RULESETS[0] if d < RULESETS[0].effective_from else RULESETS[-1]


def fy_of(d: date) -> str:
    """Financial year label, e.g. 2026-10-15 → 'FY 2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY {start}-{str(start + 1)[2:]}"


def fy_bounds(d: date) -> tuple[date, date]:
    start = d.year if d.month >= 4 else d.year - 1
    return date(start, 4, 1), date(start + 1, 3, 31)


def lt_months(tax_class: str, rs: RuleSet) -> Optional[int]:
    """Holding period (months) beyond which a gain is long-term; None if
    gains are always short-term for this class."""
    if tax_class == "equity":
        return rs.equity_lt_months
    if tax_class == "listed_other":
        return rs.listed_lt_months
    if tax_class in ("other_mf", "unlisted_other", "specified_debt"):
        return rs.other_lt_months
    return None  # unlisted_bond


def always_short(tax_class: str, acquired: date, rs: RuleSet) -> bool:
    if tax_class == "unlisted_bond":
        return True
    return tax_class == "specified_debt" and acquired >= rs.specified_debt_from


def long_term_from(tax_class: str, acquired: date, on: date) -> Optional[date]:
    """First sale date on which the lot is long-term (held *more than* N
    months), or None if it can never be long-term."""
    rs = ruleset_for(on)
    if always_short(tax_class, acquired, rs):
        return None
    months = lt_months(tax_class, rs)
    if months is None:
        return None
    return acquired + relativedelta(months=months) + relativedelta(days=1)


def is_long_term(tax_class: str, acquired: date, sold: date) -> bool:
    lt = long_term_from(tax_class, acquired, sold)
    return lt is not None and sold >= lt


def bucket_for(tax_class: str, acquired: date, sold: date) -> str:
    rs = ruleset_for(sold)
    if always_short(tax_class, acquired, rs):
        return SLAB_50AA
    lt = is_long_term(tax_class, acquired, sold)
    if tax_class == "equity":
        return LTCG_112A if lt else STCG_111A
    return LTCG_112 if lt else STCG_SLAB


def bucket_rate(bucket: str, slab_rate: float, rs: RuleSet) -> float:
    return {
        STCG_111A: rs.equity_stcg_rate,
        LTCG_112A: rs.equity_ltcg_rate,
        LTCG_112: rs.other_ltcg_rate,
        STCG_SLAB: slab_rate,
        SLAB_50AA: slab_rate,
    }[bucket]


# Transaction cost / exit load estimates (shown as estimates in the UI)
STT_EQUITY_DELIVERY_SELL = 0.001     # shares / equity ETFs, delivery sale
STT_EQUITY_MF_REDEMPTION = 0.00001   # equity-oriented MF redemption


def exit_load_rate(kind: str, tax_class: str, asset_class: str, days_held: int) -> float:
    """Typical exit loads; actual loads are in each scheme's documents."""
    if kind != "mf":
        return 0.0
    if tax_class == "equity" and asset_class in ("equity", "hybrid"):
        if asset_class == "hybrid" and days_held < 30:
            return 0.0025  # arbitrage-style short loads
        return 0.01 if days_held < 365 else 0.0
    if asset_class in ("hybrid", "gold") and days_held < 365:
        return 0.01
    return 0.0


def stt_rate(kind: str, tax_class: str) -> float:
    if kind in ("equity", "etf", "reit_invit") and tax_class == "equity":
        return STT_EQUITY_DELIVERY_SELL
    if kind == "mf" and tax_class == "equity":
        return STT_EQUITY_MF_REDEMPTION
    return 0.0
