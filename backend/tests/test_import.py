"""Statement import mapping, using casparser's own data types."""

from datetime import date
from decimal import Decimal

from casparser.types import (CASData, DematAccount, DematOwner, Equity, Folio, InvestorInfo, NSDLCASData,
                             Scheme, SchemeValuation, StatementPeriod, TransactionData)

from kosh.analytics.portfolio import build_portfolio
from kosh.importer import cas
from kosh.models import Client, Instrument

INV = InvestorInfo(name="Test Investor", email="t@example.com", address="", mobile="")


def _cams():
    txns = [
        TransactionData(date=date(2024, 1, 10), description="Purchase", amount=Decimal("10000"),
                        units=Decimal("100"), nav=Decimal("100"), balance=Decimal("100"), type="PURCHASE"),
        TransactionData(date=date(2025, 1, 10), description="SIP", amount=Decimal("12000"),
                        units=Decimal("100"), nav=Decimal("120"), balance=Decimal("200"), type="PURCHASE_SIP"),
        TransactionData(date=date(2025, 1, 10), description="Stamp", amount=Decimal("0.6"),
                        units=None, nav=None, balance=None, type="STAMP_DUTY_TAX"),
        TransactionData(date=date(2026, 5, 10), description="Redemption", amount=Decimal("-6000"),
                        units=Decimal("-50"), nav=Decimal("120"), balance=Decimal("150"), type="REDEMPTION"),
    ]
    sc = Scheme(scheme="Test Flexi Cap Fund - Regular Growth", advisor="ARN-12345", rta_code="X1", rta="CAMS",
                type="EQUITY", isin="INF000TEST01", amfi="999999", open=Decimal("0"), close=Decimal("150"),
                close_calculated=Decimal("150"),
                valuation=SchemeValuation(date=date(2026, 9, 30), nav=Decimal("130"), value=Decimal("19500")),
                transactions=txns)
    return CASData(statement_period=StatementPeriod(**{"from": "01-Jan-1990", "to": "30-Sep-2026"}),
                   folios=[Folio(folio="123/45", amc="Test AMC", PAN="ABCDE1234F", schemes=[sc])],
                   investor_info=INV, cas_type="DETAILED", file_type="CAMS")


def _nsdl():
    acct = DematAccount(name="Sample DP", type="NSDL Demat Account", dp_id="IN300000", client_id="12345678",
                        folios=0, balance=Decimal("0"), owners=[DematOwner(name="Test Investor", PAN="ABCDE1234F")],
                        equities=[Equity(name="TEST LTD", isin="INE000T01011", num_shares=Decimal("10"),
                                         price=Decimal("500"), value=Decimal("5000"))],
                        mutual_funds=[])
    return NSDLCASData(accounts=[acct], statement_period=StatementPeriod(**{"from": "01-Sep-2026", "to": "30-Sep-2026"}),
                       investor_info=INV, file_type="NSDL")


def test_cams_detailed_import_roundtrip(session):
    payload = cas.normalise(_cams())
    assert payload["pans"] == ["ABCDE1234F"]
    acct = payload["accounts"][0]
    assert acct["arn"] == "ARN-12345"
    assert [t["type"] for t in acct["transactions"]] == ["BUY", "BUY", "SELL"]
    preview = cas.build_preview(session, payload, "x.pdf")
    assert session.get(Instrument, "INF000TEST01") is None  # preview leaves no trace
    assert preview["new_transactions"] == 3
    assert all(r["matches"] for r in preview["reconciliation"])
    res = cas.commit(session, preview["token"], None, {"name": "Test Investor"})
    assert res["added"] == 3
    client = session.get(Client, res["client_id"])
    assert client.pan == "ABCDE1234F"
    assert session.get(Instrument, "INF000TEST01") is not None
    p = build_portfolio(session, client)
    assert round(p.holdings[0].units, 3) == 150
    assert round(p.realised[0].gain, 2) == 1000.0  # 50 units: cost 100, sold 120

    # importing the same statement again adds nothing
    preview2 = cas.build_preview(session, cas.normalise(_cams()), "x.pdf")
    assert preview2["matched_client"]["id"] == client.id
    assert preview2["new_transactions"] == 0
    assert cas.commit(session, preview2["token"], client.id, None)["added"] == 0


def test_nsdl_holdings_have_unknown_cost(session):
    payload = cas.normalise(_nsdl())
    preview = cas.build_preview(session, payload, "n.pdf")
    assert preview["accounts"][0]["cost_unknown"] == 1
    res = cas.commit(session, preview["token"], None, None)
    p = build_portfolio(session, session.get(Client, res["client_id"]))
    h = p.holdings[0]
    assert h.unknown_units == 10 and h.value == 5000
