"""Realised-gains view and the what-if planner.

Everything here is a calculation on changes the user enters (or a target the
client chose). Kosh does not decide what should be sold."""

import copy
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from ..analytics.portfolio import Holding, Portfolio, Realised, allocations, build_portfolio
from ..models import Client
from . import rules
from .engine import TaxProfile, compute_tax


def profile_for(client: Client, overrides: Optional[dict] = None) -> TaxProfile:
    o = overrides or {}
    return TaxProfile(
        slab_rate=float(o.get("slab_rate", client.slab_rate)),
        surcharge_rate=float(o.get("surcharge_rate", client.surcharge_rate)),
        cf_stcl=float(o.get("cf_stcl", client.cf_stcl or 0.0)),
        cf_ltcl=float(o.get("cf_ltcl", client.cf_ltcl or 0.0)),
    )


def _instr(p: Portfolio):
    return {h.instrument.isin: h.instrument for h in p.holdings}


def realised_rows(p: Portfolio, realised: list[Realised], instruments: dict) -> list[dict]:
    rows = []
    for r in realised:
        ins = instruments.get(r.isin)
        bucket = rules.bucket_for(ins.tax_class, r.acquired, r.sold) if (ins and r.cost_known) else None
        rows.append({
            "isin": r.isin,
            "name": ins.name if ins else r.isin,
            "account_id": r.account_id,
            "acquired": r.acquired,
            "sold": r.sold,
            "days_held": (r.sold - r.acquired).days,
            "units": round(r.units, 4),
            "cost": round(r.units * r.unit_cost, 2) if r.unit_cost is not None else None,
            "proceeds": round(r.proceeds, 2),
            "gain": round(r.gain, 2) if r.gain is not None else None,
            "bucket": bucket,
            "bucket_label": rules.BUCKET_LABELS.get(bucket) if bucket else "Excluded: cost or date unknown",
            "hypothetical": r.hypothetical,
        })
    return rows


def _sum_buckets(rows: list[dict]) -> dict[str, float]:
    g: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["bucket"] and r["gain"] is not None:
            g[r["bucket"]] += r["gain"]
    return dict(g)


def _all_instruments(session: Session, p: Portfolio) -> dict:
    from ..analytics.portfolio import instruments_for
    return instruments_for(session, {t.isin for t in p.txns})


def fy_realised(session: Session, p: Portfolio, on: Optional[date] = None, overrides=None) -> dict:
    on = on or p.asof
    start, end = rules.fy_bounds(on)
    instruments = _all_instruments(session, p)
    in_fy = [r for r in p.realised if start <= r.sold <= end]
    rows = realised_rows(p, in_fy, instruments)
    tax = compute_tax(_sum_buckets(rows), profile_for(p.client, overrides), on)
    return {
        "fy": rules.fy_of(on),
        "rows": rows,
        "excluded": sum(1 for r in rows if r["bucket"] is None),
        "tax": tax.to_dict(),
    }


# ---------------------------------------------------------------- insights

def insights(session: Session, p: Portfolio, horizon_days: int = 60, overrides=None) -> dict:
    prof = profile_for(p.client, overrides)
    rs = rules.ruleset_for(p.asof)
    soon: list[dict] = []
    loss_by_holding: dict[tuple, dict] = {}
    for h in p.holdings:
        ins = h.instrument
        px = h.quote.price if h.quote else None
        if px is None:
            continue
        for l in h.lots:
            if not l.cost_known:
                continue
            gain = l.units * (px - l.unit_cost)
            lt_date = rules.long_term_from(ins.tax_class, l.acquired, p.asof)
            is_lt = lt_date is not None and p.asof >= lt_date
            if lt_date and not is_lt and (lt_date - p.asof).days <= horizon_days and gain > 0:
                st_b = rules.bucket_for(ins.tax_class, l.acquired, p.asof)
                lt_b = rules.bucket_for(ins.tax_class, l.acquired, lt_date)
                saved = gain * (rules.bucket_rate(st_b, prof.slab_rate, rs) - rules.bucket_rate(lt_b, prof.slab_rate, rs))
                soon.append({
                    "isin": ins.isin, "name": ins.name, "account_id": h.account.id,
                    "acquired": l.acquired, "long_term_on": lt_date,
                    "days_left": (lt_date - p.asof).days, "units": round(l.units, 4),
                    "unrealised_gain": round(gain, 2), "approx_tax_difference": round(max(saved, 0), 2),
                })
            if gain < 0:
                agg = loss_by_holding.setdefault((h.account.id, ins.isin), {
                    "isin": ins.isin, "name": ins.name, "account_id": h.account.id,
                    "units": 0.0, "unrealised_loss": 0.0, "st_loss": 0.0, "lt_loss": 0.0, "lots": 0,
                })
                agg["units"] += l.units
                agg["unrealised_loss"] += gain
                agg["lt_loss" if is_lt else "st_loss"] += gain
                agg["lots"] += 1
    soon.sort(key=lambda r: r["days_left"])
    losses = [{**v, "units": round(v["units"], 4), "unrealised_loss": round(v["unrealised_loss"], 2),
               "st_loss": round(v["st_loss"], 2), "lt_loss": round(v["lt_loss"], 2)}
              for v in loss_by_holding.values()]
    losses.sort(key=lambda r: r["unrealised_loss"])
    fy = fy_realised(session, p, overrides=overrides)
    # unrealised long-term equity gains that would still fall inside the exemption
    lt_equity_gain = 0.0
    for h in p.holdings:
        if h.instrument.tax_class != "equity" or not h.quote:
            continue
        for l in h.lots:
            if l.cost_known and rules.is_long_term("equity", l.acquired, p.asof):
                lt_equity_gain += max(0.0, l.units * (h.quote.price - l.unit_cost))
    return {
        "long_term_soon": soon,
        "unrealised_losses": losses,
        "exemption_remaining": fy["tax"]["exemption_remaining"],
        "unrealised_lt_equity_gain": round(lt_equity_gain, 2),
        "fy": fy["fy"],
    }


# ---------------------------------------------------------------- what-if

def _estimate_costs(h: Holding, lot_acquired: date, sale_date: date, proceeds: float) -> tuple[float, float]:
    ins = h.instrument
    days = (sale_date - lot_acquired).days
    load = proceeds * rules.exit_load_rate(ins.kind, ins.tax_class, ins.asset_class, days)
    stt = proceeds * rules.stt_rate(ins.kind, ins.tax_class)
    return load, stt


def simulate(session: Session, client: Client, sells: list[dict], buys: list[dict] | None = None,
             sale_date: Optional[date] = None, overrides: Optional[dict] = None,
             p: Optional[Portfolio] = None) -> dict:
    """sells: [{account_id, isin, units? | amount? | all?}]; buys: [{isin, amount, asset_class?}]"""
    p = p or build_portfolio(session, client)
    sale_date = sale_date or p.asof
    prof = profile_for(client, overrides)
    holdings = {(h.account.id, h.instrument.isin): h for h in p.holdings}
    lots = {k: [copy.copy(l) for l in h.lots] for k, h in holdings.items()}
    hypothetical: list[Realised] = []
    lines, warnings = [], []
    alloc_delta: dict[str, float] = defaultdict(float)

    for s in sells:
        key = (int(s["account_id"]), s["isin"])
        h = holdings.get(key)
        if h is None or not h.quote:
            warnings.append(f"{s['isin']}: not held in that account, or no price")
            continue
        px = h.quote.price
        if s.get("all"):
            units = h.units
        elif s.get("units"):
            units = float(s["units"])
        else:
            units = float(s.get("amount", 0)) / px if px else 0.0
        units = min(units, sum(l.units for l in lots[key]))
        remaining = units
        consumed = []
        load_total = stt_total = 0.0
        while remaining > 1e-9 and lots[key]:
            l = lots[key][0]
            take = min(l.units, remaining)
            proceeds = take * px
            r = Realised(key[0], key[1], l.acquired, sale_date, take, l.unit_cost, proceeds, l.cost_known, True)
            load, stt = _estimate_costs(h, l.acquired, sale_date, proceeds)
            # exit load reduces the consideration received (and hence the gain)
            r.proceeds -= load
            load_total += load
            stt_total += stt
            hypothetical.append(r)
            bucket = rules.bucket_for(h.instrument.tax_class, l.acquired, sale_date) if l.cost_known else None
            consumed.append({
                "acquired": l.acquired, "units": round(take, 4),
                "cost": round(take * l.unit_cost, 2) if l.unit_cost is not None else None,
                "proceeds": round(r.proceeds, 2), "gain": round(r.gain, 2) if r.gain is not None else None,
                "bucket": bucket,
                "bucket_label": rules.BUCKET_LABELS.get(bucket) if bucket else "Excluded: cost or date unknown",
                "days_held": (sale_date - l.acquired).days, "exit_load": round(load, 2),
            })
            l.units -= take
            remaining -= take
            if l.units <= 1e-9:
                lots[key].pop(0)
        gross = units * px
        lines.append({
            "account_id": key[0], "isin": key[1], "name": h.instrument.name,
            "units": round(units, 4), "price": px, "gross": round(gross, 2),
            "exit_load": round(load_total, 2), "stt": round(stt_total, 2),
            "lots": consumed,
            "has_unknown_cost": any(c["bucket"] is None for c in consumed),
        })
        alloc_delta[h.instrument.asset_class] -= gross

    for b in buys or []:
        amt = float(b.get("amount", 0))
        cls = b.get("asset_class")
        if not cls and b.get("isin"):
            from ..models import Instrument
            ins = session.get(Instrument, b["isin"])
            cls = ins.asset_class if ins else "other"
        alloc_delta[cls or "other"] += amt

    instruments = _all_instruments(session, p)
    start, end = rules.fy_bounds(sale_date)
    base_rows = realised_rows(p, [r for r in p.realised if start <= r.sold <= end], instruments)
    hyp_rows = realised_rows(p, hypothetical, instruments)
    base_tax = compute_tax(_sum_buckets(base_rows), prof, sale_date)
    new_tax = compute_tax(_sum_buckets(base_rows + hyp_rows), prof, sale_date)

    gross = sum(l["gross"] for l in lines)
    loads = sum(l["exit_load"] for l in lines)
    stt = sum(l["stt"] for l in lines)
    incremental = new_tax.total - base_tax.total
    if any(l["has_unknown_cost"] for l in lines):
        warnings.append("Some units have no known cost or purchase date; their gains are excluded "
                        "from the tax estimate. Add the cost basis to include them.")
    if any(c["acquired"] < date(2018, 2, 1) and h_tc == "equity"
           for l in lines for c in l["lots"]
           for h_tc in [instruments[l["isin"]].tax_class]):
        warnings.append("Equity bought before 1-Feb-2018 may qualify for grandfathering "
                        "(cost = FMV on 31-Jan-2018); Kosh uses actual cost, so tax may be overstated.")

    before = allocations(p)["asset_class"]
    total_before = p.value
    after_vals = {r["name"]: r["value"] for r in before}
    for k, v in alloc_delta.items():
        after_vals[k] = after_vals.get(k, 0.0) + v
    total_after = sum(after_vals.values()) or 1.0
    after = sorted(({"name": k, "value": round(v, 2), "pct": v / total_after}
                    for k, v in after_vals.items() if abs(v) > 0.5), key=lambda r: -r["value"])

    return {
        "sale_date": sale_date,
        "fy": rules.fy_of(sale_date),
        "lines": lines,
        "gross_proceeds": round(gross, 2),
        "exit_loads": round(loads, 2),
        "stt": round(stt, 2),
        "tax_before": base_tax.to_dict(),
        "tax_after": new_tax.to_dict(),
        "incremental_tax": round(incremental, 2),
        "net_proceeds": round(gross - loads - stt - incremental, 2),
        "allocation_before": before,
        "allocation_after": after,
        "portfolio_value_before": round(total_before, 2),
        "assumptions": {
            "slab_rate": prof.slab_rate, "surcharge_rate": prof.surcharge_rate,
            "cf_stcl": prof.cf_stcl, "cf_ltcl": prof.cf_ltcl,
            "tax_regime": client.tax_regime, "rules": rules.ruleset_for(sale_date).name,
            "prices_asof": p.asof,
        },
        "warnings": warnings,
    }


def tax_per_lakh(session: Session, client: Client, p: Portfolio, overrides=None) -> list[dict]:
    """For each holding: estimated extra tax if ₹1 lakh (or the whole holding,
    if smaller) were sold today. A fact sheet, not a recommendation."""
    out = []
    for h in p.holdings:
        if not h.quote or not h.value:
            continue
        amt = min(100_000.0, h.value)
        r = simulate(session, client, [{"account_id": h.account.id, "isin": h.instrument.isin, "amount": amt}],
                     overrides=overrides, p=p)
        cost = r["incremental_tax"] + r["exit_loads"] + r["stt"]
        out.append({
            "account_id": h.account.id, "isin": h.instrument.isin, "name": h.instrument.name,
            "amount": round(amt, 2), "tax_and_costs": round(cost, 2),
            "per_lakh": round(cost / amt * 100_000, 2) if amt else None,
            "has_unknown_cost": any(l["has_unknown_cost"] for l in r["lines"]),
        })
    return out
