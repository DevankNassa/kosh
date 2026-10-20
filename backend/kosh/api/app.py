"""HTTP API (FastAPI). Also serves the built web app from kosh/web_dist."""

import base64
import datetime
import io
import logging
import secrets
from datetime import date
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from .. import config, settings_store
from ..analytics.portfolio import (
    PriceBook,
    allocations,
    build_portfolio,
    debt_summary,
    instruments_for,
    market_asof,
    summary,
    target_drift,
)
from ..db import get_session, init_db
from ..impact.shocks import book_impact, portfolio_impact
from ..importer import cas
from ..models import Account, AuditLog, Client, Event, Import, Instrument, Transaction, audit
from ..tax import planner, rules
from . import export

log = logging.getLogger(__name__)

DISCLAIMER = (
    "For information only; not investment advice. Mutual fund investments are subject to market "
    "risks, read all scheme related documents carefully. Tax figures are indicative estimates; "
    "please confirm with a tax professional."
)

app = FastAPI(title="Kosh", version="0.1.0")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gate every request behind HTTP basic auth when KOSH_AUTH_USER/KOSH_AUTH_PASS are set.

    Kosh has no login system (showcase MVP, single user) — this is the minimum needed
    before exposing it over a tunnel or public URL to a client.
    """

    async def dispatch(self, request, call_next):
        if not (config.AUTH_USER and config.AUTH_PASS):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            except Exception:
                user, pw = "", ""
            if secrets.compare_digest(user, config.AUTH_USER) and secrets.compare_digest(pw, config.AUTH_PASS):
                return await call_next(request)
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Kosh"'})


app.add_middleware(BasicAuthMiddleware)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.exception_handler(cas.ImportErrorUser)
def _import_error(_, exc: cas.ImportErrorUser):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------- helpers

def _client_or_404(s: Session, client_id: int) -> Client:
    c = s.get(Client, client_id)
    if c is None:
        raise HTTPException(404, "Client not found")
    return c


def _all_portfolios(s: Session):
    clients = list(s.scalars(select(Client).order_by(Client.name)))
    isins = {t for (t,) in s.execute(select(Transaction.isin).distinct())}
    book = PriceBook(s, instruments_for(s, isins))
    return [build_portfolio(s, c, book) for c in clients]


def _client_dict(c: Client) -> dict:
    return {
        "id": c.id, "name": c.name, "pan_masked": (c.pan[:3] + "XXXX" + c.pan[-3:]) if c.pan else None,
        "email": c.email, "residency": c.residency, "tax_regime": c.tax_regime, "slab_rate": c.slab_rate,
        "surcharge_rate": c.surcharge_rate, "risk_profile": c.risk_profile, "family": c.family,
        "notes": c.notes, "target_allocation": c.target_allocation, "cf_stcl": c.cf_stcl,
        "cf_ltcl": c.cf_ltcl, "is_demo": c.is_demo,
    }


def _event_dict(e: Event) -> dict:
    return {"id": e.id, "date": e.date, "kind": e.kind, "title": e.title, "summary": e.summary,
            "source": e.source, "source_url": e.source_url, "tags": e.tags,
            "actual_tags": e.actual_tags, "is_sample": e.is_sample}


# ---------------------------------------------------------------- status & settings

@app.get("/api/status")
def status(s: Session = Depends(get_session)):
    return {
        "market": settings_store.get(s, "market_status"),
        "market_asof": market_asof(s),
        "yield_curve": settings_store.get(s, "yield_curve"),
        "indices": settings_store.get(s, "indices"),
        "settings": {k: settings_store.get(s, k) for k in ("distributor_name", "arn", "firm_name")},
        "clients": s.scalar(select(func.count(Client.id))),
        "demo_clients": s.scalar(select(func.count(Client.id)).where(Client.is_demo.is_(True))),
        "disclaimer": DISCLAIMER,
        "rules": [r.name for r in rules.RULESETS],
    }


class SettingsIn(BaseModel):
    distributor_name: Optional[str] = None
    arn: Optional[str] = None
    firm_name: Optional[str] = None


@app.put("/api/settings")
def put_settings(body: SettingsIn, s: Session = Depends(get_session)):
    for k, v in body.model_dump(exclude_none=True).items():
        settings_store.put(s, k, v.strip())
    audit(s, "update_settings", None, **body.model_dump(exclude_none=True))
    return {"ok": True}


@app.post("/api/market/refresh")
def refresh(s: Session = Depends(get_session)):
    from ..marketdata.refresh import refresh_market_data
    st = refresh_market_data(s)
    audit(s, "market_refresh", None, ok={k: v.get("ok") for k, v in st.items() if isinstance(v, dict)})
    return st


# ---------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard(s: Session = Depends(get_session)):
    ps = _all_portfolios(s)
    total = sum(p.value for p in ps)
    change = sum(p.day_change for p in ps)
    clients = []
    alerts = {"long_term_soon": 0, "cost_unknown_clients": 0, "drift_clients": 0, "stale_prices": 0}
    movers: dict[str, dict] = {}
    for p in ps:
        sm = summary(p, include_holdings=False)
        contrib = sorted((h for h in p.holdings if h.day_change), key=lambda h: -abs(h.day_change))[:3]
        drift = [d for d in target_drift(p) if d["drift_pct"] is not None and abs(d["drift_pct"]) >= 0.05]
        soon = planner.insights(s, p)["long_term_soon"]
        alerts["long_term_soon"] += len({(r["isin"], r["long_term_on"]) for r in soon})
        alerts["cost_unknown_clients"] += 1 if sm["cost_unknown_value"] > 0 else 0
        alerts["drift_clients"] += 1 if drift else 0
        alerts["stale_prices"] += sm["stale_prices"]
        clients.append({
            **{k: sm[k] for k in ("client_id", "value", "day_change", "day_change_pct", "xirr",
                                  "unrealised", "cost_unknown_value")},
            "name": p.client.name, "is_demo": p.client.is_demo, "residency": p.client.residency,
            "top_contributors": [{"name": h.instrument.name, "symbol": h.instrument.symbol,
                                  "day_change": round(h.day_change, 2)} for h in contrib],
            "drift": drift, "long_term_soon": len(soon),
        })
        for h in p.holdings:
            if h.day_change:
                m = movers.setdefault(h.instrument.isin, {"isin": h.instrument.isin, "name": h.instrument.name,
                                                          "symbol": h.instrument.symbol, "day_change": 0.0,
                                                          "value": 0.0, "clients": 0,
                                                          "price_change_pct": (h.quote.price / h.quote.prev_price - 1)
                                                          if h.quote and h.quote.prev_price else None})
                m["day_change"] += h.day_change
                m["value"] += h.value
                m["clients"] += 1
    by_class: dict[str, float] = {}
    for p in ps:
        for r in allocations(p)["asset_class"]:
            by_class[r["name"]] = by_class.get(r["name"], 0) + r["value"]
    events = list(s.scalars(select(Event).order_by(Event.date.desc(), Event.id.desc()).limit(8)))
    ev_out = []
    for e in events:
        bi = book_impact(ps, e.tags or {})
        ev_out.append({**_event_dict(e), "clients_exposed": bi["clients_exposed"],
                       "exposure": bi["exposure"], "impact": bi["impact"]})
    prev = total - change
    return {
        "asof": market_asof(s),
        "book_value": round(total, 2),
        "day_change": round(change, 2),
        "day_change_pct": change / prev if prev else None,
        "clients": sorted(clients, key=lambda c: c["day_change"]),
        "allocation": sorted(({"name": k, "value": round(v, 2), "pct": v / total if total else 0}
                              for k, v in by_class.items()), key=lambda r: -r["value"]),
        "top_movers": sorted(movers.values(), key=lambda m: -abs(m["day_change"]))[:8],
        "events": ev_out,
        "alerts": alerts,
        "indices": settings_store.get(s, "indices"),
    }


# ---------------------------------------------------------------- clients

class ClientIn(BaseModel):
    name: Optional[str] = None
    pan: Optional[str] = None
    email: Optional[str] = None
    residency: Optional[str] = None
    tax_regime: Optional[str] = None
    slab_rate: Optional[float] = None
    surcharge_rate: Optional[float] = None
    risk_profile: Optional[str] = None
    family: Optional[str] = None
    notes: Optional[str] = None
    target_allocation: Optional[dict[str, float]] = None
    cf_stcl: Optional[float] = None
    cf_ltcl: Optional[float] = None


@app.get("/api/clients")
def list_clients(s: Session = Depends(get_session)):
    ps = _all_portfolios(s)
    return [{**_client_dict(p.client), **summary(p, include_holdings=False)} for p in ps]


@app.post("/api/clients")
def create_client(body: ClientIn, s: Session = Depends(get_session)):
    if not body.name:
        raise HTTPException(400, "Name is required")
    c = Client(**{k: v for k, v in body.model_dump(exclude_none=True).items()})
    if c.pan:
        c.pan = c.pan.upper().strip()
    s.add(c)
    s.flush()
    audit(s, "create_client", "client", client_id=c.id)
    return _client_dict(c)


@app.get("/api/clients/{client_id}")
def get_client(client_id: int, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    p = build_portfolio(s, c)
    return {
        "client": _client_dict(c),
        "accounts": [{"id": a.id, "kind": a.kind, "identifier": a.identifier, "provider": a.provider,
                      "arn": a.arn} for a in c.accounts],
        "summary": summary(p),
        "allocations": allocations(p),
        "drift": target_drift(p),
        "debt": debt_summary(p),
    }


@app.put("/api/clients/{client_id}")
def update_client(client_id: int, body: ClientIn, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    changes = body.model_dump(exclude_unset=True)
    if "target_allocation" in changes and changes["target_allocation"]:
        tot = sum(changes["target_allocation"].values())
        if tot and abs(tot - 1) > 0.011:
            raise HTTPException(400, f"Target allocation must add up to 100% (now {tot:.0%})")
    for k, v in changes.items():
        setattr(c, k, v)
    audit(s, "update_client", "client", client_id=c.id, fields=list(changes))
    return _client_dict(c)


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: int, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    s.delete(c)
    audit(s, "delete_client", "client", client_id=client_id)
    return {"ok": True}


@app.get("/api/clients/{client_id}/transactions")
def client_transactions(client_id: int, s: Session = Depends(get_session)):
    _client_or_404(s, client_id)
    rows = s.execute(
        select(Transaction, Instrument.name, Account.identifier, Account.provider)
        .join(Account).join(Instrument, Instrument.isin == Transaction.isin)
        .where(Account.client_id == client_id).order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    ).all()
    return [{"id": t.id, "date": t.trade_date, "type": t.type, "isin": t.isin, "name": name,
             "account": f"{prov or ''} · {ident}", "units": t.units, "price": t.price, "amount": t.amount,
             "date_is_estimate": t.date_is_estimate, "source": t.source, "description": t.description}
            for t, name, ident, prov in rows]


@app.get("/api/clients/{client_id}/tax")
def client_tax(client_id: int, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    p = build_portfolio(s, c)
    return {
        "realised": planner.fy_realised(s, p),
        "insights": planner.insights(s, p),
        "tax_per_lakh": planner.tax_per_lakh(s, c, p),
        "assumptions": {"slab_rate": c.slab_rate, "surcharge_rate": c.surcharge_rate,
                        "tax_regime": c.tax_regime, "residency": c.residency,
                        "rules": rules.ruleset_for(p.asof).name},
    }


class WhatIfIn(BaseModel):
    sells: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []
    sale_date: Optional[date] = None
    overrides: Optional[dict[str, float]] = None
    label: Optional[str] = None


@app.post("/api/clients/{client_id}/whatif")
def whatif(client_id: int, body: WhatIfIn, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    return planner.simulate(s, c, body.sells, body.buys, body.sale_date, body.overrides)


class WhatIfExportIn(BaseModel):
    scenarios: list[WhatIfIn]


@app.post("/api/clients/{client_id}/whatif/export")
def whatif_export(client_id: int, body: WhatIfExportIn, s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    results = [(sc.label or f"Scenario {i + 1}",
                planner.simulate(s, c, sc.sells, sc.buys, sc.sale_date, sc.overrides))
               for i, sc in enumerate(body.scenarios)]
    meta = {k: settings_store.get(s, k) for k in ("distributor_name", "arn", "firm_name")}
    data = export.whatif_xlsx(c, results, meta, DISCLAIMER)
    audit(s, "export_whatif", "client", client_id=c.id, scenarios=len(results),
          inputs=[sc.model_dump(mode="json") for sc in body.scenarios])
    fname = f"kosh-whatif-{c.name.replace(' ', '_')}-{date.today().isoformat()}.xlsx"
    return StreamingResponse(io.BytesIO(data),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class CostLot(BaseModel):
    date: date
    units: float
    price: float


class CostBasisIn(BaseModel):
    account_id: int
    isin: str
    lots: list[CostLot]


@app.post("/api/clients/{client_id}/cost-basis")
def set_cost_basis(client_id: int, body: CostBasisIn, s: Session = Depends(get_session)):
    """Replace a holding's 'cost unknown' opening balance with purchase lots."""
    c = _client_or_404(s, client_id)
    acct = s.get(Account, body.account_id)
    if acct is None or acct.client_id != c.id:
        raise HTTPException(404, "Account not found")
    openings = [t for t in acct.transactions if t.isin == body.isin and t.type == "OPENING"
                and (t.price is None or t.date_is_estimate)]
    if not openings:
        raise HTTPException(400, "No holding with unknown cost for this instrument")
    opening_units = sum(t.units for t in openings)
    lot_units = sum(l.units for l in body.lots)
    if abs(lot_units - opening_units) > 1e-4:
        raise HTTPException(400, f"Lots add up to {lot_units:g} units; the holding has {opening_units:g}")
    for t in openings:
        s.delete(t)
    for i, l in enumerate(body.lots):
        s.add(Transaction(account_id=acct.id, isin=body.isin, trade_date=l.date, type="BUY", units=l.units,
                          price=l.price, amount=l.units * l.price, source="manual",
                          description="Cost basis entered by user",
                          dedupe_key=f"cost-{acct.id}-{body.isin}-{l.date}-{l.units}-{l.price}-{i}"))
    audit(s, "set_cost_basis", "client", client_id=c.id, account_id=acct.id, isin=body.isin,
          lots=len(body.lots))
    return {"ok": True}


# ---------------------------------------------------------------- events & scenarios

class EventIn(BaseModel):
    title: str
    kind: str = "market"
    # qualified as datetime.date, not bare `date`: pydantic v2 resolves a field's
    # own type hint using the class namespace, and a field named the same as its
    # type (with a default) shadows the type with the default value (None here),
    # silently turning `Optional[date]` into `Optional[NoneType]`
    date: Optional[datetime.date] = None
    summary: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    tags: dict[str, Any] = {}


@app.get("/api/events")
def list_events(s: Session = Depends(get_session)):
    ps = _all_portfolios(s)
    out = []
    for e in s.scalars(select(Event).order_by(Event.date.desc(), Event.id.desc())):
        bi = book_impact(ps, e.actual_tags or e.tags or {})
        out.append({**_event_dict(e), "clients_exposed": bi["clients_exposed"], "exposure": bi["exposure"],
                    "impact": bi["impact"], "impact_basis": "actual" if e.actual_tags else "estimated"})
    return out


@app.post("/api/events")
def create_event(body: EventIn, s: Session = Depends(get_session)):
    e = Event(title=body.title, kind=body.kind, date=body.date or date.today(), summary=body.summary,
              source=body.source or "Entered by user", source_url=body.source_url, tags=body.tags,
              is_sample=False)
    s.add(e)
    s.flush()
    audit(s, "create_event", "event", event_id=e.id)
    return _event_dict(e)


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, s: Session = Depends(get_session)):
    e = s.get(Event, event_id)
    if e is None:
        raise HTTPException(404, "Event not found")
    s.delete(e)
    return {"ok": True}


@app.get("/api/events/{event_id}/impact")
def event_impact(event_id: int, s: Session = Depends(get_session)):
    e = s.get(Event, event_id)
    if e is None:
        raise HTTPException(404, "Event not found")
    basis = "actual" if e.actual_tags else "estimated"
    return {"event": _event_dict(e), "impact_basis": basis,
            **book_impact(_all_portfolios(s), e.actual_tags or e.tags or {})}


@app.post("/api/scenario")
def scenario(shock: dict[str, Any], s: Session = Depends(get_session)):
    return book_impact(_all_portfolios(s), shock)


@app.get("/api/scenario/historical")
def historical_scenarios(s: Session = Depends(get_session)):
    from ..impact.historical import HISTORICAL_EVENTS, real_shock
    out = []
    for ev in HISTORICAL_EVENTS:
        shock = real_shock(s, ev.sector, ev.start, ev.end)
        out.append({"id": ev.id, "label": ev.label, "start": ev.start, "end": ev.end,
                    "sector": ev.sector, "shock": shock})
    return out


@app.post("/api/scenario/historical/{event_id}")
def apply_historical_scenario(event_id: str, s: Session = Depends(get_session)):
    from ..impact.historical import HISTORICAL_EVENTS, real_shock
    ev = next((e for e in HISTORICAL_EVENTS if e.id == event_id), None)
    if ev is None:
        raise HTTPException(404, "Historical event not found")
    shock = real_shock(s, ev.sector, ev.start, ev.end)
    return {"historical_event": {"id": ev.id, "label": ev.label, "start": ev.start, "end": ev.end},
            **book_impact(_all_portfolios(s), shock)}


@app.get("/api/scenario/historical/{event_id}/chart")
def historical_scenario_chart(event_id: str, mode: str = "families", days_before: int = 20, days_after: int = 20,
                               s: Session = Depends(get_session)):
    from datetime import timedelta

    from ..impact.historical import HISTORICAL_EVENTS, family_series, sector_small_multiples
    ev = next((e for e in HISTORICAL_EVENTS if e.id == event_id), None)
    if ev is None:
        raise HTTPException(404, "Historical event not found")
    start, end = ev.start - timedelta(days=days_before), ev.end + timedelta(days=days_after)
    event = {"id": ev.id, "label": ev.label, "start": ev.start, "end": ev.end, "sector": ev.sector}
    if mode == "sectors":
        return {"event": event, "mode": mode, "start": start, "end": end, **sector_small_multiples(s, start, end)}
    return {"event": event, "mode": "families", "start": start, "end": end,
            "series": family_series(s, ev.sector, start, end)}


@app.get("/api/market/chart")
def market_chart(sector: Optional[str] = None, event_id: Optional[int] = None,
                  days_before: int = 30, days_after: int = 30, s: Session = Depends(get_session)):
    from datetime import timedelta

    from ..analytics.classify import BROAD_MARKET_INDEX, SECTOR_INDEX
    from ..marketdata.backfill import backfill_indices
    from ..models import IndexPrice

    event = None
    if event_id is not None:
        e = s.get(Event, event_id)
        if e is None:
            raise HTTPException(404, "Event not found")
        flt = (e.tags or {}).get("filter") if isinstance(e.tags, dict) else None
        sector = sector or (flt.get("sector") if isinstance(flt, dict) else None)
        event = {"id": e.id, "title": e.title, "date": e.date}
        center = e.date
    else:
        center = market_asof(s)

    start, end = center - timedelta(days=days_before), center + timedelta(days=days_after)
    names = [BROAD_MARKET_INDEX]
    sector_index = SECTOR_INDEX.get(sector) if sector else None
    if sector_index:
        names.append(sector_index)
    backfill_indices(s, names, start, end)

    series = {}
    for name in names:
        rows = s.scalars(select(IndexPrice).where(IndexPrice.name == name, IndexPrice.date.between(start, end))
                          .order_by(IndexPrice.date))
        pts = [(r.date, r.close) for r in rows]
        if not pts:
            series[name] = []
            continue
        base = pts[0][1]
        series[name] = [{"date": d, "value": round(c / base * 100, 2)} for d, c in pts]

    return {"event": event, "sector": sector, "sector_index": sector_index,
            "market_index": BROAD_MARKET_INDEX, "start": start, "end": end, "series": series}


@app.post("/api/clients/{client_id}/scenario")
def client_scenario(client_id: int, shock: dict[str, Any], s: Session = Depends(get_session)):
    c = _client_or_404(s, client_id)
    return portfolio_impact(build_portfolio(s, c), shock)


# ---------------------------------------------------------------- instruments

@app.get("/api/instruments/search")
def search_instruments(q: str, limit: int = 20, s: Session = Depends(get_session)):
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    rows = s.scalars(select(Instrument).where(or_(
        Instrument.name.ilike(like), Instrument.symbol.ilike(like), Instrument.isin == q.upper()))
        .order_by((Instrument.symbol == q.upper()).desc(), Instrument.kind, Instrument.name).limit(limit))
    return [{"isin": i.isin, "name": i.name, "symbol": i.symbol, "kind": i.kind, "asset_class": i.asset_class,
             "sub_class": i.sub_class, "sector": i.sector, "plan": i.plan} for i in rows]


@app.get("/api/sectors")
def sectors(s: Session = Depends(get_session)):
    return [r for (r,) in s.execute(select(Instrument.sector).where(Instrument.sector.is_not(None))
                                    .distinct().order_by(Instrument.sector))]


class InstrumentIn(BaseModel):
    rating: Optional[str] = None
    face_value: Optional[float] = None
    coupon: Optional[float] = None
    coupon_freq: Optional[int] = None
    maturity: Optional[date] = None
    sector: Optional[str] = None
    issuer: Optional[str] = None


@app.put("/api/instruments/{isin}")
def update_instrument(isin: str, body: InstrumentIn, s: Session = Depends(get_session)):
    ins = s.get(Instrument, isin)
    if ins is None:
        raise HTTPException(404, "Instrument not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(ins, k, v)
    if "maturity" in changes:
        ins.maturity_is_estimate = False
    audit(s, "update_instrument", "instrument", isin=isin, fields=list(changes))
    return {"ok": True}


# ---------------------------------------------------------------- import

@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...), password: str = Form(""),
                         s: Session = Depends(get_session)):
    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a CAS statement PDF")
    data = cas.parse_pdf(content, password)
    del content
    payload = cas.normalise(data)
    return cas.build_preview(s, payload, file.filename or "statement.pdf")


class CommitIn(BaseModel):
    token: str
    client_id: Optional[int] = None
    new_client: Optional[dict[str, Any]] = None


@app.post("/api/import/commit")
def import_commit(body: CommitIn, s: Session = Depends(get_session)):
    return cas.commit(s, body.token, body.client_id, body.new_client)


@app.get("/api/imports")
def list_imports(s: Session = Depends(get_session)):
    rows = s.execute(select(Import, Client.name).join(Client, isouter=True).order_by(Import.created_at.desc())).all()
    return [{"id": i.id, "client_id": i.client_id, "client_name": n, "filename": i.filename,
             "file_type": i.file_type, "period": f"{i.statement_from} – {i.statement_to}",
             "summary": i.summary, "warnings": i.warnings, "created_at": i.created_at} for i, n in rows]


# ---------------------------------------------------------------- demo & audit

@app.post("/api/demo/reset")
def demo_reset(s: Session = Depends(get_session)):
    from ..demo.seed import remove_demo, seed_demo
    removed = remove_demo(s)
    s.flush()
    return {**removed, **seed_demo(s)}


@app.post("/api/demo/remove")
def demo_remove(s: Session = Depends(get_session)):
    from ..demo.seed import remove_demo
    return remove_demo(s)


@app.get("/api/audit")
def audit_log(limit: int = 100, s: Session = Depends(get_session)):
    rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return [{"ts": a.ts, "action": a.action, "entity": a.entity, "details": a.details} for a in rows]


# ---------------------------------------------------------------- web app

if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = config.WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.WEB_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_ui():
        return JSONResponse({"message": "API is running. Build the web app: cd frontend && npm install && npm run build"})
