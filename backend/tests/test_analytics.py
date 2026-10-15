from datetime import date

import pytest

from kosh.analytics.bonds import BondTerms, clean_price, risk, ytm, price_change_pct
from kosh.analytics.classify import (bond_terms_from_name, classify_exchange, classify_mf,
                                     maturity_from_symbol, rating_bucket)
from kosh.analytics.portfolio import TxnIn, run_fifo
from kosh.analytics.xirr import xirr


def test_price_yield_roundtrip_and_par():
    b = BondTerms(0.07, date(2036, 10, 15), 2)
    settle = date(2026, 10, 15)
    assert clean_price(b, 0.07, settle) == pytest.approx(100, abs=0.05)
    assert ytm(b, 95.0, settle) == pytest.approx(0.0773, abs=0.001)


def test_duration_sensible():
    b = BondTerms(0.0718, date(2037, 6, 30), 2)
    d, c = risk(b, 0.07, date(2026, 10, 15))
    assert 6.5 < d < 8.0 and c > 0
    assert price_change_pct(d, c, 0.01) < 0


def test_xirr_simple():
    r = xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 110)])
    assert r == pytest.approx(0.10, abs=1e-4)


def test_fifo_matches_oldest_first():
    t = [
        TxnIn(1, 1, "X", date(2020, 1, 1), "BUY", 10, 100, None),
        TxnIn(2, 1, "X", date(2021, 1, 1), "BUY", 10, 150, None),
        TxnIn(3, 1, "X", date(2022, 1, 1), "SELL", 15, 200, None),
    ]
    open_lots, realised, warns = run_fifo(t)
    assert [round(r.units) for r in realised] == [10, 5]
    assert realised[0].gain == pytest.approx(1000)
    assert realised[1].gain == pytest.approx(250)
    assert open_lots[(1, "X")][0].units == pytest.approx(5)
    assert not warns


def test_fifo_oversell_warns():
    t = [TxnIn(1, 1, "X", date(2020, 1, 1), "BUY", 1, 10, None),
         TxnIn(2, 1, "X", date(2020, 2, 1), "SELL", 2, 10, None)]
    assert run_fifo(t)[2]


def test_unknown_cost_lot_excluded_from_gain():
    t = [TxnIn(1, 1, "X", date(2020, 1, 1), "OPENING", 5, None, None, True),
         TxnIn(2, 1, "X", date(2026, 1, 1), "SELL", 5, 10, None)]
    _, realised, _ = run_fifo(t)
    assert realised[0].gain is None


def test_classify_mf_categories():
    assert classify_mf("Open Ended Schemes(Debt Scheme - Liquid Fund)", "X Liquid").tax_class == "specified_debt"
    eq = classify_mf("Open Ended Schemes(Equity Scheme - Large Cap Fund)", "X Bluechip")
    assert (eq.asset_class, eq.tax_class) == ("equity", "equity")
    arb = classify_mf("Open Ended Schemes(Hybrid Scheme - Arbitrage Fund)", "X Arbitrage")
    assert arb.tax_class == "equity" and arb.asset_class == "hybrid"
    gold = classify_mf("Open Ended Schemes(Other Scheme - Gold ETF)", "X Gold ETF")
    assert gold.asset_class == "gold"
    idx = classify_mf("Open Ended Schemes(Other Scheme - Index Funds)", "X Nifty SDL Apr 2027 Index Fund")
    assert idx.asset_class == "debt"


def test_exchange_rows():
    assert classify_exchange("IN0020230077", "GS", "GOI LOAN  7.18% 2037")["kind"] == "gsec"
    nc = classify_exchange("INE053F07579", "N4", "7.34 NCD 19FEB28 TR1 SR2")
    assert nc["kind"] == "corp_bond" and nc["maturity"] == date(2028, 2, 19) and nc["coupon"] == 0.0734
    tf = classify_exchange("INE906B07DF8", "N6", "8.75% TAX FREE TR I S IIB", "875NHAI29")
    assert tf["tax_free_interest"] and tf["maturity"].year == 2029


def test_name_parsing():
    assert bond_terms_from_name("8.20 NCD05MAR27 FV 1000")["maturity"] == date(2027, 3, 5)
    assert bond_terms_from_name("2.5%GOLDBONDS2029SR-I")["maturity"].year == 2029
    assert maturity_from_symbol("930IIFL27") == date(2027, 6, 30)
    assert rating_bucket("CRISIL AA+") == "AA" and rating_bucket("SOV") == "Sovereign"
