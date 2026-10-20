"""Database tables. Transactions are the source of truth; lots and holdings
are derived from them (see analytics.portfolio)."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Instrument.kind values
KINDS = (
    "equity", "mf", "etf", "gsec", "sdl", "tbill", "corp_bond", "sgb",
    "reit_invit", "other",
)
# Instrument.asset_class values
ASSET_CLASSES = ("equity", "debt", "hybrid", "gold", "other")
# Instrument.tax_class values (see tax.rules)
TAX_CLASSES = (
    "equity",          # listed equity, equity MFs/ETFs, REIT/InvIT: 111A / 112A
    "specified_debt",  # debt MFs/ETFs (>65% debt): slab if bought on/after 1-Apr-2023
    "other_mf",        # hybrid (<65% equity), FoFs, international funds: 24m, 12.5%
    "listed_other",    # listed bonds, G-secs, SGBs, gold ETFs: 12m, 12.5%
    "unlisted_bond",   # unlisted debentures: always slab
    "unlisted_other",  # unlisted/foreign shares: 24m, 12.5%
)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    pan: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(200))
    residency: Mapped[str] = mapped_column(String(10), default="resident")  # resident | nri
    tax_regime: Mapped[str] = mapped_column(String(10), default="new")  # new | old
    slab_rate: Mapped[float] = mapped_column(Float, default=0.30)
    surcharge_rate: Mapped[float] = mapped_column(Float, default=0.0)
    risk_profile: Mapped[Optional[str]] = mapped_column(String(40))
    family: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # {"equity": 0.6, "debt": 0.3, "gold": 0.1}
    target_allocation: Mapped[Optional[dict]] = mapped_column(JSON)
    # carried-forward capital losses from earlier years, entered from the ITR
    cf_stcl: Mapped[float] = mapped_column(Float, default=0.0)
    cf_ltcl: Mapped[float] = mapped_column(Float, default=0.0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Account(Base):
    """A demat account (BO ID) or a mutual fund folio."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("client_id", "kind", "identifier"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))  # mf_folio | demat
    identifier: Mapped[str] = mapped_column(String(64))
    provider: Mapped[Optional[str]] = mapped_column(String(200))  # AMC or depository participant
    depository: Mapped[Optional[str]] = mapped_column(String(10))  # NSDL | CDSL | CAMS | KFINTECH
    arn: Mapped[Optional[str]] = mapped_column(String(40))  # distributor code on the folio

    client: Mapped[Client] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Instrument(Base):
    __tablename__ = "instruments"
    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="other")
    asset_class: Mapped[str] = mapped_column(String(20), default="other")
    sub_class: Mapped[Optional[str]] = mapped_column(String(80))
    tax_class: Mapped[str] = mapped_column(String(20), default="listed_other")
    sector: Mapped[Optional[str]] = mapped_column(String(80))
    issuer: Mapped[Optional[str]] = mapped_column(String(200))
    symbol: Mapped[Optional[str]] = mapped_column(String(40))
    listed: Mapped[bool] = mapped_column(Boolean, default=True)
    # mutual funds
    amfi_code: Mapped[Optional[str]] = mapped_column(String(12), index=True)
    amc: Mapped[Optional[str]] = mapped_column(String(120))
    mf_category: Mapped[Optional[str]] = mapped_column(String(120))
    plan: Mapped[Optional[str]] = mapped_column(String(20))  # Regular | Direct
    # debt analytics; for debt MFs this is a category-level estimate
    mod_duration: Mapped[Optional[float]] = mapped_column(Float)
    # bonds
    face_value: Mapped[Optional[float]] = mapped_column(Float)
    coupon: Mapped[Optional[float]] = mapped_column(Float)  # annual rate, 0.0735 = 7.35%
    coupon_freq: Mapped[Optional[int]] = mapped_column(Integer)  # payments per year
    maturity: Mapped[Optional[date]] = mapped_column(Date)
    maturity_is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[Optional[str]] = mapped_column(String(20))
    tax_free_interest: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    @property
    def issuer_key(self) -> str:
        """Indian ISINs encode the issuer in characters 3–7 (e.g. INE053F…),
        which links a company's shares and its bonds."""
        return self.isin[:7]


class Price(Base):
    __tablename__ = "prices"
    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))  # amfi | nse | model | statement | snapshot
    level: Mapped[str] = mapped_column(String(10), default="observed")  # observed | model | stale


class IndexPrice(Base):
    """Daily closes for NSE benchmark/sectoral indices (not individual
    instruments) — the real historical series behind historical scenarios
    and the market/event chart (see impact/historical.py)."""

    __tablename__ = "index_prices"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    isin: Mapped[str] = mapped_column(ForeignKey("instruments.isin"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(10))  # BUY | SELL | OPENING
    units: Mapped[float] = mapped_column(Float)  # always positive
    price: Mapped[Optional[float]] = mapped_column(Float)  # None = cost unknown
    amount: Mapped[Optional[float]] = mapped_column(Float)
    date_is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # cas | demo | manual
    import_id: Mapped[Optional[int]] = mapped_column(ForeignKey("imports.id", ondelete="SET NULL"))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True)

    account: Mapped[Account] = relationship(back_populates="transactions")
    instrument: Mapped[Instrument] = relationship()


class Import(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(300))
    file_type: Mapped[str] = mapped_column(String(20))
    statement_from: Mapped[Optional[str]] = mapped_column(String(20))
    statement_to: Mapped[Optional[str]] = mapped_column(String(20))
    summary: Mapped[Optional[dict]] = mapped_column(JSON)
    warnings: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # rate | rating | corporate | sector | market
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    # what the event touches, e.g. {"yield_shift_bps": -25} or
    # {"isins": ["INE..."], "spread_bps": 75} or {"sector": "Financial Services", "equity_move_pct": -3}
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    # the real, realized shock computed once the event has aged (see
    # marketdata.refresh); None until then. `tags` above is left as the
    # consultant's original estimate.
    actual_tags: Mapped[Optional[dict]] = mapped_column(JSON)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[Optional[str]] = mapped_column(String(60))
    details: Mapped[Optional[dict]] = mapped_column(JSON)


def audit(session, action: str, entity: str | None = None, **details) -> None:
    session.add(AuditLog(action=action, entity=entity, details=details or None))
