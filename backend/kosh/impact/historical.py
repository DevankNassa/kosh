"""Real, data-derived shocks: instead of a hand-typed guess at how much the
market moved, compute the actual NSE index move over a real date window and
turn it into the same shock shape `impact/shocks.py` already knows how to
apply (see impact/shocks.py's module docstring for the shock format).

Backed by IndexPrice (models.py), filled in by marketdata/refresh.py day by
day and backfilled on demand here for historical windows."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.classify import BROAD_MARKET_INDEX, DEBT_INDEX, SECTOR_INDEX
from ..marketdata.backfill import backfill_indices, backfill_instrument_prices
from ..models import IndexPrice, Instrument, Price
from .shocks import ShockLike


def index_return(session: Session, name: str, start: date, end: date) -> Optional[float]:
    """% change of index `name` between the first trading day on/after `start`
    and the last trading day on/before `end`. Backfills the range first if it
    isn't cached yet. None if there's no data in range."""
    backfill_indices(session, [name], start, end)
    session.flush()
    first = session.execute(
        select(IndexPrice.close, IndexPrice.date)
        .where(IndexPrice.name == name, IndexPrice.date >= start)
        .order_by(IndexPrice.date.asc()).limit(1)
    ).first()
    last = session.execute(
        select(IndexPrice.close, IndexPrice.date)
        .where(IndexPrice.name == name, IndexPrice.date <= end)
        .order_by(IndexPrice.date.desc()).limit(1)
    ).first()
    if not first or not last or first.date >= last.date:
        return None
    return (last.close - first.close) / first.close * 100


def real_shock(session: Session, sector: Optional[str], start: date, end: date) -> ShockLike:
    """The real shock that actually happened over [start, end]: a sector's
    real move plus the market's real move for everything else, or just the
    market-wide move if there's no sector (or no index for it)."""
    market_pct = index_return(session, BROAD_MARKET_INDEX, start, end)
    sector_index = SECTOR_INDEX.get(sector) if sector else None
    if sector_index:
        sector_pct = index_return(session, sector_index, start, end)
        if sector_pct is not None:
            shocks: list[dict] = [{"filter": {"sector": sector}, "equity_move_pct": round(sector_pct, 2)}]
            if market_pct is not None:
                shocks.append({"filter": {"not_sector": sector}, "equity_move_pct": round(market_pct, 2)})
            return shocks
    return {"equity_move_pct": round(market_pct, 2)} if market_pct is not None else {}


# ---------------------------------------------------------------- chart data

def _rebase(points: list[tuple[date, float]]) -> list[dict]:
    """Rebase a (date, value) series to 100 at its first point, so series on
    different scales (an index level, a NAV in rupees) can share one chart."""
    if not points:
        return []
    base = points[0][1]
    return [{"date": d, "value": round(v / base * 100, 2)} for d, v in points]


def _index_series(session: Session, name: str, start: date, end: date) -> list[dict]:
    backfill_indices(session, [name], start, end)
    rows = session.scalars(
        select(IndexPrice).where(IndexPrice.name == name, IndexPrice.date.between(start, end))
        .order_by(IndexPrice.date)
    )
    return _rebase([(r.date, r.close) for r in rows])


def _instrument_series(session: Session, isin: str, start: date, end: date) -> list[dict]:
    backfill_instrument_prices(session, isin, start, end)
    rows = session.scalars(
        select(Price).where(Price.isin == isin, Price.date.between(start, end)).order_by(Price.date)
    )
    return _rebase([(r.date, r.price) for r in rows])


def gold_proxy(session: Session) -> tuple[Optional[str], Optional[str]]:
    """A listed gold ETF already in the book, used as a free stand-in for the
    gold price — NSE doesn't publish a gold price index, but AMFI publishes
    NAV history for every scheme it covers, including listed ETFs."""
    row = session.execute(
        select(Instrument.isin, Instrument.name)
        .where(Instrument.asset_class == "gold", Instrument.kind == "etf")
        .order_by(Instrument.isin).limit(1)
    ).first()
    return (row.isin, row.name) if row else (None, None)


def family_series(session: Session, sector: Optional[str], start: date, end: date) -> list[dict]:
    """Debt, equity, gold, and (if the event is sector-tagged) that sector —
    rebased to 100, for the Scenarios chart. Fixed role order so the frontend
    can colour by role rather than position (color follows the entity, not
    where it happens to land in the list)."""
    out = []
    debt = _index_series(session, DEBT_INDEX, start, end)
    if debt:
        out.append({"role": "debt", "label": "Debt (10Y G-Sec)", "points": debt})
    equity = _index_series(session, BROAD_MARKET_INDEX, start, end)
    if equity:
        out.append({"role": "equity", "label": "Equity (Nifty 500)", "points": equity})
    gold_isin, gold_name = gold_proxy(session)
    if gold_isin:
        gold = _instrument_series(session, gold_isin, start, end)
        if gold:
            out.append({"role": "gold", "label": f"Gold ({gold_name})", "points": gold})
    sector_index = SECTOR_INDEX.get(sector) if sector else None
    if sector_index:
        sec = _index_series(session, sector_index, start, end)
        if sec:
            out.append({"role": "sector", "label": sector, "points": sec})
    return out


def sector_small_multiples(session: Session, start: date, end: date) -> dict:
    """Every tracked sector vs the broad market, for the "all sectors" chart
    mode — one small chart per sector rather than one busy 14-line chart."""
    market = _index_series(session, BROAD_MARKET_INDEX, start, end)
    sectors = []
    for sector, idx in sorted(SECTOR_INDEX.items()):
        pts = _index_series(session, idx, start, end)
        if pts:
            sectors.append({"role": "sector", "label": sector, "points": pts})
    return {"market": {"label": BROAD_MARKET_INDEX, "points": market}, "sectors": sectors}


@dataclass
class HistoricalEvent:
    id: str
    label: str
    start: date
    end: date
    sector: Optional[str] = None


# Curated real past events, chosen to fall within NSE's confirmed index-history
# window (2020+) so `real_shock` resolves to real numbers, not guesses. Each
# one models the real move in the relevant sector index (if tagged) plus the
# real broad-market move for the rest of the book.
HISTORICAL_EVENTS = [
    HistoricalEvent("covid-2020", "COVID-19 crash (Feb–Mar 2020)", date(2020, 2, 20), date(2020, 3, 23)),
    HistoricalEvent("ru-ua-2022", "Russia invades Ukraine (Feb 2022)", date(2022, 2, 21), date(2022, 3, 7)),
    HistoricalEvent("oil-spike-2022", "Oil & gas price spike after the Ukraine invasion (Mar 2022)",
                     date(2022, 2, 21), date(2022, 3, 14), "Oil Gas & Consumable Fuels"),
    HistoricalEvent("fed-hikes-2022", "Aggressive Fed rate-hike sell-off (Sep 2022)",
                     date(2022, 9, 1), date(2022, 9, 30)),
    HistoricalEvent("adani-2023", "Hindenburg report on Adani Group (Jan 2023)",
                     date(2023, 1, 24), date(2023, 2, 7)),
    HistoricalEvent("svb-2023", "Silicon Valley Bank collapse (Mar 2023)",
                     date(2023, 3, 8), date(2023, 3, 20), "Financial Services"),
    HistoricalEvent("it-guidance-2023", "IT sector guidance cuts (Apr 2023)",
                     date(2023, 4, 10), date(2023, 4, 21), "Information Technology"),
    HistoricalEvent("iran-israel-2024", "Iran–Israel strikes raise oil prices (Apr 2024)",
                     date(2024, 4, 1), date(2024, 4, 19), "Oil Gas & Consumable Fuels"),
    HistoricalEvent("iran-israel-2025", "Iran–Israel conflict and oil-price spike (Jun 2025)",
                     date(2025, 6, 10), date(2025, 6, 30), "Oil Gas & Consumable Fuels"),
]
