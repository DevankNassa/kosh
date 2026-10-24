"""Historical market data, stored in the database day by day.

- `backfill_history` loads a past date range from the same free end-of-day
  files the daily refresh uses: NSE bhavcopy (every listed security), NSE
  index closes (every index), AMFI NAVs (every scheme), plus NSE's list of
  splits / bonus issues (to adjust share prices). It commits after each
  day (each week for AMFI), skips days already stored, and can be stopped and
  re-run safely.
- `catch_up` fills the gap since the last stored trading day, so days the
  laptop was off are not lost.
- `backfill_indices` / `backfill_instrument_prices` fetch narrow windows on
  demand for the market/event chart and historical scenarios
  (impact/historical.py)."""

import logging
import time
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..analytics.classify import classify_exchange, classify_mf
from ..models import CorporateAction, IndexPrice, Instrument, Price
from . import amfi, nse
from .refresh import upsert_index_prices, upsert_instruments, upsert_prices, _chunks

log = logging.getLogger(__name__)

SOURCES = ("actions", "indices", "nse", "amfi")
# a day counts as stored once it has at least this many rows (a full day has
# ~3,000 NSE securities, ~100 indices, ~15,000+ AMFI ISINs)
_FULL_DAY = {"nse": 500, "indices": 20, "amfi": 2000}
AMFI_CHUNK_DAYS = 7
MAX_CONSECUTIVE_ERRORS = 4

Progress = Callable[[dict], None]


def _weekdays(start: date, end: date) -> list[date]:
    """Weekdays in [start, end], newest first, so recent history lands first."""
    out, d = [], end
    while d >= start:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def stored_days(session: Session, source: str, start: date, end: date) -> set[date]:
    """Days in [start, end] that already hold a full day of `source` data."""
    if source == "indices":
        q = (select(IndexPrice.date).where(IndexPrice.date.between(start, end))
             .group_by(IndexPrice.date).having(func.count() >= _FULL_DAY["indices"]))
    else:
        q = (select(Price.date).where(Price.source == source, Price.date.between(start, end))
             .group_by(Price.date).having(func.count() >= _FULL_DAY[source]))
    return set(session.scalars(q))


def insert_prices_if_missing(session: Session, rows: list[dict]) -> None:
    """Like upsert_prices, but never replaces a stored price. AMFI history
    uses this so an ETF's NSE closing price (stored by the daily refresh)
    is not overwritten by its NAV, whichever loads first."""
    table = Price.__table__
    for chunk in _chunks(rows):
        session.execute(insert(table).values(chunk).on_conflict_do_nothing(index_elements=["isin", "date"]))


class _Known:
    """ISINs already in the instruments table, so history for securities
    that have since been delisted or wound up still gets a name and class."""

    def __init__(self, session: Session):
        self.isins = set(session.scalars(select(Instrument.isin)))

    def add_missing(self, session: Session, rows: dict[str, dict]) -> None:
        new = [r for isin, r in rows.items() if isin not in self.isins]
        if new:
            upsert_instruments(session, new, [])
            self.isins.update(r["isin"] for r in new)


def _store_nse_day(session: Session, rows: list[nse.BhavRow], known: _Known) -> int:
    known.add_missing(session, {
        r.isin: {**classify_exchange(r.isin, r.series, r.name, r.symbol),
                 "isin": r.isin, "name": r.name or r.symbol, "symbol": r.symbol, "listed": False}
        for r in rows if not r.isin.startswith("INF")
    })
    upsert_prices(session, [dict(isin=r.isin, date=r.trade_date, price=r.close, source="nse", level="observed")
                            for r in rows])
    return len(rows)


def _store_amfi_rows(session: Session, rows: list[amfi.NavRow], known: _Known) -> int:
    instruments, prices = {}, {}
    for r in rows:
        cls = classify_mf(r.category, r.name)
        for isin in r.isins:
            instruments[isin] = dict(
                isin=isin, name=r.name, kind=cls.kind, asset_class=cls.asset_class,
                sub_class=cls.sub_class, tax_class=cls.tax_class, mod_duration=cls.mod_duration,
                amfi_code=r.scheme_code, amc=r.amc, mf_category=r.category, plan=r.plan,
                issuer=r.amc, listed=False,
            )
            prices[(isin, r.nav_date)] = dict(isin=isin, date=r.nav_date, price=r.nav,
                                              source="amfi", level="observed")
    known.add_missing(session, instruments)
    insert_prices_if_missing(session, list(prices.values()))
    return len(prices)


def store_corporate_actions(session: Session, rows: list[dict]) -> int:
    for chunk in _chunks(rows):
        session.execute(insert(CorporateAction.__table__).values(chunk).on_conflict_do_nothing())
    return len(rows)


def _amfi_windows(days: list[date]) -> list[tuple[date, date]]:
    """Group newest-first weekdays into calendar windows of AMFI_CHUNK_DAYS."""
    if not days:
        return []
    out, end, start = [], days[0], days[-1]
    while end >= start:
        lo = max(start, end - timedelta(days=AMFI_CHUNK_DAYS - 1))
        out.append((lo, end))
        end = lo - timedelta(days=1)
    return out


def backfill_history(session: Session, start: date, end: date,
                     sources: Iterable[str] = SOURCES,
                     progress: Optional[Progress] = None,
                     should_stop: Optional[Callable[[], bool]] = None,
                     pause: float = 0.15) -> dict:
    """Store end-of-day history for [start, end]. Returns per-source counts."""
    sources = [s for s in SOURCES if s in set(sources)]
    days = _weekdays(start, end)
    have = {s: stored_days(session, s, start, end) for s in sources if s != "actions"}
    plan: list[tuple[str, object]] = []
    for s in sources:
        if s == "actions":
            plan.append((s, (start, end)))  # a few requests for the whole range
        elif s == "amfi":
            # skip a week once every NSE trading day in it has NAVs (NSE days
            # stand in for the trading calendar; holidays have no NAVs)
            nse_days = have.get("nse") or stored_days(session, "nse", start, end)
            for lo, hi in _amfi_windows(days):
                trading = {d for d in nse_days if lo <= d <= hi} or {d for d in days if lo <= d <= hi}
                got = {d for d in have["amfi"] if lo <= d <= hi}
                if not got or not trading <= got:
                    plan.append((s, (lo, hi)))
        else:
            plan += [(s, d) for d in days if d not in have[s]]

    summary = {s: {"fetched": 0, "rows": 0, "no_data": 0, "errors": 0,
                   "already_stored": (len(have[s]) if s in ("nse", "indices") else None)} for s in sources}
    known = _Known(session)
    failing = {s: 0 for s in sources}
    stopped = False

    with nse._client() as http:
        for i, (src, step) in enumerate(plan):
            if should_stop and should_stop():
                stopped = True
                break
            if failing[src] >= MAX_CONSECUTIVE_ERRORS:
                continue
            if progress:
                label = step if isinstance(step, date) else step[1]
                progress({"done": i, "total": len(plan), "source": src, "date": label})
            try:
                if src == "nse":
                    rows = nse.fetch_bhavcopy(step, http)
                    n = _store_nse_day(session, rows, known) if rows else 0
                elif src == "indices":
                    rows = nse.fetch_index_closes(step, http)
                    pick = [dict(name=r["name"], date=step, close=r["close"]) for r in rows if r["name"]]
                    upsert_index_prices(session, pick)
                    n = len(pick)
                elif src == "actions":
                    n = store_corporate_actions(session, nse.fetch_corporate_actions(*step))
                else:
                    n = _store_amfi_rows(session, amfi.fetch_history(*step), known)
                session.commit()
                failing[src] = 0
                summary[src]["fetched" if n else "no_data"] += 1
                summary[src]["rows"] += n
            except Exception as e:
                session.rollback()
                failing[src] += 1
                summary[src]["errors"] += 1
                summary[src]["last_error"] = str(e)[:300]
                log.warning("%s history failed for %s: %s", src, step, str(e)[:300])
                if failing[src] >= MAX_CONSECUTIVE_ERRORS:
                    summary[src]["gave_up"] = True
            if pause:
                time.sleep(pause)

    if progress:
        progress({"done": len(plan), "total": len(plan), "source": None, "date": None})
    return {"start": start, "end": end, "steps": len(plan), "stopped": stopped, "sources": summary}


def catch_up(session: Session, today: date, max_days: int = 60, **kw) -> dict:
    """Fill trading days missing from the last `max_days` (e.g. the laptop was
    off), but not before the first day Kosh ever stored, so a fresh install
    doesn't silently download months of history."""
    first = session.scalar(select(func.min(Price.date)).where(Price.source == "nse"))
    if first is None:
        return {"steps": 0, "sources": {}}
    return backfill_history(session, max(first, today - timedelta(days=max_days)), today, **kw)


# ---------------------------------------------------------------- narrow, on-demand

def backfill_indices(session: Session, names: list[str], start: date, end: date) -> dict:
    """Fetch and store NSE index closes for `names` over [start, end] (inclusive),
    skipping trading days already cached for every name. Returns how many days
    were actually fetched over the network."""
    end = min(end, date.today())  # an event window can run past today; no files exist yet
    names = sorted(set(names))
    cached_days: set[date] = set()
    if names:
        rows = session.execute(
            select(IndexPrice.date, IndexPrice.name)
            .where(IndexPrice.name.in_(names), IndexPrice.date.between(start, end))
        ).all()
        by_day: dict[date, set[str]] = {}
        for d, n in rows:
            by_day.setdefault(d, set()).add(n)
        cached_days = {d for d, have in by_day.items() if have >= set(names)}

    fetched = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in cached_days:
            try:
                index_rows = nse.fetch_index_closes(d)
            except Exception as e:
                log.warning("index backfill failed for %s: %s", d, e)
                index_rows = []
            pick = [dict(name=r["name"], date=d, close=r["close"])
                    for r in index_rows if r["name"] in names]
            if pick:
                upsert_index_prices(session, pick)
                fetched += 1
        d += timedelta(days=1)
    return {"days_fetched": fetched}


def backfill_instrument_prices(session: Session, isin: str, start: date, end: date) -> dict:
    """Fetch historical AMFI NAVs for one instrument (e.g. the gold-ETF proxy
    used by impact/historical.py) over [start, end], skipping if already
    cached. AMFI publishes NAV history for every scheme it covers, including
    exchange-listed ETFs, so this works further back than NSE's per-stock
    bhavcopy archive."""
    end = min(end, date.today())
    existing = session.execute(
        select(Price.date).where(Price.isin == isin, Price.date.between(start, end))
    ).all()
    have = {d for (d,) in existing}
    # a handful of missing trading days is normal (holidays); only refetch
    # when the range looks genuinely unfetched
    if len(have) >= (end - start).days * 0.5:
        return {"days_fetched": 0}
    try:
        rows = amfi.fetch_history(start, end)
    except Exception as e:
        log.warning("instrument backfill failed for %s: %s", isin, e)
        return {"days_fetched": 0, "error": str(e)[:200]}
    pick = [dict(isin=isin, date=r.nav_date, price=r.nav, source="amfi", level="observed")
            for r in rows if isin in r.isins]
    if pick:
        upsert_prices(session, pick)
    return {"days_fetched": len(pick)}


# ---------------------------------------------------------------- what's stored

def coverage(session: Session) -> dict:
    """Row counts and date ranges of the market data held in the database."""
    from .. import config

    prices = []
    for src, rows, isins, days, lo, hi in session.execute(
        select(Price.source, func.count(), func.count(func.distinct(Price.isin)),
               func.count(func.distinct(Price.date)), func.min(Price.date), func.max(Price.date))
        .group_by(Price.source).order_by(func.count().desc())
    ):
        prices.append({"source": src, "rows": rows, "instruments": isins, "days": days, "from": lo, "to": hi})
    rows, names, days, lo, hi = session.execute(
        select(func.count(), func.count(func.distinct(IndexPrice.name)), func.count(func.distinct(IndexPrice.date)),
               func.min(IndexPrice.date), func.max(IndexPrice.date))
    ).one()
    ca_rows, ca_isins, ca_lo, ca_hi = session.execute(
        select(func.count(), func.count(func.distinct(CorporateAction.isin)),
               func.min(CorporateAction.ex_date), func.max(CorporateAction.ex_date))
    ).one()
    kinds = dict(session.execute(select(Instrument.kind, func.count()).group_by(Instrument.kind)).all())
    db_bytes = sum(p.stat().st_size for p in config.DB_PATH.parent.glob(config.DB_PATH.name + "*")
                   if p.is_file()) if config.DB_PATH.exists() else None
    return {
        "prices": prices,
        "indices": {"rows": rows, "indices": names, "days": days, "from": lo, "to": hi},
        "actions": {"rows": ca_rows, "instruments": ca_isins, "from": ca_lo, "to": ca_hi},
        "instruments": {"total": sum(kinds.values()), "by_kind": kinds},
        "db_path": str(config.DB_PATH),
        "db_bytes": db_bytes,
    }
