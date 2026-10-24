"""Stored market history: backfill, resume, PriceBook on long history, auto-refresh timing."""

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from kosh.analytics.portfolio import PriceBook
from kosh.api.app import app
from kosh.marketdata import amfi, backfill, jobs, nse
from kosh.models import CorporateAction, IndexPrice, Instrument, Price

LEGACY = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
    "RELIANCE,EQ,2540,2560,2530,2550.5,2551,2541,100,255000,03-JAN-2023,50,INE002A01018,\n"
    "BADROW,EQ,1,1,1,,1,1,1,1,03-JAN-2023,1,INE000000000,\n"
)

ETF = "INF204KB14I2"  # an ETF: has both an NSE close and an AMFI NAV


def test_parse_legacy_bhavcopy():
    rows = nse.parse_legacy_bhavcopy(LEGACY)
    assert len(rows) == 1
    r = rows[0]
    assert (r.isin, r.symbol, r.close, r.trade_date) == ("INE002A01018", "RELIANCE", 2550.5, date(2023, 1, 3))


def _fake_sources(monkeypatch, calls):
    def bhav(d, client=None):
        calls["nse"] += 1
        if d == date(2026, 1, 26):  # a holiday: no file
            return None
        rows = [nse.BhavRow(f"INE{i:07d}01", f"S{i}", "EQ", f"Company {i}", 100 + i, None, 1, d) for i in range(600)]
        rows.append(nse.BhavRow(ETF, "GOLDBEES", "EQ", "Gold ETF", 70.0, None, 1, d))
        return rows

    def indices(d, client=None):
        calls["indices"] += 1
        return [{"name": f"Nifty {i}", "close": 1000.0 + i, "change_pct": 0.1} for i in range(30)]

    def history(start, end):
        calls["amfi"] += 1
        out, d = [], start
        while d <= end:
            if d.weekday() < 5 and d != date(2026, 1, 26):
                out += [amfi.NavRow(str(i), [f"INF{i:09d}"], f"Fund {i}", 10.0 + i, d,
                                    "Open Ended Schemes(Equity Scheme - Large Cap Fund)", "AMC", "Direct")
                        for i in range(2100)]
                out.append(amfi.NavRow("x", [ETF], "Gold ETF", 69.0, d, "Other Scheme - Gold ETF", "AMC", None))
            d += timedelta(days=1)
        return out

    monkeypatch.setattr(nse, "fetch_corporate_actions", lambda start, end: [
        {"isin": "INE000000101", "symbol": "S1", "ex_date": date(2026, 1, 22), "subject": "Bonus 1:1", "factor": 0.5}])
    monkeypatch.setattr(nse, "fetch_bhavcopy", bhav)
    monkeypatch.setattr(nse, "fetch_index_closes", indices)
    monkeypatch.setattr(amfi, "fetch_history", history)


def test_backfill_stores_and_resumes(session, monkeypatch):
    calls = {"nse": 0, "indices": 0, "amfi": 0}
    _fake_sources(monkeypatch, calls)
    start, end = date(2026, 1, 19), date(2026, 1, 30)  # two weeks, 10 weekdays, 1 holiday
    res = backfill.backfill_history(session, start, end, pause=0)
    assert res["sources"]["nse"]["fetched"] == 9
    assert res["sources"]["nse"]["no_data"] == 1
    assert calls["indices"] == 10
    assert session.query(IndexPrice).count() == 300
    assert session.query(CorporateAction).one().factor == 0.5

    # delisted / unknown securities still get an instrument row, not marked listed
    ins = session.get(Instrument, "INE000000501")
    assert ins.name == "Company 5" and ins.listed is False

    # the ETF keeps its NSE close; AMFI's NAV doesn't overwrite it
    p = session.get(Price, (ETF, date(2026, 1, 20)))
    assert (p.source, p.price) == ("nse", 70.0)

    # re-running skips everything already stored (only the NSE holiday is retried)
    calls.update(nse=0, indices=0, amfi=0)
    res = backfill.backfill_history(session, start, end, pause=0)
    assert calls == {"nse": 1, "indices": 0, "amfi": 0}


def test_backfill_gives_up_on_a_failing_source(session, monkeypatch):
    calls = {"nse": 0, "indices": 0, "amfi": 0}
    _fake_sources(monkeypatch, calls)

    def down(*a, **k):
        raise RuntimeError("AMFI returned a web page instead of NAV data")

    monkeypatch.setattr(amfi, "fetch_history", down)
    res = backfill.backfill_history(session, date(2025, 9, 1), date(2026, 1, 30), sources=["amfi"], pause=0)
    assert res["sources"]["amfi"]["errors"] == backfill.MAX_CONSECUTIVE_ERRORS
    assert res["sources"]["amfi"]["gave_up"]


def test_pricebook_uses_latest_two_of_long_history(session):
    session.add(Instrument(isin="INE002A01018", name="Reliance", kind="equity", asset_class="equity"))
    d0 = date(2026, 10, 20)
    session.add_all([Price(isin="INE002A01018", date=d0 - timedelta(days=i), price=100.0 + i,
                           source="nse", level="observed") for i in range(400)])
    session.commit()
    q = PriceBook(session, {"INE002A01018": session.get(Instrument, "INE002A01018")}).get("INE002A01018")
    assert (q.date, q.price, q.prev_date, q.prev_price) == (d0, 100.0, d0 - timedelta(days=1), 101.0)


def test_refresh_due():
    evening = datetime(2026, 10, 22, 20, 0)
    ok = {"nse": {"ok": True}, "amfi": {"ok": True}}
    assert jobs.refresh_due(None, evening)
    assert jobs.refresh_due({**ok, "finished": "2026-10-22T10:00:00"}, evening)  # before today's files
    assert not jobs.refresh_due({**ok, "finished": "2026-10-22T19:30:00"}, evening)
    # morning: yesterday evening's refresh still counts
    assert not jobs.refresh_due({**ok, "finished": "2026-10-21T19:30:00"}, datetime(2026, 10, 22, 9, 0))
    # a failed refresh (offline) is retried after an hour
    failed = {"nse": {"ok": False}, "amfi": {"ok": True}, "finished": "2026-10-22T19:05:00"}
    assert not jobs.refresh_due(failed, datetime(2026, 10, 22, 19, 30))
    assert jobs.refresh_due(failed, datetime(2026, 10, 22, 20, 30))


def test_market_data_and_price_history_api(session):
    session.add(Instrument(isin="INE002A01018", name="Reliance", symbol="RELIANCE", kind="equity",
                           asset_class="equity"))
    session.add_all([Price(isin="INE002A01018", date=date(2026, 10, 1) + timedelta(days=i), price=100.0 + i,
                           source="nse", level="observed") for i in range(5)])
    session.commit()
    client = TestClient(app)
    r = client.get("/api/market/data")
    assert r.status_code == 200, r.text
    nse_row = next(p for p in r.json()["prices"] if p["source"] == "nse")
    assert (nse_row["rows"], nse_row["days"], nse_row["from"]) == (5, 5, "2026-10-01")
    r = client.get("/api/instruments/INE002A01018/prices?days=2")
    assert [p["price"] for p in r.json()["points"]] == [102.0, 103.0, 104.0]
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3")


def test_split_and_bonus_are_adjusted_not_a_crash(session):
    """Real cases from Oct 2024: Reliance 1:1 bonus (same ISIN) and Dr Reddy's
    5→1 split (new ISIN). History is restated; day change is the real move."""
    from kosh import settings_store
    from kosh.marketdata.nse import price_factor

    rel, old_drl, new_drl = "INE002A01018", "INE089A01023", "INE089A01031"
    session.add_all([
        Instrument(isin=rel, name="Reliance", symbol="RELIANCE", kind="equity", asset_class="equity"),
        Instrument(isin=old_drl, name="Dr Reddy", symbol="DRREDDY", kind="equity", asset_class="equity", listed=False),
        Instrument(isin=new_drl, name="Dr Reddy", symbol="DRREDDY", kind="equity", asset_class="equity"),
        CorporateAction(isin=rel, symbol="RELIANCE", ex_date=date(2024, 10, 28), subject="Bonus 1:1",
                        factor=price_factor("Bonus 1:1")),
        CorporateAction(isin=old_drl, symbol="DRREDDY", ex_date=date(2024, 10, 28),
                        subject="Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share",
                        factor=0.2),
    ])
    for isin, d, px in [(rel, date(2024, 10, 25), 2655.7), (rel, date(2024, 10, 28), 1334.35),
                        (old_drl, date(2024, 10, 25), 6450.0), (new_drl, date(2024, 10, 28), 1290.0),
                        (new_drl, date(2024, 10, 29), 1300.0)]:
        session.add(Price(isin=isin, date=d, price=px, source="nse", level="observed"))
    settings_store.put(session, "market_status", {"nse": {"asof": "2024-10-28"}})
    session.commit()

    # day change on the ex-date compares with the restated previous close
    q = PriceBook(session, {rel: session.get(Instrument, rel)}).get(rel)
    assert q.prev_price == 2655.7 * 0.5

    client = TestClient(app)
    body = client.get(f"/api/instruments/{rel}/prices").json()
    assert body["adjusted"] and [p["price"] for p in body["points"]] == [1327.85, 1334.35]
    assert body["points"][0]["close"] == 2655.7

    body = client.get(f"/api/instruments/{new_drl}/prices").json()
    assert [(p["date"], p["price"]) for p in body["points"]] == [
        ("2024-10-25", 1290.0), ("2024-10-28", 1290.0), ("2024-10-29", 1300.0)]


def test_catch_up_fills_gaps_since_first_stored_day(session, monkeypatch):
    calls = {"nse": 0, "indices": 0, "amfi": 0}
    _fake_sources(monkeypatch, calls)
    assert backfill.catch_up(session, date(2026, 1, 30), pause=0)["steps"] == 0  # nothing stored yet
    # the daily refresh stored 19 and 30 Jan; the days between are missing
    for d in (date(2026, 1, 19), date(2026, 1, 30)):
        session.add_all([Price(isin=f"INE{i:07d}01", date=d, price=1.0, source="nse", level="observed")
                         for i in range(600)])
    session.commit()
    res = backfill.catch_up(session, date(2026, 1, 30), sources=["nse"], pause=0)
    assert res["start"] == date(2026, 1, 19)
    assert calls["nse"] == 8  # 20–29 Jan weekdays (incl. the 26th, a holiday)
