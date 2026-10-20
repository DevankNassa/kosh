from datetime import date

import pytest

from kosh.analytics.portfolio import Holding
from kosh.impact.historical import index_return, real_shock
from kosh.impact.shocks import holding_impact
from kosh.marketdata import refresh as refresh_mod
from kosh.models import Event, IndexPrice, Instrument


def _holding(isin, sector, value, asset_class="equity"):
    ins = Instrument(isin=isin, name=isin, kind="equity", asset_class=asset_class, sector=sector)
    return Holding(account=None, instrument=ins, lots=[], quote=None, asof=date.today(), value=value)


def test_single_dict_shock_still_works():
    h = _holding("INE000000001", None, 1000.0)
    imp, why = holding_impact(h, {"equity_move_pct": -10})
    assert imp == pytest.approx(-100.0)
    assert why


def test_sector_plus_market_shock_does_not_double_count():
    """A sector-filtered shock and a {"not_sector": ...} market-wide shock,
    combined in a list, must each apply to the right holdings only — a
    holding inside the sector should get only the sector's number, not
    sector + market summed together."""
    oil = _holding("INE000000002", "Oil Gas & Consumable Fuels", 1000.0)
    other = _holding("INE000000003", "Information Technology", 1000.0)
    shock = [
        {"filter": {"sector": "Oil Gas & Consumable Fuels"}, "equity_move_pct": 10},
        {"filter": {"not_sector": "Oil Gas & Consumable Fuels"}, "equity_move_pct": -5},
    ]
    oil_impact, _ = holding_impact(oil, shock)
    other_impact, _ = holding_impact(other, shock)
    assert oil_impact == pytest.approx(100.0)
    assert other_impact == pytest.approx(-50.0)


@pytest.fixture()
def no_network(monkeypatch):
    """real_shock/index_return self-backfill before reading; for these tests
    the endpoints are pre-seeded, so refuse any live NSE fetch and prove the
    logic works purely from what's already cached."""
    monkeypatch.setattr("kosh.marketdata.nse.fetch_index_closes", lambda d: [])


def test_index_return_from_cached_prices(session, no_network):
    session.add_all([
        IndexPrice(name="Nifty 500", date=date(2024, 1, 1), close=100.0),
        IndexPrice(name="Nifty 500", date=date(2024, 1, 31), close=110.0),
    ])
    session.flush()
    pct = index_return(session, "Nifty 500", date(2024, 1, 1), date(2024, 1, 31))
    assert pct == pytest.approx(10.0)


def test_index_return_missing_data_is_none(session, no_network):
    assert index_return(session, "Nifty 500", date(2024, 1, 1), date(2024, 1, 31)) is None


def test_real_shock_splits_sector_from_market(session, no_network):
    session.add_all([
        IndexPrice(name="Nifty 500", date=date(2024, 1, 1), close=100.0),
        IndexPrice(name="Nifty 500", date=date(2024, 1, 31), close=95.0),
        IndexPrice(name="Nifty IT", date=date(2024, 1, 1), close=100.0),
        IndexPrice(name="Nifty IT", date=date(2024, 1, 31), close=90.0),
    ])
    session.flush()
    shock = real_shock(session, "Information Technology", date(2024, 1, 1), date(2024, 1, 31))
    assert isinstance(shock, list) and len(shock) == 2
    sector_shock = next(s for s in shock if "sector" in s["filter"])
    market_shock = next(s for s in shock if "not_sector" in s["filter"])
    assert sector_shock["equity_move_pct"] == pytest.approx(-10.0)
    assert market_shock["equity_move_pct"] == pytest.approx(-5.0)


def test_real_shock_market_wide_when_no_sector(session, no_network):
    session.add_all([
        IndexPrice(name="Nifty 500", date=date(2024, 1, 1), close=100.0),
        IndexPrice(name="Nifty 500", date=date(2024, 1, 31), close=105.0),
    ])
    session.flush()
    shock = real_shock(session, None, date(2024, 1, 1), date(2024, 1, 31))
    assert shock == {"equity_move_pct": 5.0}


def test_true_up_events_fills_actual_tags(session, no_network):
    session.add_all([
        IndexPrice(name="Nifty 500", date=date(2024, 1, 2), close=100.0),
        IndexPrice(name="Nifty 500", date=date(2024, 1, 9), close=103.0),
    ])
    e = Event(date=date(2024, 1, 2), kind="market", title="Test event", tags={}, is_sample=False)
    session.add(e)
    session.flush()

    result = refresh_mod._true_up_events(session, date(2024, 1, 15))

    assert result["updated"] == 1
    assert e.actual_tags == {"equity_move_pct": 3.0}


def test_true_up_events_skips_recent_events(session, no_network):
    e = Event(date=date.today(), kind="market", title="Just logged", tags={}, is_sample=False)
    session.add(e)
    session.flush()

    result = refresh_mod._true_up_events(session, date.today())

    assert result["updated"] == 0
    assert e.actual_tags is None
