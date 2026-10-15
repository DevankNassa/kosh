"""Exposure mapping and scenario impact.

A *shock* describes what moved and what it touches:

    {
      "yield_shift_bps": 25,            # parallel G-sec yield move (all debt)
      "spread_bps": 75,                 # credit spread widening (corporate bonds)
      "rating_buckets": ["AA", "A"],    # optional: only bonds in these buckets
      "equity_move_pct": -3,            # equity price move
      "gold_move_pct": 5,
      "default_recovery_pct": 40,       # write bonds down to this % of value
      "filter": {"isins": [...], "issuer_keys": ["INE053F"], "sector": "Financial Services"}
    }

With no filter the shock is market-wide. Events store a shock in their tags."""

from collections import defaultdict
from typing import Optional

from ..analytics.bonds import price_change_pct
from ..analytics.classify import equity_share, rating_bucket
from ..analytics.portfolio import BOND_KINDS, Holding, Portfolio


def _matches(h: Holding, flt: Optional[dict]) -> bool:
    if not flt:
        return True
    ins = h.instrument
    if flt.get("isins") and ins.isin in flt["isins"]:
        return True
    if flt.get("issuer_keys") and ins.isin[:7] in flt["issuer_keys"]:
        return True
    if flt.get("sector") and ins.sector and ins.sector.lower() == flt["sector"].lower():
        return True
    if flt.get("asset_classes") and ins.asset_class in flt["asset_classes"]:
        return True
    return False


def holding_impact(h: Holding, shock: dict) -> tuple[float, list[str]]:
    """Estimated ₹ change for one holding, with a short explanation."""
    ins = h.instrument
    v = h.value
    if not v:
        return 0.0, []
    flt = shock.get("filter")
    matched = _matches(h, flt)
    impact, why = 0.0, []

    dy = (shock.get("yield_shift_bps") or 0) / 10_000
    if dy and h.mod_duration is not None and h.debt_share > 0 and (not flt or matched):
        conv = h.convexity if ins.kind in BOND_KINDS else 0.0
        d = v * h.debt_share * price_change_pct(h.mod_duration, conv, dy)
        impact += d
        why.append(f"rates {shock['yield_shift_bps']:+g} bps × duration {h.mod_duration:.1f}")

    ds = (shock.get("spread_bps") or 0) / 10_000
    if ds and ins.kind == "corp_bond" and h.mod_duration is not None and matched:
        buckets = shock.get("rating_buckets")
        if not buckets or rating_bucket(ins.rating) in buckets:
            d = v * price_change_pct(h.mod_duration, h.convexity, ds)
            impact += d
            why.append(f"credit spread {shock['spread_bps']:+g} bps")

    rec = shock.get("default_recovery_pct")
    if rec is not None and ins.kind == "corp_bond" and matched:
        impact += -v * (1 - rec / 100)
        why.append(f"default, {rec:g}% recovery")

    eq = (shock.get("equity_move_pct") or 0) / 100
    if eq and matched:
        share = equity_share(ins.asset_class, ins.sub_class)
        if share:
            impact += v * share * eq
            why.append(f"equity {shock['equity_move_pct']:+g}%" + (f" × {share:.0%} equity" if share < 1 else ""))

    g = (shock.get("gold_move_pct") or 0) / 100
    if g and ins.asset_class == "gold" and (not flt or matched):
        impact += v * g
        why.append(f"gold {shock['gold_move_pct']:+g}%")
    return impact, why


def exposed(h: Holding, shock: dict) -> bool:
    """Does the shock touch this holding at all (even if not quantified)?"""
    flt = shock.get("filter")
    if flt:
        return _matches(h, flt)
    impact, _ = holding_impact(h, shock)
    return abs(impact) > 0.005


def portfolio_impact(p: Portfolio, shock: dict) -> dict:
    rows = []
    total = 0.0
    exposure = 0.0
    for h in p.holdings:
        if not exposed(h, shock):
            continue
        imp, why = holding_impact(h, shock)
        total += imp
        exposure += h.value
        rows.append({
            "isin": h.instrument.isin, "name": h.instrument.name, "kind": h.instrument.kind,
            "asset_class": h.instrument.asset_class, "value": round(h.value, 2),
            "impact": round(imp, 2), "impact_pct": imp / h.value if h.value else None,
            "explain": "; ".join(why) if why else "Exposed (impact not modelled)",
        })
    rows.sort(key=lambda r: r["impact"])
    return {
        "client_id": p.client.id, "client_name": p.client.name,
        "portfolio_value": round(p.value, 2), "exposure": round(exposure, 2),
        "impact": round(total, 2), "impact_pct": total / p.value if p.value else None,
        "holdings": rows,
    }


def book_impact(portfolios: list[Portfolio], shock: dict) -> dict:
    clients = [portfolio_impact(p, shock) for p in portfolios]
    clients = [c for c in clients if c["holdings"]]
    clients.sort(key=lambda c: c["impact"])
    by_class: dict[str, float] = defaultdict(float)
    for c in clients:
        for h in c["holdings"]:
            by_class[h["asset_class"]] += h["impact"]
    book_value = sum(p.value for p in portfolios)
    total = sum(c["impact"] for c in clients)
    return {
        "shock": shock,
        "clients_exposed": len(clients),
        "clients_total": len(portfolios),
        "exposure": round(sum(c["exposure"] for c in clients), 2),
        "impact": round(total, 2),
        "impact_pct": total / book_value if book_value else None,
        "by_asset_class": {k: round(v, 2) for k, v in by_class.items()},
        "clients": clients,
    }
