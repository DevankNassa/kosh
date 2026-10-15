"""Demo book: eight fictional clients holding real instruments.

Instruments and current prices are real (AMFI / NSE). Client names,
holdings and purchase prices are made up: purchase prices are generated
from today's price along a smooth, deterministic path. Everything created
here is flagged `is_demo` / `is_sample` and can be removed from Settings."""

import hashlib
import math
from datetime import date, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import settings_store
from ..analytics.portfolio import PriceBook, instruments_for
from ..models import Account, Client, Event, Instrument, Transaction, audit
from ..tax.rules import fy_bounds

# ---------------------------------------------------------------- instruments

MF = {
    "PPFAS": "INF879O01019",       # Parag Parikh Flexi Cap - Regular - Growth
    "HDFC_FLEXI": "INF179K01608",
    "ICICI_LARGE": "INF109K01BL4",
    "SBI_SMALL": "INF200K01T28",
    "NIPPON_SMALL": "INF204K01HY3",
    "KOTAK_MID": "INF174K01DS9",
    "AXIS_ELSS": "INF846K01131",
    "MIRAE_LMC": "INF769K01101",
    "HDFC_BAF": "INF179K01830",
    "KOTAK_ARB": "INF174K01302",
    "HDFC_CORP": "INF179K01DC2",
    "ICICI_ST": "INF109K01654",
    "SBI_GILT": "INF200K01AH1",
    "ABSL_LIQ": "INF209K01RU9",
    "ICICI_MAA": "INF109K01761",
}
EQ = {
    "RELIANCE": "INE002A01018", "HDFCBANK": "INE040A01034", "ICICIBANK": "INE090A01021",
    "INFY": "INE009A01021", "TCS": "INE467B01029", "ITC": "INE154A01025", "LT": "INE018A01030",
    "SBIN": "INE062A01020", "BHARTIARTL": "INE397D01024", "HINDUNILVR": "INE030A01027",
    "ASIANPAINT": "INE021A01026", "IRFC": "INE053F01010", "PFC": "INE134E01011",
    "RECLTD": "INE020B01018", "BAJFINANCE": "INE296A01032",
    "NIFTYBEES": "INF204KB14I2", "GOLDBEES": "INF204KB17I5",
}
BONDS = {
    "SGB29": "IN0020210053",
    "GS2037": "IN0020230077",
    "IRFC28": "INE053F07579",
    "NHAI29TF": "INE906B07DF8",
    "REC27TF": "INE020B07GH7",
    "HUDCO27": "INE031A07840",
    "ABCL33": "INE860H07IS6",
    "IIFL27": "INE530B07534",
}
# Bond attributes entered for the demo (ratings are as entered by the user;
# Kosh has no ratings feed yet).
BOND_META = {
    "IRFC28": dict(face_value=1000.0, rating="AAA", issuer="Indian Railway Finance Corp"),
    "NHAI29TF": dict(face_value=1000.0, rating="AAA", issuer="National Highways Authority of India"),
    "REC27TF": dict(face_value=1000.0, rating="AAA", issuer="REC Ltd"),
    "HUDCO27": dict(face_value=1000.0, rating="AAA", issuer="HUDCO"),
    "ABCL33": dict(face_value=1000.0, rating="AAA", issuer="Aditya Birla Capital"),
    "IIFL27": dict(face_value=1000.0, rating="AA", issuer="IIFL Finance"),
    "GS2037": dict(issuer="Government of India"),
    "SGB29": dict(face_value=None, issuer="Government of India (RBI)"),
}
# Created if the exchange did not list it today (no recent trade → model price)
FALLBACK_INSTRUMENTS = {
    "INE530B07534": dict(name="IIFL 9.30% NCD 2027 TR I SR III", kind="corp_bond", asset_class="debt",
                         sub_class="Corporate bond", tax_class="listed_other", coupon=0.093,
                         coupon_freq=1, maturity=date(2027, 6, 30), maturity_is_estimate=True,
                         symbol="930IIFL27", listed=True),
}

GROWTH = {  # (annual growth, wiggle amplitude) used to back-fill purchase prices
    "equity": (0.13, 0.10), "small": (0.17, 0.14), "mid": (0.15, 0.12), "debt": (0.07, 0.01),
    "liquid": (0.066, 0.002), "gilt": (0.075, 0.025), "hybrid": (0.10, 0.05), "arb": (0.068, 0.004),
    "gold": (0.14, 0.06), "bond": (0.0, 0.015),
}


def _profile(ins: Instrument) -> str:
    s = (ins.sub_class or "").lower()
    if ins.kind in ("corp_bond", "gsec", "sdl"):
        return "bond"
    if ins.asset_class == "gold":
        return "gold"
    if "small" in s:
        return "small"
    if "mid" in s and "large" not in s:
        return "mid"
    if "liquid" in s or "overnight" in s:
        return "liquid"
    if "gilt" in s:
        return "gilt"
    if "arbitrage" in s:
        return "arb"
    if ins.asset_class == "debt":
        return "debt"
    if ins.asset_class == "hybrid":
        return "hybrid"
    return "equity"


def _phase(isin: str) -> float:
    return int(hashlib.md5(isin.encode()).hexdigest()[:6], 16) / 0xFFFFFF * 2 * math.pi


def past_price(ins: Instrument, current: float, on: date, today: date) -> float:
    g, amp = GROWTH[_profile(ins)]
    t = max(0.0, (today - on).days / 365.25)
    ph = _phase(ins.isin)
    wiggle = 1 + amp * math.sin(2 * math.pi * t / 2.7 + ph) - amp * math.sin(ph)
    return current / (1 + g) ** t * wiggle


# ---------------------------------------------------------------- clients

def _months(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d = d + relativedelta(months=1)


class _Builder:
    def __init__(self, session: Session, today: date, book: PriceBook, arn: str):
        self.s, self.today, self.book, self.arn = session, today, book, arn
        self.client: Optional[Client] = None
        self.accounts: dict[str, Account] = {}
        self.seq = 0

    def client_(self, **kw) -> "_Builder":
        self.client = Client(is_demo=True, **kw)
        self.s.add(self.client)
        self.s.flush()
        self.accounts = {}
        return self

    def account(self, key: str, kind: str, identifier: str, provider: str, arn: Optional[str] = None):
        a = Account(client_id=self.client.id, kind=kind, identifier=identifier, provider=provider,
                    depository="DEMO", arn=arn)
        self.s.add(a)
        self.s.flush()
        self.accounts[key] = a
        return a

    def _px(self, isin: str, on: date, mult: Optional[float]) -> float:
        q = self.book.get(isin)
        ins = self.book.instruments[isin]
        cur = q.price if q else 100.0
        if mult is not None:
            return cur * mult
        return past_price(ins, cur, on, self.today)

    def _add(self, acct: str, isin: str, on: date, ttype: str, units: float, price: Optional[float],
             estimate: bool = False, desc: str = ""):
        self.seq += 1
        self.s.add(Transaction(
            account_id=self.accounts[acct].id, isin=isin, trade_date=on, type=ttype, units=round(units, 4),
            price=round(price, 4) if price is not None else None,
            amount=round(units * price, 2) if price is not None else None,
            date_is_estimate=estimate, description=desc, source="demo",
            dedupe_key=f"demo-{self.client.id}-{self.seq}",
        ))

    def buy(self, acct: str, isin: str, on: date, amount: float = 0, units: float = 0,
            mult: Optional[float] = None, desc: str = "Purchase"):
        px = self._px(isin, on, mult)
        u = units or amount / px
        self._add(acct, isin, on, "BUY", u, px, desc=desc)

    def sip(self, acct: str, isin: str, start: date, amount: float, end: Optional[date] = None):
        for d in _months(start, end or self.today):
            self.buy(acct, isin, d, amount=amount, desc="SIP")

    def sell(self, acct: str, isin: str, on: date, amount: float = 0, units: float = 0,
             mult: Optional[float] = None):
        px = self._px(isin, on, mult)
        u = units or amount / px
        self._add(acct, isin, on, "SELL", u, px, desc="Redemption / sale")

    def opening(self, acct: str, isin: str, units: float):
        """Holding imported from a depository statement with no cost basis."""
        self._add(acct, isin, self.today - timedelta(days=20), "OPENING", units, None, estimate=True,
                  desc="Holding from depository statement (cost unknown)")


def _ensure_instruments(session: Session) -> None:
    for isin, fields in FALLBACK_INSTRUMENTS.items():
        if session.get(Instrument, isin) is None:
            session.add(Instrument(isin=isin, **fields))
    session.flush()
    for key, meta in BOND_META.items():
        ins = session.get(Instrument, BONDS[key])
        if ins is None:
            continue
        for k, v in meta.items():
            if v is not None and getattr(ins, k) in (None, ""):
                setattr(ins, k, v)
    session.flush()


def seed_demo(session: Session, today: Optional[date] = None) -> dict:
    from ..analytics.portfolio import market_asof

    today = today or market_asof(session)
    _ensure_instruments(session)
    all_isins = list(MF.values()) + list(EQ.values()) + list(BONDS.values())
    instruments = instruments_for(session, all_isins)
    missing = [i for i in all_isins if i not in instruments]
    if missing:
        raise RuntimeError(f"Market data missing for demo instruments: {missing}. Run a market data refresh.")
    book = PriceBook(session, instruments)
    arn = settings_store.get(session, "arn")
    b = _Builder(session, today, book, arn)
    fy_start, _ = fy_bounds(today)

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    def in_fy(days_ago: int) -> date:
        return max(fy_start + timedelta(days=5), ago(days_ago))

    # 1. Retired, conservative, debt-heavy
    b.client_(name="Anil Mehta", residency="resident", tax_regime="old", slab_rate=0.30,
              risk_profile="Conservative", family="Mehta", notes="Retired. Prefers regular income.",
              target_allocation={"equity": 0.25, "debt": 0.55, "hybrid": 0.10, "gold": 0.10})
    b.account("demat", "demat", "1208160000123456", "Sample Securities Pvt Ltd (CDSL)")
    b.account("hdfc", "mf_folio", "11223344/55", "HDFC Mutual Fund", arn)
    b.account("icici", "mf_folio", "8899001/12", "ICICI Prudential Mutual Fund", arn)
    b.account("absl", "mf_folio", "1045566778", "Aditya Birla Sun Life Mutual Fund", arn)
    b.buy("demat", BONDS["GS2037"], date(2023, 8, 10), units=3000)
    b.buy("demat", BONDS["NHAI29TF"], date(2019, 3, 15), units=500)
    b.buy("demat", BONDS["REC27TF"], date(2018, 11, 20), units=300)
    b.buy("demat", BONDS["SGB29"], date(2021, 5, 20), units=40)
    b.buy("hdfc", MF["HDFC_CORP"], date(2022, 6, 10), amount=800_000)
    b.buy("hdfc", MF["HDFC_CORP"], date(2024, 2, 12), amount=400_000)
    b.buy("hdfc", MF["HDFC_BAF"], date(2021, 9, 1), amount=600_000)
    b.sip("icici", MF["ICICI_LARGE"], date(2020, 1, 5), 15_000)
    b.buy("absl", MF["ABSL_LIQ"], ago(100), amount=500_000)
    b.sell("hdfc", MF["HDFC_CORP"], in_fy(120), amount=150_000)

    # 2. Young IT professional, aggressive; has employer shares
    b.client_(name="Priya Sharma", residency="resident", tax_regime="new", slab_rate=0.30,
              surcharge_rate=0.10, risk_profile="Aggressive", notes="Receives Infosys stock as part of pay.",
              target_allocation={"equity": 0.80, "debt": 0.10, "hybrid": 0.05, "gold": 0.05})
    b.account("demat", "demat", "IN30012345678901", "Sample Broking Ltd (NSDL)")
    b.account("ppfas", "mf_folio", "PP-4455667", "PPFAS Mutual Fund", arn)
    b.account("sbi", "mf_folio", "20987654", "SBI Mutual Fund", arn)
    b.account("kotak", "mf_folio", "7766554", "Kotak Mahindra Mutual Fund", arn)
    b.account("axis", "mf_folio", "910203040", "Axis Mutual Fund", arn)
    b.account("absl", "mf_folio", "1045599887", "Aditya Birla Sun Life Mutual Fund", arn)
    b.sip("ppfas", MF["PPFAS"], date(2021, 4, 10), 25_000)
    b.sip("sbi", MF["SBI_SMALL"], date(2023, 6, 10), 10_000)
    b.sip("kotak", MF["KOTAK_MID"], date(2024, 1, 10), 10_000)
    b.sip("axis", MF["AXIS_ELSS"], date(2019, 4, 10), 12_500, end=date(2023, 3, 10))
    b.buy("demat", EQ["INFY"], date(2022, 7, 1), units=400)
    b.buy("demat", EQ["INFY"], today - relativedelta(months=11) - timedelta(days=12), units=200, mult=0.92)
    b.buy("demat", EQ["TCS"], today - relativedelta(months=10) - timedelta(days=20), units=100, mult=0.95)
    b.buy("demat", EQ["NIFTYBEES"], date(2024, 3, 1), units=1500)
    b.buy("absl", MF["ABSL_LIQ"], date(2026, 3, 1), amount=300_000)
    b.sell("ppfas", MF["PPFAS"], in_fy(150), amount=200_000)

    # 3. Business owner, direct equity and NBFC bonds
    b.client_(name="Vikram Rao", residency="resident", tax_regime="new", slab_rate=0.30,
              surcharge_rate=0.15, risk_profile="Growth", family="Rao",
              notes="Holds a concentrated direct-equity book.",
              target_allocation={"equity": 0.65, "debt": 0.20, "hybrid": 0.10, "gold": 0.05})
    b.account("demat", "demat", "IN30098765432109", "Sample Broking Ltd (NSDL)")
    b.account("hdfc", "mf_folio", "11998877/01", "HDFC Mutual Fund", arn)
    for sym, d, u in (("RELIANCE", date(2019, 5, 10), 800), ("HDFCBANK", date(2020, 3, 25), 1200),
                      ("ICICIBANK", date(2021, 2, 1), 1500), ("LT", date(2023, 1, 15), 300),
                      ("SBIN", date(2022, 9, 1), 2000), ("ITC", date(2017, 12, 12), 3000),
                      ("BHARTIARTL", date(2024, 8, 1), 500)):
        b.buy("demat", EQ[sym], d, units=u)
    b.buy("demat", EQ["BAJFINANCE"], ago(30), units=400, mult=1.04)
    b.buy("demat", EQ["ASIANPAINT"], date(2024, 9, 2), units=300, mult=1.25)
    b.sell("demat", EQ["ASIANPAINT"], in_fy(120), units=300, mult=0.98)
    b.sell("demat", EQ["ITC"], in_fy(60), units=1000)
    b.buy("demat", BONDS["IIFL27"], date(2024, 5, 20), units=1000)
    b.buy("demat", BONDS["ABCL33"], date(2023, 10, 1), units=500)
    b.buy("demat", BONDS["HUDCO27"], date(2022, 3, 1), units=400)
    b.buy("hdfc", MF["HDFC_BAF"], date(2022, 1, 3), amount=1_500_000)

    # 4. Senior citizen, moderate, gold-heavy
    b.client_(name="Sunita Iyer", residency="resident", tax_regime="new", slab_rate=0.20,
              risk_profile="Moderate", notes="Needs liquidity for family expenses.",
              target_allocation={"equity": 0.30, "debt": 0.45, "hybrid": 0.10, "gold": 0.15})
    b.account("demat", "demat", "1208160000654321", "Sample Securities Pvt Ltd (CDSL)")
    b.account("icici", "mf_folio", "8800112/34", "ICICI Prudential Mutual Fund", arn)
    b.account("sbi", "mf_folio", "20123456", "SBI Mutual Fund", arn)
    b.account("mirae", "mf_folio", "79912345", "Mirae Asset Mutual Fund", arn)
    b.buy("demat", BONDS["SGB29"], date(2021, 5, 20), units=60)
    b.buy("demat", EQ["GOLDBEES"], date(2023, 4, 10), units=3000)
    b.buy("demat", BONDS["IRFC28"], date(2022, 2, 1), units=600)
    b.buy("icici", MF["ICICI_ST"], date(2021, 11, 1), amount=1_000_000)
    b.buy("icici", MF["ICICI_MAA"], date(2022, 8, 1), amount=600_000)
    b.buy("sbi", MF["SBI_GILT"], date(2024, 6, 3), amount=500_000)
    b.sip("mirae", MF["MIRAE_LMC"], date(2020, 6, 5), 10_000)

    # 5. Early-career investor with a recent loss
    b.client_(name="Kunal Shah", residency="resident", tax_regime="new", slab_rate=0.20,
              risk_profile="Aggressive", target_allocation={"equity": 0.85, "hybrid": 0.05, "debt": 0.10})
    b.account("demat", "demat", "1208160000777888", "Sample Securities Pvt Ltd (CDSL)")
    b.account("nippon", "mf_folio", "4012345678", "Nippon India Mutual Fund", arn)
    b.account("kotak", "mf_folio", "7700112", "Kotak Mahindra Mutual Fund", arn)
    b.account("ppfas", "mf_folio", "PP-9988776", "PPFAS Mutual Fund", arn)
    b.account("hdfc", "mf_folio", "11554433/09", "HDFC Mutual Fund", arn)
    for d in _months(date(2023, 1, 15), today):
        b.buy("demat", EQ["NIFTYBEES"], d, amount=8_000, desc="Monthly ETF purchase")
    b.buy("nippon", MF["NIPPON_SMALL"], ago(300), amount=300_000, mult=1.16)
    b.buy("kotak", MF["KOTAK_ARB"], date(2025, 10, 1), amount=200_000)
    b.sip("ppfas", MF["PPFAS"], date(2024, 4, 10), 5_000)
    b.buy("hdfc", MF["HDFC_FLEXI"], ago(330), amount=100_000, mult=0.93)
    b.sell("hdfc", MF["HDFC_FLEXI"], in_fy(75), amount=60_000, mult=0.99)

    # 6. Doctor; PSU financier stocks and bonds from the same issuers
    b.client_(name="Meera Nair", residency="resident", tax_regime="old", slab_rate=0.30,
              surcharge_rate=0.10, risk_profile="Moderately aggressive", family="Nair",
              target_allocation={"equity": 0.55, "debt": 0.35, "gold": 0.10})
    b.account("demat", "demat", "IN30011223344556", "Sample Broking Ltd (NSDL)")
    b.account("mirae", "mf_folio", "79955511", "Mirae Asset Mutual Fund", arn)
    b.account("hdfc", "mf_folio", "11001122/77", "HDFC Mutual Fund", arn)
    b.account("sbi", "mf_folio", "20765432", "SBI Mutual Fund", arn)
    b.buy("mirae", MF["MIRAE_LMC"], date(2020, 10, 1), amount=1_000_000)
    b.sip("hdfc", MF["HDFC_FLEXI"], date(2022, 1, 7), 20_000)
    b.buy("hdfc", MF["HDFC_CORP"], date(2023, 9, 1), amount=1_200_000)
    b.buy("sbi", MF["SBI_GILT"], date(2025, 2, 3), amount=600_000)
    b.buy("demat", EQ["PFC"], date(2023, 6, 1), units=2000)
    b.buy("demat", EQ["RECLTD"], date(2023, 6, 1), units=1500)
    b.buy("demat", EQ["IRFC"], date(2023, 10, 3), units=10000)
    b.buy("demat", BONDS["IRFC28"], date(2023, 3, 1), units=300)
    b.buy("demat", BONDS["ABCL33"], date(2024, 1, 10), units=200)

    # 7. NRI client
    b.client_(name="Arjun Kapoor", residency="nri", tax_regime="new", slab_rate=0.30,
              risk_profile="Growth", notes="Lives in Dubai. NRI: TDS applies on redemptions.",
              target_allocation={"equity": 0.70, "debt": 0.30})
    b.account("ppfas", "mf_folio", "PP-1122334", "PPFAS Mutual Fund", arn)
    b.account("icici", "mf_folio", "8811223/44", "ICICI Prudential Mutual Fund", arn)
    b.buy("ppfas", MF["PPFAS"], date(2022, 5, 2), amount=1_500_000)
    b.buy("icici", MF["ICICI_LARGE"], date(2023, 7, 3), amount=800_000)
    b.buy("icici", MF["ICICI_ST"], date(2024, 2, 1), amount=500_000)

    # 8. Mid-career; a demat account whose cost basis is not yet entered
    b.client_(name="Farhan Qureshi", residency="resident", tax_regime="new", slab_rate=0.30,
              risk_profile="Moderate", notes="Demat holdings imported from statement; costs pending.",
              target_allocation={"equity": 0.60, "debt": 0.25, "hybrid": 0.05, "gold": 0.10})
    b.account("demat", "demat", "1208160000999000", "Sample Securities Pvt Ltd (CDSL)")
    b.account("hdfc", "mf_folio", "11667788/03", "HDFC Mutual Fund", arn)
    b.account("icici", "mf_folio", "8833445/66", "ICICI Prudential Mutual Fund", arn)
    b.account("absl", "mf_folio", "1045500112", "Aditya Birla Sun Life Mutual Fund", arn)
    b.buy("hdfc", MF["HDFC_FLEXI"], date(2021, 3, 1), amount=600_000)
    b.buy("hdfc", MF["HDFC_BAF"], date(2024, 11, 4), amount=400_000)
    b.sip("icici", MF["ICICI_LARGE"], date(2023, 4, 5), 10_000)
    b.buy("absl", MF["ABSL_LIQ"], ago(30), amount=200_000)
    b.buy("demat", EQ["GOLDBEES"], date(2025, 4, 1), units=1000)
    b.opening("demat", EQ["HINDUNILVR"], 300)
    b.opening("demat", EQ["ASIANPAINT"], 200)
    b.opening("demat", EQ["RELIANCE"], 300)

    events = seed_events(session, today)
    audit(session, "seed_demo", None, clients=8, events=events)
    session.flush()
    return {"clients": 8, "events": events}


SAMPLE_EVENTS = [
    ("rate", "What if: RBI cuts the repo rate by 25 bps",
     "Hypothetical policy move. Assumes G-sec yields fall 25 bps across the curve; bond and debt fund "
     "prices rise roughly by duration × 0.25%.",
     {"yield_shift_bps": -25}),
    ("rate", "What if: G-sec yields rise 50 bps",
     "Hypothetical sell-off in government bonds, e.g. after a fiscal slippage or a global rate shock.",
     {"yield_shift_bps": 50}),
    ("rating", "What if: spreads on AA and A rated bonds widen 100 bps",
     "Hypothetical credit stress in lower-rated corporate and NBFC bonds. Only directly held "
     "bonds are measured; debt fund look-through is not yet available.",
     {"spread_bps": 100, "rating_buckets": ["AA", "A", "BBB", "Below BBB"]}),
    ("sector", "What if: PSU financiers (PFC, REC, IRFC) re-rate 10% lower",
     "Hypothetical. Touches both the shares and the bonds of the same issuers: Kosh links them by "
     "the issuer code inside the ISIN.",
     {"filter": {"issuer_keys": ["INE134E", "INE020B", "INE053F"]}, "equity_move_pct": -10,
      "spread_bps": 25}),
    ("sector", "What if: Financial Services stocks fall 5%",
     "Hypothetical sector move applied to directly held bank and NBFC shares.",
     {"filter": {"sector": "Financial Services"}, "equity_move_pct": -5}),
    ("sector", "What if: IT stocks rise 4% on a weaker rupee",
     "Hypothetical sector move applied to directly held IT shares.",
     {"filter": {"sector": "Information Technology"}, "equity_move_pct": 4}),
    ("market", "What if: Nifty falls 10%",
     "Hypothetical market-wide fall. Equity funds and shares move 1:1; hybrid funds by their "
     "typical equity share.",
     {"equity_move_pct": -10}),
    ("market", "What if: gold rises 8%",
     "Hypothetical move in gold prices (SGBs, gold ETFs, gold funds).",
     {"gold_move_pct": 8}),
]


def seed_events(session: Session, today: date) -> int:
    for i, (kind, title, summary, tags) in enumerate(SAMPLE_EVENTS):
        session.add(Event(date=today - timedelta(days=i // 3), kind=kind, title=title, summary=summary,
                          source="Kosh sample scenario", tags=tags, is_sample=True))
    return len(SAMPLE_EVENTS)


def remove_demo(session: Session) -> dict:
    ids = list(session.scalars(select(Client.id).where(Client.is_demo.is_(True))))
    for c in session.scalars(select(Client).where(Client.id.in_(ids))):
        session.delete(c)
    n_ev = session.execute(delete(Event).where(Event.is_sample.is_(True))).rowcount
    audit(session, "remove_demo", None, clients=len(ids), events=n_ev)
    return {"clients_removed": len(ids), "events_removed": n_ev}
