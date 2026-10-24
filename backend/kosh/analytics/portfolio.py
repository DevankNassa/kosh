"""Holdings, FIFO lots, valuation and portfolio summaries, derived from the
transactions table."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from .. import settings_store
from ..models import Account, Client, Instrument, Price, Transaction
from ..tax import rules
from .adjust import factor_between, factors_for
from .bonds import RATING_SPREADS, BondTerms, accrued, cashflows, clean_price, interp_curve, risk, ytm
from .classify import equity_share, maturity_bucket, rating_bucket
from .xirr import xirr

BOND_KINDS = ("gsec", "sdl", "tbill", "corp_bond")
STALE_AFTER_DAYS = 7


# ---------------------------------------------------------------- lots

@dataclass
class Lot:
    txn_id: int
    account_id: int
    isin: str
    acquired: date
    units: float
    unit_cost: Optional[float]
    date_is_estimate: bool

    @property
    def cost_known(self) -> bool:
        return self.unit_cost is not None and not self.date_is_estimate


@dataclass
class Realised:
    account_id: int
    isin: str
    acquired: date
    sold: date
    units: float
    unit_cost: Optional[float]
    proceeds: float
    cost_known: bool
    hypothetical: bool = False

    @property
    def gain(self) -> Optional[float]:
        if not self.cost_known:
            return None
        return self.proceeds - self.units * self.unit_cost


@dataclass
class TxnIn:
    id: int
    account_id: int
    isin: str
    trade_date: date
    type: str
    units: float
    price: Optional[float]
    amount: Optional[float]
    date_is_estimate: bool = False


def _order(t: TxnIn):
    return (t.trade_date, 0 if t.type in ("OPENING", "BUY") else 1, t.id)


def run_fifo(txns: list[TxnIn]) -> tuple[dict[tuple[int, str], list[Lot]], list[Realised], list[str]]:
    """FIFO per (account, ISIN). FIFO is how Indian depositories and RTAs
    match redemptions to purchases."""
    open_lots: dict[tuple[int, str], list[Lot]] = defaultdict(list)
    realised: list[Realised] = []
    warnings: list[str] = []
    for t in sorted(txns, key=_order):
        key = (t.account_id, t.isin)
        if t.type in ("BUY", "OPENING"):
            open_lots[key].append(Lot(t.id, t.account_id, t.isin, t.trade_date, t.units,
                                      t.price, t.date_is_estimate))
            continue
        if t.type != "SELL":
            continue
        unit_px = t.price if t.price is not None else ((t.amount or 0.0) / t.units if t.units else 0.0)
        remaining = t.units
        lots = open_lots[key]
        while remaining > 1e-9 and lots:
            lot = lots[0]
            take = min(lot.units, remaining)
            realised.append(Realised(t.account_id, t.isin, lot.acquired, t.trade_date, take,
                                     lot.unit_cost, take * unit_px, lot.cost_known))
            lot.units -= take
            remaining -= take
            if lot.units <= 1e-9:
                lots.pop(0)
        if remaining > 1e-6:
            warnings.append(f"{t.isin}: sold {remaining:.3f} more units than held on {t.trade_date}")
    return {k: v for k, v in open_lots.items() if v}, realised, warnings


def load_txns(session: Session, client_id: int) -> list[TxnIn]:
    rows = session.execute(
        select(Transaction).join(Account).where(Account.client_id == client_id)
    ).scalars()
    return [TxnIn(t.id, t.account_id, t.isin, t.trade_date, t.type, t.units, t.price, t.amount,
                  t.date_is_estimate) for t in rows]


# ---------------------------------------------------------------- prices

@dataclass
class Quote:
    price: float
    date: Optional[date]
    source: str
    level: str  # observed | model | stale
    prev_price: Optional[float] = None
    prev_date: Optional[date] = None
    ytm: Optional[float] = None


def market_asof(session: Session) -> date:
    st = settings_store.get(session, "market_status") or {}
    for k in ("nse", "amfi", "snapshot"):
        a = (st.get(k) or {}).get("asof")
        if a:
            return date.fromisoformat(str(a)[:10])
    return date.today()


def get_curve(session: Session) -> list[tuple[float, float]]:
    c = settings_store.get(session, "yield_curve") or {}
    pts = c.get("points")
    if pts:
        return [(float(t), float(y)) for t, y in pts]
    from ..marketdata.curve import DEFAULT_CURVE
    return DEFAULT_CURVE


def bond_terms(ins: Instrument) -> Optional[BondTerms]:
    if ins.maturity is None or ins.coupon is None:
        return None
    return BondTerms(ins.coupon, ins.maturity, ins.coupon_freq or 1)


def model_quote(ins: Instrument, curve, asof: date) -> Optional[Quote]:
    terms = bond_terms(ins)
    if terms is None or not ins.face_value or terms.maturity <= asof:
        return None
    tenor = (terms.maturity - asof).days / 365.25
    y = interp_curve(curve, tenor)
    if ins.kind == "corp_bond":
        y += RATING_SPREADS.get(rating_bucket(ins.rating), RATING_SPREADS["Unrated / unknown"])
        if ins.tax_free_interest:
            y -= 0.015  # tax-free bonds trade below taxable yields
    pct = clean_price(terms, y, asof)
    if ins.kind == "corp_bond":
        pct += accrued(terms, asof)  # exchange NCD prices include accrued interest
    return Quote(pct * ins.face_value / 100.0, asof, "model", "model", ytm=y)


class PriceBook:
    def __init__(self, session: Session, instruments: dict[str, Instrument]):
        self.asof = market_asof(session)
        self.curve = get_curve(session)
        self.instruments = instruments
        self._quotes: dict[str, Optional[Quote]] = {}
        isins = list(instruments)
        rows: dict[str, list[Price]] = defaultdict(list)
        for i in range(0, len(isins), 500):
            chunk = isins[i:i + 500]
            # only the latest two prices per ISIN, not the full stored history
            rn = (func.row_number().over(partition_by=Price.isin, order_by=Price.date.desc())
                  .label("rn"))
            latest = select(Price, rn).where(Price.isin.in_(chunk)).subquery()
            recent = aliased(Price, latest)
            q = select(recent).where(latest.c.rn <= 2).order_by(recent.isin, recent.date.desc())
            for p in session.scalars(q):
                rows[p.isin].append(p)
        # a split / bonus ex-date between the last two closes isn't a price move
        self._actions = factors_for(session, isins, since=self.asof - timedelta(days=30)) if isins else {}
        for isin, ins in instruments.items():
            self._quotes[isin] = self._build(ins, rows.get(isin, []))

    def _build(self, ins: Instrument, prices: list[Price]) -> Optional[Quote]:
        obs = [p for p in prices if p.source != "statement"]
        latest = prices[0] if prices else None
        fresh = obs and (self.asof - obs[0].date).days <= STALE_AFTER_DAYS
        if fresh:
            p = obs[0]
            q = Quote(p.price, p.date, p.source, "observed")
            if len(obs) > 1:
                q.prev_price, q.prev_date = obs[1].price, obs[1].date
                q.prev_price *= factor_between(self._actions.get(ins.isin, ()), obs[1].date, p.date)
            return q
        if ins.kind in BOND_KINDS:
            m = model_quote(ins, self.curve, self.asof)
            if m:
                return m
        if latest:
            return Quote(latest.price, latest.date, latest.source, "stale")
        return None

    def get(self, isin: str) -> Optional[Quote]:
        return self._quotes.get(isin)


# ---------------------------------------------------------------- holdings

@dataclass
class Holding:
    account: Account
    instrument: Instrument
    lots: list[Lot]
    quote: Optional[Quote]
    asof: date
    units: float = 0.0
    value: float = 0.0
    known_units: float = 0.0
    known_cost: float = 0.0
    known_value: float = 0.0
    day_change: Optional[float] = None
    st_units: float = 0.0
    lt_units: float = 0.0
    unknown_units: float = 0.0
    mod_duration: Optional[float] = None
    convexity: float = 0.0
    ytm: Optional[float] = None
    xirr: Optional[float] = None
    cash_flows: list[dict] = field(default_factory=list)

    def compute(self) -> "Holding":
        ins = self.instrument
        self.units = sum(l.units for l in self.lots)
        px = self.quote.price if self.quote else 0.0
        self.value = self.units * px
        for l in self.lots:
            if l.cost_known:
                self.known_units += l.units
                self.known_cost += l.units * l.unit_cost
                if rules.is_long_term(ins.tax_class, l.acquired, self.asof):
                    self.lt_units += l.units
                else:
                    self.st_units += l.units
            else:
                self.unknown_units += l.units
        self.known_value = self.known_units * px
        if self.quote and self.quote.prev_price:
            self.day_change = self.units * (px - self.quote.prev_price)
        self._debt_analytics()
        return self

    def _debt_analytics(self) -> None:
        ins = self.instrument
        if ins.kind in BOND_KINDS:
            terms = bond_terms(ins)
            if terms and terms.maturity > self.asof and self.quote:
                y = self.quote.ytm
                if y is None and ins.face_value:
                    pct = self.quote.price / ins.face_value * 100.0
                    if ins.kind == "corp_bond":
                        pct -= accrued(terms, self.asof)
                    y = ytm(terms, pct, self.asof)
                if y is not None:
                    self.ytm = y
                    self.mod_duration, self.convexity = risk(terms, y, self.asof)
                face_total = self.units * (ins.face_value or 0)
                if face_total:
                    horizon = self.asof + timedelta(days=366)
                    for d, cf in cashflows(terms, self.asof):
                        if d > horizon:
                            break
                        is_mat = d == terms.maturity
                        coupon_part = cf - (100.0 if is_mat else 0.0)
                        if coupon_part > 0:
                            self.cash_flows.append({"date": d, "type": "coupon",
                                                    "amount": face_total * coupon_part / 100.0})
                        if is_mat:
                            self.cash_flows.append({"date": d, "type": "maturity", "amount": face_total})
        elif ins.mod_duration is not None and ins.asset_class in ("debt", "hybrid"):
            self.mod_duration = ins.mod_duration

    @property
    def debt_share(self) -> float:
        ins = self.instrument
        if ins.asset_class == "debt":
            return 1.0
        if ins.asset_class == "hybrid":
            return max(0.0, 1.0 - equity_share(ins.asset_class, ins.sub_class))
        return 0.0

    @property
    def unrealised(self) -> Optional[float]:
        return self.known_value - self.known_cost if self.known_units else None

    def to_dict(self) -> dict:
        ins, q = self.instrument, self.quote
        first_lt = None
        for l in self.lots:
            if l.cost_known and not rules.is_long_term(ins.tax_class, l.acquired, self.asof):
                d = rules.long_term_from(ins.tax_class, l.acquired, self.asof)
                if d and (first_lt is None or d < first_lt):
                    first_lt = d
        return {
            "account_id": self.account.id,
            "account": f"{self.account.provider or ''} · {self.account.identifier}".strip(" ·"),
            "account_kind": self.account.kind,
            "isin": ins.isin,
            "name": ins.name,
            "symbol": ins.symbol,
            "kind": ins.kind,
            "asset_class": ins.asset_class,
            "sub_class": ins.sub_class,
            "sector": ins.sector,
            "tax_class": ins.tax_class,
            "units": round(self.units, 4),
            "price": q.price if q else None,
            "price_date": q.date if q else None,
            "price_source": q.source if q else None,
            "price_level": q.level if q else "missing",
            "value": round(self.value, 2),
            "cost": round(self.known_cost, 2) if self.known_units else None,
            "avg_cost": round(self.known_cost / self.known_units, 4) if self.known_units else None,
            "unrealised": round(self.unrealised, 2) if self.unrealised is not None else None,
            "unrealised_pct": (self.unrealised / self.known_cost) if self.known_cost else None,
            "day_change": round(self.day_change, 2) if self.day_change is not None else None,
            "st_units": round(self.st_units, 4),
            "lt_units": round(self.lt_units, 4),
            "unknown_cost_units": round(self.unknown_units, 4),
            "next_long_term_date": first_lt,
            "ytm": self.ytm,
            "mod_duration": self.mod_duration,
            "rating": ins.rating,
            "maturity": ins.maturity,
            "xirr": self.xirr,
            "lots": [
                {"acquired": l.acquired, "units": round(l.units, 4), "unit_cost": l.unit_cost,
                 "cost_known": l.cost_known, "date_is_estimate": l.date_is_estimate,
                 "term": ("LT" if rules.is_long_term(ins.tax_class, l.acquired, self.asof) else "ST")
                 if l.cost_known else None}
                for l in self.lots
            ],
        }


@dataclass
class Portfolio:
    client: Client
    asof: date
    holdings: list[Holding]
    realised: list[Realised]
    warnings: list[str]
    txns: list[TxnIn]
    open_lots: dict

    @property
    def value(self) -> float:
        return sum(h.value for h in self.holdings)

    @property
    def day_change(self) -> float:
        return sum(h.day_change or 0.0 for h in self.holdings)


def instruments_for(session: Session, isins) -> dict[str, Instrument]:
    isins = list(set(isins))
    out = {}
    for i in range(0, len(isins), 500):
        for ins in session.scalars(select(Instrument).where(Instrument.isin.in_(isins[i:i + 500]))):
            out[ins.isin] = ins
    return out


def build_portfolio(session: Session, client: Client, book: Optional[PriceBook] = None) -> Portfolio:
    txns = load_txns(session, client.id)
    open_lots, realised, warnings = run_fifo(txns)
    instruments = instruments_for(session, [t.isin for t in txns])
    if book is None:
        book = PriceBook(session, instruments)
    accounts = {a.id: a for a in client.accounts}
    holdings = []
    for (acct_id, isin), lots in open_lots.items():
        ins = instruments.get(isin)
        if ins is None:
            continue
        h = Holding(accounts[acct_id], ins, lots, book.get(isin), book.asof).compute()
        holdings.append(h)
    _holding_xirr(holdings, txns)
    holdings.sort(key=lambda h: -h.value)
    for h in holdings:
        if h.quote is None:
            warnings.append(f"No price for {h.instrument.name} ({h.instrument.isin})")
    return Portfolio(client, book.asof, holdings, realised, warnings, txns, open_lots)


def _holding_xirr(holdings: list[Holding], txns: list[TxnIn]) -> None:
    by_key = defaultdict(list)
    for t in txns:
        by_key[(t.account_id, t.isin)].append(t)
    for h in holdings:
        flows = []
        ok = True
        for t in by_key[(h.account.id, h.instrument.isin)]:
            if t.price is None or t.date_is_estimate:
                ok = False
                break
            amt = t.units * t.price
            flows.append((t.trade_date, -amt if t.type in ("BUY", "OPENING") else amt))
        if ok and flows and h.value:
            flows.append((h.asof, h.value))
            h.xirr = xirr(flows)


def portfolio_xirr(p: Portfolio) -> Optional[float]:
    """XIRR over holdings whose full cost history is known."""
    known = {(h.account.id, h.instrument.isin) for h in p.holdings if h.unknown_units < 1e-9}
    sold_only = {(t.account_id, t.isin) for t in p.txns} - {(h.account.id, h.instrument.isin) for h in p.holdings}
    flows = []
    for t in p.txns:
        k = (t.account_id, t.isin)
        if k not in known and k not in sold_only:
            continue
        if t.price is None or t.date_is_estimate:
            continue
        amt = t.units * t.price
        flows.append((t.trade_date, -amt if t.type in ("BUY", "OPENING") else amt))
    terminal = sum(h.value for h in p.holdings if (h.account.id, h.instrument.isin) in known)
    if terminal:
        flows.append((p.asof, terminal))
    return xirr(flows)


# ---------------------------------------------------------------- summaries

def _group(holdings: list[Holding], key) -> list[dict]:
    agg: dict[str, float] = defaultdict(float)
    for h in holdings:
        for k, share in key(h):
            agg[k or "Other"] += h.value * share
    total = sum(agg.values()) or 1.0
    return sorted(({"name": k, "value": round(v, 2), "pct": v / total} for k, v in agg.items() if v),
                  key=lambda r: -r["value"])


def allocations(p: Portfolio) -> dict:
    hs = p.holdings
    debt = [h for h in hs if h.instrument.asset_class == "debt"]
    eq_direct = [h for h in hs if h.instrument.kind in ("equity", "reit_invit")]
    return {
        "asset_class": _group(hs, lambda h: [(h.instrument.asset_class, 1.0)]),
        "sub_class": _group(hs, lambda h: [(h.instrument.sub_class or h.instrument.kind, 1.0)]),
        "sector": _group(eq_direct, lambda h: [(h.instrument.sector or "Unclassified", 1.0)]),
        "issuer": _group(hs, lambda h: [(_issuer_label(h.instrument), 1.0)])[:12],
        "rating": _group(debt, lambda h: [(_rating_label(h.instrument), 1.0)]),
        "maturity": _group([h for h in debt if h.instrument.kind in BOND_KINDS],
                           lambda h: [(maturity_bucket(h.instrument.maturity, p.asof), 1.0)]),
        "provider": _group(hs, lambda h: [(h.account.provider or h.account.kind, 1.0)]),
    }


def _issuer_label(ins: Instrument) -> str:
    if ins.kind in ("mf",):
        return ins.amc or "Mutual fund"
    if ins.kind in ("gsec", "sdl", "tbill", "sgb"):
        return "Government of India" if ins.kind != "sdl" else "State governments"
    return ins.issuer or _clean_company(ins.name)


def _clean_company(name: str) -> str:
    return (name or "").replace(" LIMITED", "").replace(" LTD.", "").replace(" LTD", "").title()


def _rating_label(ins: Instrument) -> str:
    if ins.kind == "mf" or ins.kind == "etf":
        return "Debt funds (fund-level)"
    return rating_bucket(ins.rating)


def target_drift(p: Portfolio) -> list[dict]:
    target = p.client.target_allocation or {}
    cur = {r["name"]: r for r in _group(p.holdings, lambda h: [(h.instrument.asset_class, 1.0)])}
    total = p.value or 1.0
    out = []
    for cls in sorted(set(target) | set(cur), key=lambda c: ["equity", "debt", "hybrid", "gold", "other"].index(c)
                      if c in ["equity", "debt", "hybrid", "gold", "other"] else 9):
        cur_pct = cur.get(cls, {}).get("pct", 0.0)
        tgt = target.get(cls)
        out.append({
            "asset_class": cls,
            "current_pct": cur_pct,
            "target_pct": tgt,
            "current_value": cur.get(cls, {}).get("value", 0.0),
            "drift_pct": (cur_pct - tgt) if tgt is not None else None,
            "amount_to_target": round((tgt - cur_pct) * total, 2) if tgt is not None else None,
        })
    return out


def debt_summary(p: Portfolio) -> dict:
    debtish = [h for h in p.holdings if h.debt_share > 0 and h.mod_duration is not None]
    w = sum(h.value * h.debt_share for h in debtish)
    dur = sum(h.value * h.debt_share * h.mod_duration for h in debtish) / w if w else None
    bonds = [h for h in p.holdings if h.ytm is not None]
    bw = sum(h.value for h in bonds)
    flows = []
    for h in p.holdings:
        for cf in h.cash_flows:
            flows.append({**cf, "name": h.instrument.name, "isin": h.instrument.isin})
    flows.sort(key=lambda f: f["date"])
    return {
        "debt_value": round(sum(h.value * h.debt_share for h in p.holdings), 2),
        "weighted_mod_duration": dur,
        "bond_value": round(bw, 2),
        "bond_weighted_ytm": sum(h.value * h.ytm for h in bonds) / bw if bw else None,
        "cash_flows_12m": flows,
        "duration_note": "Debt fund durations are category estimates; bond durations are computed.",
    }


def summary(p: Portfolio, include_holdings: bool = True) -> dict:
    hs = p.holdings
    known_cost = sum(h.known_cost for h in hs)
    known_value = sum(h.known_value for h in hs)
    prev_total = sum(h.value - (h.day_change or 0.0) for h in hs)
    unknown_value = sum(h.unknown_units * (h.quote.price if h.quote else 0) for h in hs)
    out = {
        "client_id": p.client.id,
        "asof": p.asof,
        "value": round(p.value, 2),
        "day_change": round(p.day_change, 2),
        "day_change_pct": p.day_change / prev_total if prev_total else None,
        "cost": round(known_cost, 2),
        "unrealised": round(known_value - known_cost, 2),
        "unrealised_pct": (known_value - known_cost) / known_cost if known_cost else None,
        "xirr": portfolio_xirr(p),
        "holdings_count": len(hs),
        "cost_unknown_value": round(unknown_value, 2),
        "stale_prices": sum(1 for h in hs if not h.quote or h.quote.level == "stale"),
        "model_prices": sum(1 for h in hs if h.quote and h.quote.level == "model"),
        "warnings": p.warnings,
    }
    if include_holdings:
        out["holdings"] = [h.to_dict() for h in hs]
    return out
