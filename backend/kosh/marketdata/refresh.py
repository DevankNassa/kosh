"""Daily market data refresh: AMFI NAVs, NSE bhavcopy, sectors, yield curve,
index closes. Falls back to the bundled snapshot when offline."""

import csv
import json
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .. import config, settings_store
from ..analytics.classify import SECTOR_INDEX, BROAD_MARKET_INDEX, DEBT_INDEX, classify_exchange, classify_mf
from ..models import Event, IndexPrice, Instrument, Price
from . import amfi, nse
from .curve import DEFAULT_CURVE, derive_curve

TRACKED_INDICES = sorted(set(SECTOR_INDEX.values()) | {BROAD_MARKET_INDEX, DEBT_INDEX})

log = logging.getLogger(__name__)

_INSTR_COLS = [c.name for c in Instrument.__table__.columns if c.name != "updated_at"]
# Fields that users may correct by hand; refresh only fills them when empty.
_KEEP_IF_SET = {"coupon", "coupon_freq", "maturity", "maturity_is_estimate", "rating",
                "face_value", "sector", "issuer"}


def _chunks(items: list, n: int = 500) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


_NOT_NULL = {c.name for c in Instrument.__table__.columns
             if not c.nullable and not c.primary_key and c.name != "updated_at"}


def _default(col: str):
    d = Instrument.__table__.c[col].default
    return d.arg if d is not None and not callable(d.arg) else None


def upsert_instruments(session: Session, rows: list[dict], update_cols: list[str]) -> None:
    if not rows:
        return
    table = Instrument.__table__
    for chunk in _chunks(rows):
        cols = set().union(*(r.keys() for r in chunk))
        norm = [{c: (r[c] if r.get(c) is not None else _default(c)) for c in cols | _NOT_NULL}
                for r in chunk]
        stmt = insert(table).values(norm)
        upd = {}
        for c in update_cols:
            if c not in cols:
                continue
            if c in _KEEP_IF_SET:
                upd[c] = func.coalesce(table.c[c], stmt.excluded[c])
            else:
                upd[c] = stmt.excluded[c]
        upd["updated_at"] = datetime.now()
        session.execute(stmt.on_conflict_do_update(index_elements=["isin"], set_=upd))


def upsert_prices(session: Session, rows: list[dict]) -> None:
    table = Price.__table__
    for chunk in _chunks(rows):
        stmt = insert(table).values(chunk)
        session.execute(stmt.on_conflict_do_update(
            index_elements=["isin", "date"],
            set_={"price": stmt.excluded.price, "source": stmt.excluded.source, "level": stmt.excluded.level},
        ))


def upsert_index_prices(session: Session, rows: list[dict]) -> None:
    table = IndexPrice.__table__
    for chunk in _chunks(rows):
        stmt = insert(table).values(chunk)
        session.execute(stmt.on_conflict_do_update(
            index_elements=["name", "date"], set_={"close": stmt.excluded.close},
        ))


def _refresh_amfi(session: Session) -> dict:
    latest = amfi.fetch_latest()
    instruments, prices = {}, []
    for r in latest:
        cls = classify_mf(r.category, r.name)
        for isin in r.isins:
            instruments[isin] = dict(
                isin=isin, name=r.name, kind=cls.kind, asset_class=cls.asset_class,
                sub_class=cls.sub_class, tax_class=cls.tax_class, mod_duration=cls.mod_duration,
                amfi_code=r.scheme_code, amc=r.amc, mf_category=r.category, plan=r.plan,
                issuer=r.amc, listed=False,
            )
            prices.append(dict(isin=isin, date=r.nav_date, price=r.nav, source="amfi", level="observed"))
    upsert_instruments(session, list(instruments.values()),
                       ["name", "kind", "asset_class", "sub_class", "tax_class", "mod_duration",
                        "amfi_code", "amc", "mf_category", "plan", "issuer", "listed"])
    upsert_prices(session, prices)
    prev_count = 0
    try:
        prev = amfi.previous_navs(latest)
        upsert_prices(session, [dict(isin=i, date=d, price=p, source="amfi", level="observed")
                                for i, (d, p) in prev.items()])
        prev_count = len(prev)
    except Exception as e:  # history is a nice-to-have (day change for MFs)
        log.warning("AMFI history failed: %s", e)
    asof = max((r.nav_date for r in latest), default=None)
    return {"ok": True, "asof": asof, "schemes": len(latest), "isins": len(instruments),
            "previous_navs": prev_count}


def _refresh_nse(session: Session, today: date) -> dict:
    cur, prev = nse.fetch_latest_bhavcopies(today)
    if not cur:
        raise RuntimeError("No NSE bhavcopy found for the last 10 days")
    known_inf = set(session.scalars(select(Instrument.isin).where(Instrument.isin.like("INF%"))))
    new_rows, inf_symbols = [], []
    for r in cur:
        if r.isin.startswith("INF") and r.isin in known_inf:
            inf_symbols.append(dict(isin=r.isin, name=r.name, symbol=r.symbol, listed=True))
            continue
        fields = classify_exchange(r.isin, r.series, r.name, r.symbol)
        fields.update(isin=r.isin, name=r.name, symbol=r.symbol, listed=True)
        new_rows.append(fields)
    upsert_instruments(session, new_rows,
                       ["name", "symbol", "listed", "kind", "asset_class", "sub_class", "tax_class",
                        "coupon", "coupon_freq", "maturity", "maturity_is_estimate", "rating",
                        "face_value", "tax_free_interest", "mod_duration"])
    # ETFs already classified from AMFI: only add symbol / listed flag
    for chunk in _chunks(inf_symbols):
        for row in chunk:
            session.execute(Instrument.__table__.update()
                            .where(Instrument.isin == row["isin"])
                            .values(symbol=row["symbol"], listed=True))
    prices = [dict(isin=r.isin, date=r.trade_date, price=r.close, source="nse", level="observed")
              for r in cur + prev]
    upsert_prices(session, prices)

    curve, n = derive_curve(cur, cur[0].trade_date)
    settings_store.put(session, "yield_curve", {
        "asof": cur[0].trade_date,
        "points": curve,
        "source": f"Indicative: derived from {n} G-sec trades on NSE" if n else "Default curve (too few trades)",
    })
    return {"ok": True, "asof": cur[0].trade_date, "securities": len(cur),
            "previous_date": prev[0].trade_date if prev else None}


def _refresh_sectors(session: Session) -> dict:
    sectors = nse.fetch_sectors()
    for isin, ind in sectors.items():
        session.execute(Instrument.__table__.update()
                        .where(Instrument.isin == isin).values(sector=ind))
    return {"ok": bool(sectors), "count": len(sectors)}


def _refresh_actions(session: Session, today: date) -> dict:
    """Recent splits / bonus issues, so share price history stays comparable."""
    from .backfill import store_corporate_actions
    rows = nse.fetch_corporate_actions(today - timedelta(days=30), today)
    return {"ok": True, "count": store_corporate_actions(session, rows)}


def _refresh_indices(session: Session, asof: date) -> dict:
    wanted = ["Nifty 50", "Nifty Bank", "Nifty Midcap 100", "Nifty Smallcap 100",
              "Nifty Financial Services", "Nifty IT", "Nifty 10 yr Benchmark G-Sec", "India VIX"]
    rows = nse.fetch_index_closes(asof)
    by_name = {r["name"]: r for r in rows}
    pick = [by_name[n] for n in wanted if n in by_name]
    pick.sort(key=lambda r: wanted.index(r["name"]))
    settings_store.put(session, "indices", {"asof": asof, "items": pick})
    # also store today's close for every index (real-data scenarios and the
    # market/event chart read these), building up real history over time
    stored = [dict(name=r["name"], date=asof, close=r["close"]) for r in rows if r["name"]]
    upsert_index_prices(session, stored)
    return {"ok": bool(pick), "count": len(pick), "stored": len(stored),
            "tracked": sum(r["name"] in TRACKED_INDICES for r in stored)}


def _add_trading_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _true_up_events(session: Session, today: date) -> dict:
    """Once a logged (non-sample) event is 5+ trading days old, replace the
    consultant's guess with what actually happened, from real index data."""
    from ..impact.historical import real_shock

    updated = 0
    rows = session.scalars(select(Event).where(Event.is_sample.is_(False), Event.actual_tags.is_(None)))
    for e in rows:
        window_end = _add_trading_days(e.date, 5)
        if window_end > today:
            continue
        flt = (e.tags or {}).get("filter") if isinstance(e.tags, dict) else None
        sector = flt.get("sector") if isinstance(flt, dict) else None
        shock = real_shock(session, sector, e.date, window_end)
        if shock:
            e.actual_tags = shock
            updated += 1
    return {"ok": True, "updated": updated}


def refresh_market_data(session: Session, today: date | None = None) -> dict:
    today = today or date.today()
    status: dict = {"started": datetime.now().isoformat(timespec="seconds")}
    for name, fn in (("amfi", lambda: _refresh_amfi(session)),
                     ("nse", lambda: _refresh_nse(session, today))):
        try:
            status[name] = fn()
            session.commit()
        except Exception as e:
            session.rollback()
            log.warning("%s refresh failed: %s", name, str(e)[:500])
            status[name] = {"ok": False, "error": str(e)[:300]}
    nse_asof = status.get("nse", {}).get("asof")
    for name, fn in (("sectors", lambda: _refresh_sectors(session)),
                     ("actions", lambda: _refresh_actions(session, today)),
                     ("indices", lambda: _refresh_indices(session, nse_asof) if nse_asof else {"ok": False})):
        try:
            status[name] = fn()
            session.commit()
        except Exception as e:
            session.rollback()
            status[name] = {"ok": False, "error": str(e)[:300]}
    if not session.get(Instrument, "INE002A01018") and not status.get("amfi", {}).get("ok"):
        status["snapshot"] = load_snapshot(session)
    if settings_store.get(session, "yield_curve") is None:
        settings_store.put(session, "yield_curve", {"asof": None, "points": DEFAULT_CURVE,
                                                     "source": "Default curve"})
    try:
        status["events_trued_up"] = _true_up_events(session, today)
        session.commit()
    except Exception as e:
        session.rollback()
        log.warning("event true-up failed: %s", e)
        status["events_trued_up"] = {"ok": False, "error": str(e)[:300]}
    status["finished"] = datetime.now().isoformat(timespec="seconds")
    settings_store.put(session, "market_status", status)
    session.commit()
    return status


# ---------------------------------------------------------------- snapshot
# A small, committed copy of instruments and prices for the demo ISINs, so the
# showcase still works without internet. Regenerate with
# `python -m kosh snapshot` after a successful refresh.

def write_snapshot(session: Session, isins: set[str]) -> None:
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.SNAPSHOT_DIR / "instruments.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_INSTR_COLS)
        w.writeheader()
        for ins in session.scalars(select(Instrument).where(Instrument.isin.in_(isins)).order_by(Instrument.isin)):
            w.writerow({c: getattr(ins, c) for c in _INSTR_COLS})
    with open(config.SNAPSHOT_DIR / "prices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["isin", "date", "price", "source"])
        for isin in sorted(isins):
            for p in session.scalars(select(Price).where(Price.isin == isin)
                                     .order_by(Price.date.desc()).limit(2)):
                w.writerow([p.isin, p.date.isoformat(), p.price, p.source])
    meta = {k: settings_store.get(session, k) for k in ("yield_curve", "indices")}
    (config.SNAPSHOT_DIR / "meta.json").write_text(json.dumps(meta, default=str, indent=1))


def _coerce(col: str, v: str):
    if v == "":
        return None
    t = Instrument.__table__.c[col].type.python_type
    if t is bool:
        return v in ("True", "1", "true")
    if t is date:
        return date.fromisoformat(v)
    return t(v)


def load_snapshot(session: Session) -> dict:
    ipath = config.SNAPSHOT_DIR / "instruments.csv"
    if not ipath.exists():
        return {"ok": False, "error": "no snapshot bundled"}
    with open(ipath) as f:
        rows = [{c: _coerce(c, v) for c, v in r.items()} for r in csv.DictReader(f)]
    upsert_instruments(session, rows, [c for c in _INSTR_COLS if c != "isin"])
    with open(config.SNAPSHOT_DIR / "prices.csv") as f:
        prices = [dict(isin=r["isin"], date=date.fromisoformat(r["date"]), price=float(r["price"]),
                       source="snapshot", level="observed") for r in csv.DictReader(f)]
    upsert_prices(session, prices)
    meta_path = config.SNAPSHOT_DIR / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        for k, v in meta.items():
            if v:
                settings_store.put(session, k, v)
    asof = max((p["date"] for p in prices), default=None)
    return {"ok": True, "asof": asof, "instruments": len(rows)}
