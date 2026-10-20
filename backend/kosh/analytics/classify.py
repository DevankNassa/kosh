"""Classify instruments into kind / asset class / tax class, and pull bond
terms out of exchange security names."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

_DEBT_WORDS = (
    "gilt", "g-sec", "gsec", "sdl", "bond", "debt", "liquid", "overnight",
    "money market", "crisil ibx", "target mat", "psu", "treasury", "t-bill",
    "corporate", "income", "floater", "duration", "1d rate", "constant maturity",
)


@dataclass
class MFClass:
    kind: str
    asset_class: str
    sub_class: str
    tax_class: str
    mod_duration: Optional[float] = None


# Category-level modified duration estimates (years) for debt funds. AMFI does
# not publish fund durations in the NAV file; these are typical values for the
# SEBI category and are labelled as estimates in the UI.
_DEBT_DURATIONS = [
    ("overnight", 0.003),
    ("liquid", 0.1),
    ("money market", 0.4),
    ("ultra short", 0.4),
    ("low duration", 0.8),
    ("floating", 1.0),
    ("floater", 1.0),
    ("short", 2.5),
    ("banking and psu", 2.8),
    ("corporate bond", 2.8),
    ("credit risk", 2.2),
    ("medium to long", 5.0),
    ("medium", 3.5),
    ("long", 9.0),
    ("10-year constant", 6.8),
    ("gilt", 7.0),
    ("dynamic", 5.0),
    ("fixed term", 1.5),
]


def _debt_duration(text: str) -> float:
    t = text.lower()
    for key, dur in _DEBT_DURATIONS:
        if key in t:
            return dur
    return 4.0


def _has_any(text: str, words) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def classify_mf(category_header: str, scheme_name: str) -> MFClass:
    """Classify a scheme from its AMFI section header, e.g.
    'Open Ended Schemes(Debt Scheme - Liquid Fund)', plus its name."""
    head = category_header or ""
    m = re.search(r"\((.*)\)\s*$", head)
    inner = m.group(1).strip() if m else head.strip()
    parts = [p.strip() for p in inner.split(" - ", 1)]
    group = parts[0].lower()
    cat = parts[1] if len(parts) > 1 else parts[0]
    name = scheme_name or ""
    lname = name.lower()
    both = f"{inner} {name}".lower()
    is_etf = "etf" in group or " etf" in lname or "etf" in cat.lower()
    kind = "etf" if is_etf else "mf"

    def gold_or_silver():
        sub = "Silver" if "silver" in both else "Gold"
        return MFClass(kind, "gold", sub, "listed_other" if is_etf else "other_mf")

    if "gold" in cat.lower() or "silver" in cat.lower():
        return gold_or_silver()
    if "overseas" in both or "international" in lname or "global" in lname or "nasdaq" in lname or "us equity" in lname:
        return MFClass(kind, "equity", "International", "listed_other" if is_etf else "other_mf")
    if "equity" in group or "elss" in group or group == "growth":
        return MFClass(kind, "equity", cat, "equity")
    if "debt" in group or "income" in group or group == "gilt":
        return MFClass(kind, "debt", cat, "specified_debt", _debt_duration(f"{cat} {name}"))
    if "hybrid" in group:
        c = cat.lower()
        if "conservative" in c:
            return MFClass(kind, "hybrid", cat, "specified_debt", 2.0)
        if "arbitrage" in c:
            return MFClass(kind, "hybrid", cat, "equity", 0.3)
        if "equity savings" in c or "aggressive" in c or "balanced advantage" in c or "dynamic" in c:
            return MFClass(kind, "hybrid", cat, "equity", 1.0)
        return MFClass(kind, "hybrid", cat, "other_mf", 1.5)
    if "index" in group or "etf" in group or "other scheme" in group:
        if _has_any(name, ("gold",)) or _has_any(name, ("silver",)):
            return gold_or_silver()
        if _has_any(f"{cat} {name}", _DEBT_WORDS) and "equity" not in cat.lower():
            return MFClass(kind, "debt", f"Debt {('ETF' if is_etf else 'Index Fund')}",
                           "specified_debt", _debt_duration(name))
        if "fof" in cat.lower() or "fund of funds" in group:
            return MFClass(kind, "hybrid", cat, "other_mf", 1.5)
        return MFClass(kind, "equity", "Index / ETF" if not is_etf else "Equity ETF", "equity")
    if "fund of funds" in group:
        if _has_any(name, ("gold", "silver")):
            return gold_or_silver()
        return MFClass(kind, "hybrid", "Fund of Funds", "other_mf", 1.5)
    if "solution" in group or "children" in group or "life cycle" in group:
        return MFClass(kind, "hybrid", cat, "other_mf", 2.0)
    return MFClass(kind, "other", cat, "other_mf")


# ---------------------------------------------------------------- exchange rows

_EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST", "E1"}


def classify_exchange(isin: str, series: str, name: str, symbol: str = "") -> dict:
    """Classify an NSE bhavcopy row. Returns instrument fields."""
    s = (series or "").upper()
    if isin.startswith("INF"):
        # exchange-traded fund units; AMFI master refines this when available
        n = name.lower()
        if "gold" in n:
            return dict(kind="etf", asset_class="gold", sub_class="Gold", tax_class="listed_other")
        if "silver" in n:
            return dict(kind="etf", asset_class="gold", sub_class="Silver", tax_class="listed_other")
        if _has_any(n, ("liquid", "gilt", "sdl", "bond", "gsec", "g-sec", "bharat bond", "bbetf")):
            return dict(kind="etf", asset_class="debt", sub_class="Debt ETF",
                        tax_class="specified_debt", mod_duration=_debt_duration(n))
        return dict(kind="etf", asset_class="equity", sub_class="Equity ETF", tax_class="equity")
    if s in ("RR", "IV"):
        return dict(kind="reit_invit", asset_class="other", sub_class="REIT" if s == "RR" else "InvIT",
                    tax_class="equity")
    if s == "GB":
        return dict(kind="sgb", asset_class="gold", sub_class="Sovereign Gold Bond", tax_class="listed_other",
                    **bond_terms_from_name(name, default_freq=2, face=None))
    if s == "GS":
        return dict(kind="gsec", asset_class="debt", sub_class="G-Sec", tax_class="listed_other",
                    rating="SOV", face_value=100.0, **bond_terms_from_name(name, default_freq=2))
    if s == "SG":
        return dict(kind="sdl", asset_class="debt", sub_class="State Development Loan", tax_class="listed_other",
                    rating="SOV", face_value=100.0, **bond_terms_from_name(name, default_freq=2))
    if s == "TB":
        terms = tbill_terms_from_name(name)
        return dict(kind="tbill", asset_class="debt", sub_class="T-Bill", tax_class="listed_other",
                    rating="SOV", face_value=100.0, coupon=0.0, coupon_freq=1, **terms)
    if s in _EQUITY_SERIES:
        return dict(kind="equity", asset_class="equity", sub_class="Listed equity", tax_class="equity")
    if len(s) == 2 and s[0] in "NY":
        terms = bond_terms_from_name(name, default_freq=1)
        if "maturity" not in terms:
            mat = maturity_from_symbol(symbol)
            if mat:
                terms.update(maturity=mat, maturity_is_estimate=True)
        return dict(kind="corp_bond", asset_class="debt", sub_class="Corporate bond", tax_class="listed_other",
                    tax_free_interest=bool(re.search(r"tax\s*free|\bTF\b", name, re.I)), **terms)
    return dict(kind="other", asset_class="other", sub_class=None, tax_class="listed_other")


_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def bond_terms_from_name(name: str, default_freq: int = 1, face: Optional[float] = None) -> dict:
    """'GOI LOAN 6.79% 2031' / '7.34 NCD 19FEB28 TR1' → coupon, maturity.
    A maturity built from a year alone is flagged as an estimate."""
    out: dict = {"coupon_freq": default_freq}
    if face is not None:
        out["face_value"] = face
    m = re.search(r"(\d{1,2}(?:\.\d{1,3})?)\s*%", name) or re.search(r"^\s*(\d{1,2}\.\d{1,3})\b", name)
    if m:
        out["coupon"] = round(float(m.group(1)) / 100.0, 6)
    d = re.search(r"(?<!\d)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2,4})\b", name.upper())
    if d:
        y = int(d.group(3))
        y = y + 2000 if y < 100 else y
        try:
            out["maturity"] = date(y, _MONTHS[d.group(2)], int(d.group(1)))
            out["maturity_is_estimate"] = False
            return out
        except ValueError:
            pass
    y = re.search(r"(?<!\d)(20[2-9]\d)(?!\d)", name)
    if y:
        out["maturity"] = date(int(y.group(1)), 6, 30)
        out["maturity_is_estimate"] = True
    return out


def maturity_from_symbol(symbol: str) -> Optional[date]:
    """NSE bond symbols end in the maturity year: '875NHAI29', '930IIFL27'."""
    m = re.search(r"[A-Z](\d{2})[A-Z]?$", symbol or "")
    if not m:
        return None
    return date(2000 + int(m.group(1)), 6, 30)


def tbill_terms_from_name(name: str) -> dict:
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", name)
    if not m:
        return {}
    return {"maturity": date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))),
            "maturity_is_estimate": False}


def maturity_bucket(maturity: Optional[date], today: date) -> str:
    if maturity is None:
        return "Unknown"
    yrs = (maturity - today).days / 365.25
    if yrs <= 1:
        return "< 1 yr"
    if yrs <= 3:
        return "1–3 yrs"
    if yrs <= 5:
        return "3–5 yrs"
    if yrs <= 10:
        return "5–10 yrs"
    return "10+ yrs"


def rating_bucket(rating: Optional[str]) -> str:
    if not rating:
        return "Unrated / unknown"
    r = rating.upper().replace("CRISIL", "").replace("ICRA", "").replace("CARE", "").replace("IND", "").strip(" ()")
    if r in ("SOV", "SOVEREIGN"):
        return "Sovereign"
    if r.startswith("AAA"):
        return "AAA"
    if r.startswith("AA"):
        return "AA"
    if r.startswith("A"):
        return "A"
    if r.startswith("BBB"):
        return "BBB"
    return "Below BBB"


# Instrument.sector (from the NSE Nifty 500 industry classification) → the
# NSE sectoral index that tracks it, for real-data scenarios and charting.
# Sectors not listed here have no dedicated index; they're only compared
# against the broad-market baseline.
SECTOR_INDEX = {
    "Oil Gas & Consumable Fuels": "Nifty Oil & Gas",
    "Information Technology": "Nifty IT",
    "Financial Services": "Nifty Financial Services",
    "Automobile and Auto Components": "Nifty Auto",
    "Metals & Mining": "Nifty Metal",
    "Healthcare": "Nifty Healthcare Index",
    "Fast Moving Consumer Goods": "Nifty FMCG",
    "Realty": "Nifty Realty",
    "Power": "Nifty Power",
    "Consumer Durables": "Nifty Consumer Durables",
    "Chemicals": "Nifty Chemicals",
    "Telecommunication": "Nifty Telecommunications",
    "Media Entertainment & Publication": "Nifty Media",
    "Construction": "Nifty Construction",
}

BROAD_MARKET_INDEX = "Nifty 500"
DEBT_INDEX = "Nifty 10 yr Benchmark G-Sec"


def equity_share(asset_class: str, sub_class: Optional[str]) -> float:
    """Approximate unhedged equity exposure, used for market-move scenarios."""
    if asset_class == "equity":
        return 1.0
    if asset_class != "hybrid":
        return 0.0
    s = (sub_class or "").lower()
    for key, share in (("arbitrage", 0.0), ("conservative", 0.2), ("equity savings", 0.35),
                       ("aggressive", 0.75), ("balanced advantage", 0.55), ("dynamic", 0.55),
                       ("multi asset", 0.5), ("balanced hybrid", 0.5)):
        if key in s:
            return share
    return 0.5
