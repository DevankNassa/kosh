"""With no internet, the bundled snapshot is enough to run the demo."""

from kosh.analytics.portfolio import build_portfolio
from kosh.demo.seed import seed_demo
from kosh.marketdata import amfi, nse, refresh
from kosh.models import Client


def _boom(*a, **k):
    raise OSError("offline")


def test_snapshot_fallback_runs_demo(session, monkeypatch):
    monkeypatch.setattr(amfi, "fetch_latest", _boom)
    monkeypatch.setattr(nse, "fetch_latest_bhavcopies", _boom)
    monkeypatch.setattr(nse, "fetch_sectors", lambda: {})
    st = refresh.refresh_market_data(session)
    assert st["snapshot"]["ok"]
    seed_demo(session)
    clients = session.query(Client).all()
    assert len(clients) == 8
    for c in clients:
        p = build_portfolio(session, c)
        assert p.value > 0
        assert all(h.quote is not None for h in p.holdings)
