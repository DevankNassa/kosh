"""Restating stored closing prices for splits, bonus issues and consolidations.

Kosh stores actual NSE closing prices. A 1:1 bonus halves the price overnight
without anyone losing money, so before comparing prices across an ex-date,
earlier closes are multiplied by the action's factor (CorporateAction, from
NSE's corporate-actions list)."""

from datetime import date
from typing import Iterable, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import CorporateAction


def factors_for(session: Session, isins: Iterable[str], symbol: str | None = None,
                since: date | None = None) -> dict[str, list[tuple[date, float]]]:
    """{isin: [(ex_date, factor), ...]}; with `symbol`, actions filed under a
    previous ISIN of the same share are included under every given ISIN."""
    isins = list(isins)
    cond = CorporateAction.isin.in_(isins)
    if symbol:
        cond = or_(cond, CorporateAction.symbol == symbol)
    q = select(CorporateAction).where(cond)
    if since:
        q = q.where(CorporateAction.ex_date >= since)
    out: dict[str, list[tuple[date, float]]] = {}
    for a in session.scalars(q):
        for isin in (isins if symbol else [a.isin]):
            out.setdefault(isin, []).append((a.ex_date, a.factor))
    return out


def factor_between(actions: Sequence[tuple[date, float]], after: date, upto: date) -> float:
    """Combined factor of actions with after < ex_date <= upto."""
    f = 1.0
    for ex, k in actions:
        if after < ex <= upto:
            f *= k
    return f


def adjusted_closes(rows: Sequence, actions: Sequence[tuple[date, float]]) -> list[float]:
    """Each row's `.price` restated in today's terms: multiplied by every
    action with an ex-date after the row's `.date`."""
    return [r.price * factor_between(actions, r.date, date.max) for r in rows]
