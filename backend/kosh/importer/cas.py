"""Consolidated Account Statement (CAS) import.

Parsing uses the open-source `casparser` library (CAMS / KFintech detailed &
summary, NSDL / CDSL). The PDF and its password are only used in memory /
a temp file that is deleted immediately; neither is stored."""

import hashlib
import os
import secrets
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.classify import classify_exchange
from ..analytics.portfolio import TxnIn, run_fifo
from ..models import Account, Client, Import, Instrument, Price, Transaction, audit

BUY_TYPES = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER", "DIVIDEND_REINVEST", "GIFT_IN"}
SELL_TYPES = {"REDEMPTION", "SWITCH_OUT", "SWITCH_OUT_MERGER", "GIFT_OUT"}
SIGNED_TYPES = {"REVERSAL"}
IGNORED_TYPES = {"STT_TAX", "STAMP_DUTY_TAX", "TDS_TAX", "DIVIDEND_PAYOUT", "MISC", "UNKNOWN"}

_PREVIEWS: dict[str, tuple[float, dict]] = {}
PREVIEW_TTL = 30 * 60


class ImportErrorUser(Exception):
    """An import problem to show to the user."""


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def _d(x: Any) -> Optional[date]:
    if x is None:
        return None
    if isinstance(x, date):
        return x
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(x).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _ev(x: Any) -> str:
    return getattr(x, "value", x) if x is not None else ""


# ---------------------------------------------------------------- parse

def parse_pdf(content: bytes, password: str):
    try:
        import casparser
    except ImportError as e:  # pragma: no cover
        raise ImportErrorUser("casparser is not installed") from e
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        try:
            return casparser.read_cas_pdf(path, password)
        except Exception as e:
            msg = str(e)
            if "password" in msg.lower() or "decrypt" in msg.lower():
                raise ImportErrorUser("Could not open the PDF: wrong password? CAS passwords are "
                                      "usually the PAN (CAMS/KFintech) or set by you (NSDL/CDSL).") from e
            raise ImportErrorUser(f"Could not read this statement: {msg[:200]}") from e
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def normalise(data) -> dict:
    """casparser output → Kosh's import payload (plain dicts)."""
    file_type = _ev(getattr(data, "file_type", "")) or "UNKNOWN"
    period = getattr(data, "statement_period", None)
    p_from = _d(getattr(period, "from_", None)) if period else None
    p_to = _d(getattr(period, "to", None)) if period else None
    inv = getattr(data, "investor_info", None)
    out = {
        "file_type": file_type,
        "cas_type": _ev(getattr(data, "cas_type", "")) or ("HOLDINGS" if hasattr(data, "accounts") else ""),
        "period_from": p_from,
        "period_to": p_to,
        "investor": {"name": getattr(inv, "name", "") if inv else "", "email": getattr(inv, "email", "") if inv else ""},
        "pans": [],
        "accounts": [],
        "warnings": list(getattr(data, "parse_warnings", []) or []),
    }
    if hasattr(data, "folios"):
        _norm_rta(data, out)
    elif hasattr(data, "accounts"):
        _norm_depository(data, out)
    else:
        raise ImportErrorUser("Unrecognised statement format")
    out["pans"] = sorted({p for p in out["pans"] if p})
    return out


def _norm_rta(data, out: dict) -> None:
    p_from, p_to = out["period_from"], out["period_to"]
    for folio in data.folios:
        if folio.PAN:
            out["pans"].append(folio.PAN)
        acct = {
            "kind": "mf_folio", "identifier": folio.folio.strip(), "provider": folio.amc,
            "depository": out["file_type"], "arn": None, "holdings": [], "transactions": [],
        }
        for sc in folio.schemes:
            isin = (sc.isin or "").strip() or None
            if sc.advisor:
                acct["arn"] = sc.advisor
            val = sc.valuation
            close = _f(sc.close) or 0.0
            hold = {
                "isin": isin, "amfi": sc.amfi, "name": sc.scheme, "type_hint": sc.type,
                "units": close, "price": _f(val.nav) if val else None,
                "price_date": _d(val.date) if val else p_to, "value": _f(val.value) if val else None,
                "cost": _f(val.cost) if val else None,
            }
            acct["holdings"].append(hold)
            opening = _f(sc.open) or 0.0
            if out["cas_type"] == "SUMMARY" or not sc.transactions:
                if close > 0:
                    cost = hold["cost"]
                    acct["transactions"].append({
                        "isin": isin, "amfi": sc.amfi, "date": p_to or date.today(), "type": "OPENING",
                        "units": close, "price": (cost / close) if cost else None, "amount": cost,
                        "date_is_estimate": True, "description": "Holding from summary statement",
                    })
                continue
            if opening > 1e-6:
                acct["transactions"].append({
                    "isin": isin, "amfi": sc.amfi, "date": p_from or date.today(), "type": "OPENING",
                    "units": opening, "price": None, "amount": None, "date_is_estimate": True,
                    "description": "Opening balance before statement period (cost unknown)",
                })
            for t in sc.transactions:
                ttype = _ev(t.type)
                units = _f(t.units)
                if ttype in IGNORED_TYPES or units is None or abs(units) < 1e-9:
                    continue
                if ttype == "SEGREGATION":
                    out["warnings"].append(f"{sc.scheme}: segregated portfolio units skipped")
                    continue
                if ttype in BUY_TYPES:
                    kind = "BUY"
                elif ttype in SELL_TYPES:
                    kind = "SELL"
                elif ttype in SIGNED_TYPES:
                    kind = "BUY" if units > 0 else "SELL"
                else:
                    kind = "BUY" if units > 0 else "SELL"
                amount = abs(_f(t.amount) or 0.0)
                nav = _f(t.nav) or (amount / abs(units) if amount else None)
                acct["transactions"].append({
                    "isin": isin, "amfi": sc.amfi, "date": _d(t.date), "type": kind,
                    "units": abs(units), "price": nav, "amount": amount or None,
                    "date_is_estimate": False, "description": (t.description or "")[:300],
                })
        out["accounts"].append(acct)


def _norm_depository(data, out: dict) -> None:
    p_to = out["period_to"] or date.today()
    for ac in data.accounts:
        for o in ac.owners or []:
            out["pans"].append(o.PAN)
        is_mf = "mutual fund" in (ac.type or "").lower()
        ident = f"{ac.dp_id or ''}{ac.client_id or ''}".strip() or ac.name
        dep = "NSDL" if "nsdl" in (ac.type or "").lower() else ("CDSL" if "cdsl" in (ac.type or "").lower() else out["file_type"])
        base = {"kind": "mf_folio" if is_mf else "demat", "provider": ac.name, "depository": dep,
                "arn": None}
        if is_mf:
            # one Kosh account per folio
            by_folio = defaultdict(list)
            for mf in ac.mutual_funds:
                by_folio[(mf.folio or ident).strip()].append(mf)
            for folio, mfs in by_folio.items():
                acct = {**base, "identifier": folio, "holdings": [], "transactions": []}
                for mf in mfs:
                    _add_holding(acct, mf.isin, mf.name, "MF", _f(mf.balance), _f(mf.nav), _f(mf.value),
                                 p_to, avg_cost=_f(mf.avg_cost), type_hint=mf.type)
                out["accounts"].append(acct)
            continue
        acct = {**base, "identifier": ident, "holdings": [], "transactions": []}
        for eq in ac.equities:
            _add_holding(acct, eq.isin, eq.name, "EQUITY", _f(eq.num_shares), _f(eq.price), _f(eq.value), p_to)
        for mf in ac.mutual_funds:
            _add_holding(acct, mf.isin, mf.name, "MF", _f(mf.balance), _f(mf.nav), _f(mf.value), p_to,
                         avg_cost=_f(mf.avg_cost), type_hint=mf.type)
        for b in getattr(ac, "bonds", []) or []:
            units = _f(b.num_bonds)
            value = _f(b.value)
            price = _f(b.market_price) or ((value / units) if value and units else None)
            _add_holding(acct, b.isin, b.name, "BOND", units, price, value, p_to,
                         bond={"face_value": _f(b.face_value), "coupon": _f(b.coupon_rate),
                               "frequency": b.coupon_frequency, "maturity": _d(b.maturity_date)})
        out["accounts"].append(acct)


def _add_holding(acct, isin, name, section, units, price, value, asof, avg_cost=None, type_hint=None, bond=None):
    if not isin or not units:
        return
    acct["holdings"].append({"isin": isin, "name": name, "section": section, "units": units,
                             "price": price, "price_date": asof, "value": value,
                             "type_hint": type_hint, "bond": bond})
    acct["transactions"].append({
        "isin": isin, "date": asof, "type": "OPENING", "units": units,
        "price": avg_cost, "amount": (avg_cost * units) if avg_cost else None,
        "date_is_estimate": True,
        "description": "Holding from depository statement" + ("" if avg_cost else " (cost unknown)"),
    })


# ---------------------------------------------------------------- instruments

def _resolve_isins(session: Session, payload: dict) -> list[str]:
    """Fill missing ISINs from AMFI codes; create instruments for ISINs not in
    the master. Returns warnings."""
    warnings = []
    for acct in payload["accounts"]:
        for item in acct["holdings"] + acct["transactions"]:
            if not item.get("isin") and item.get("amfi"):
                ins = session.scalars(select(Instrument).where(Instrument.amfi_code == str(item["amfi"]))).first()
                if ins:
                    item["isin"] = ins.isin
        for h in acct["holdings"]:
            if not h.get("isin"):
                warnings.append(f"{h['name']}: no ISIN in statement; skipped")
                continue
            if session.get(Instrument, h["isin"]) is None:
                session.add(_new_instrument(h))
                session.flush()
    return warnings


def _new_instrument(h: dict) -> Instrument:
    isin, name = h["isin"], h["name"] or h["isin"]
    section = h.get("section") or "MF"
    hint = (h.get("type_hint") or "").upper()
    if section == "BOND" or isin.startswith("IN00"):
        b = h.get("bond") or {}
        series = "GS" if isin.startswith("IN00") else "N1"
        fields = classify_exchange(isin, series, name)
        fields.update(face_value=b.get("face_value") or fields.get("face_value"),
                      coupon=(b["coupon"] / 100.0) if b.get("coupon") else fields.get("coupon"),
                      maturity=b.get("maturity") or fields.get("maturity"))
        if b.get("maturity"):
            fields["maturity_is_estimate"] = False
        if isin[2] == "E" and not isin.startswith("IN00"):
            fields["listed"] = True
    elif section == "EQUITY" and not isin.startswith("INF"):
        fields = classify_exchange(isin, "EQ", name)
    else:
        if hint == "DEBT":
            fields = dict(kind="mf", asset_class="debt", sub_class="Debt fund", tax_class="specified_debt",
                          mod_duration=3.0)
        else:
            fields = dict(kind="mf" if not isin.startswith("INF") or section == "MF" else "etf",
                          asset_class="equity", sub_class="Mutual fund", tax_class="equity")
    fields = {k: v for k, v in fields.items() if k in Instrument.__table__.columns}
    return Instrument(isin=isin, name=name, **fields)


# ---------------------------------------------------------------- preview / commit

def _dedupe(client_key: str, acct: dict, t: dict) -> str:
    raw = "|".join(str(x) for x in (
        client_key, acct["kind"], acct["identifier"], t["isin"], t["date"], t["type"],
        f"{t['units']:.4f}", f"{(t.get('amount') or 0):.2f}"))
    return hashlib.sha1(raw.encode()).hexdigest()


def _match_client(session: Session, payload: dict) -> Optional[Client]:
    for pan in payload["pans"]:
        c = session.scalars(select(Client).where(Client.pan == pan)).first()
        if c:
            return c
    return None


def _existing_account(session: Session, client: Optional[Client], acct: dict) -> Optional[Account]:
    if client is None:
        return None
    return session.scalars(select(Account).where(
        Account.client_id == client.id, Account.kind == acct["kind"],
        Account.identifier == acct["identifier"])).first()


def _reconcile(session: Session, client: Optional[Client], payload: dict) -> list[dict]:
    """Units the client will hold after import vs units printed on the statement."""
    txns: list[TxnIn] = []
    fake_id = 10 ** 9
    acct_ids: dict[tuple, int] = {}
    for i, acct in enumerate(payload["accounts"]):
        existing = _existing_account(session, client, acct)
        aid = existing.id if existing else -(i + 1)
        acct_ids[(acct["kind"], acct["identifier"])] = aid
        have = set()
        if existing:
            for t in existing.transactions:
                txns.append(TxnIn(t.id, aid, t.isin, t.trade_date, t.type, t.units, t.price, t.amount, t.date_is_estimate))
                have.add(t.isin)
        for t in acct["transactions"]:
            if not t.get("isin") or not t.get("date"):
                continue
            if t["type"] == "OPENING" and t["isin"] in have:
                continue  # already tracked; don't double count
            fake_id += 1
            txns.append(TxnIn(fake_id, aid, t["isin"], t["date"], t["type"], t["units"], t["price"], t.get("amount")))
    open_lots, _, warns = run_fifo(txns)
    rows = []
    for acct in payload["accounts"]:
        aid = acct_ids[(acct["kind"], acct["identifier"])]
        for h in acct["holdings"]:
            if not h.get("isin"):
                continue
            after = sum(l.units for l in open_lots.get((aid, h["isin"]), []))
            stmt = h["units"] or 0.0
            rows.append({
                "account": acct["identifier"], "isin": h["isin"], "name": h["name"],
                "statement_units": round(stmt, 4), "units_after_import": round(after, 4),
                "matches": abs(after - stmt) <= max(0.002, stmt * 1e-6),
                "value": h.get("value"),
            })
    return rows


def build_preview(session: Session, payload: dict, filename: str) -> dict:
    # Instruments created while previewing live in a savepoint that is rolled
    # back; commit() creates them again.
    savepoint = session.begin_nested()
    try:
        warnings = payload["warnings"] + _resolve_isins(session, payload)
        client = _match_client(session, payload)
        client_ref = {"id": client.id, "name": client.name} if client else None
        recon = _reconcile(session, client, payload)
        new_txn_count = 0
        for acct in payload["accounts"]:
            existing = _existing_account(session, client, acct)
            keys = {t.dedupe_key for t in existing.transactions} if existing else set()
            held = {t.isin for t in existing.transactions} if existing else set()
            ck = str(client.id) if client else "new"
            for t in acct["transactions"]:
                if not t.get("isin") or (t["type"] == "OPENING" and t["isin"] in held):
                    continue
                if _dedupe(ck, acct, t) not in keys:
                    new_txn_count += 1
    finally:
        savepoint.rollback()
    token = secrets.token_urlsafe(16)
    _gc()
    _PREVIEWS[token] = (time.time(), {"payload": payload, "filename": filename})
    total_value = sum((h.get("value") or 0) for a in payload["accounts"] for h in a["holdings"])
    return {
        "token": token,
        "file_type": payload["file_type"],
        "cas_type": payload["cas_type"],
        "period_from": payload["period_from"],
        "period_to": payload["period_to"],
        "investor_name": payload["investor"]["name"],
        "pans_masked": [p[:3] + "XXXX" + p[-3:] for p in payload["pans"] if len(p) == 10],
        "matched_client": client_ref,
        "accounts": [{
            "kind": a["kind"], "identifier": a["identifier"], "provider": a["provider"],
            "arn": a.get("arn"), "holdings": len(a["holdings"]),
            "transactions": sum(1 for t in a["transactions"] if t["type"] != "OPENING"),
            "cost_unknown": sum(1 for t in a["transactions"] if t["type"] == "OPENING" and t["price"] is None),
        } for a in payload["accounts"]],
        "total_value": round(total_value, 2),
        "new_transactions": new_txn_count,
        "reconciliation": recon,
        "warnings": warnings,
    }


def _gc() -> None:
    now = time.time()
    for k in [k for k, (ts, _) in _PREVIEWS.items() if now - ts > PREVIEW_TTL]:
        _PREVIEWS.pop(k, None)


def commit(session: Session, token: str, client_id: Optional[int], new_client: Optional[dict]) -> dict:
    item = _PREVIEWS.pop(token, None)
    if item is None:
        raise ImportErrorUser("This preview has expired. Please upload the statement again.")
    payload, filename = item[1]["payload"], item[1]["filename"]
    _resolve_isins(session, payload)
    if client_id:
        client = session.get(Client, client_id)
        if client is None:
            raise ImportErrorUser("Client not found")
    else:
        nc = new_client or {}
        client = Client(name=nc.get("name") or payload["investor"]["name"] or "New client",
                        pan=(payload["pans"][0] if payload["pans"] else None),
                        email=payload["investor"].get("email") or None,
                        slab_rate=float(nc.get("slab_rate", 0.30)))
        session.add(client)
        session.flush()
    if client.pan is None and payload["pans"]:
        client.pan = payload["pans"][0]

    imp = Import(client_id=client.id, filename=filename[:300], file_type=payload["file_type"],
                 statement_from=str(payload["period_from"] or ""), statement_to=str(payload["period_to"] or ""),
                 warnings=payload["warnings"])
    session.add(imp)
    session.flush()
    added = skipped = 0
    for a in payload["accounts"]:
        acct = _existing_account(session, client, a)
        if acct is None:
            acct = Account(client_id=client.id, kind=a["kind"], identifier=a["identifier"],
                           provider=a["provider"], depository=a["depository"], arn=a.get("arn"))
            session.add(acct)
            session.flush()
        elif a.get("arn"):
            acct.arn = a["arn"]
        held = {t.isin for t in acct.transactions}
        keys = {t.dedupe_key for t in acct.transactions}
        for t in a["transactions"]:
            if not t.get("isin") or not t.get("date"):
                skipped += 1
                continue
            if t["type"] == "OPENING" and t["isin"] in held:
                skipped += 1
                continue
            key = _dedupe(str(client.id), a, t)
            if key in keys or session.scalars(select(Transaction.id).where(Transaction.dedupe_key == key)).first():
                skipped += 1
                continue
            keys.add(key)
            session.add(Transaction(
                account_id=acct.id, isin=t["isin"], trade_date=t["date"], type=t["type"],
                units=t["units"], price=t["price"], amount=t.get("amount"),
                date_is_estimate=bool(t.get("date_is_estimate")), description=t.get("description"),
                source="cas", import_id=imp.id, dedupe_key=key,
            ))
            added += 1
        for h in a["holdings"]:
            if h.get("isin") and h.get("price") and h.get("price_date"):
                if session.get(Price, (h["isin"], h["price_date"])) is None:
                    session.add(Price(isin=h["isin"], date=h["price_date"], price=h["price"],
                                      source="statement", level="observed"))
    imp.summary = {"added": added, "skipped_duplicates": skipped, "accounts": len(payload["accounts"])}
    audit(session, "import_statement", "client", client_id=client.id, import_id=imp.id,
          file_type=payload["file_type"], added=added, skipped=skipped)
    session.flush()
    return {"client_id": client.id, "import_id": imp.id, "added": added, "skipped": skipped}
