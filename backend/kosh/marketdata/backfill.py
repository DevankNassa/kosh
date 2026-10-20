"""Backfill historical NSE index closes into IndexPrice, for real-data
scenarios and the market/event chart (see impact/historical.py). Separate
from the daily refresh.py loop: this fetches one day's archive per missing
trading day over an arbitrary past range."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IndexPrice, Price
from . import amfi, nse
from .refresh import upsert_index_prices, upsert_prices

log = logging.getLogger(__name__)


def backfill_indices(session: Session, names: list[str], start: date, end: date) -> dict:
    """Fetch and store NSE index closes for `names` over [start, end] (inclusive),
    skipping trading days already cached for every name. Returns how many days
    were actually fetched over the network."""
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
