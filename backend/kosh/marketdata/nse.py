"""NSE end-of-day files from nsearchives.nseindia.com (free, published daily).

- Bhavcopy (UDiFF format): every security traded in the cash market, with
  ISIN — equities, ETFs, G-secs, SDLs, T-bills, SGBs, corporate bonds.
- Index closes: Nifty 50, sectoral and debt indices.
- Nifty 500 constituents: industry classification for listed stocks."""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from .. import config

BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
# Pre-UDiFF bhavcopy (NSE switched formats on 8 Jul 2024): same securities
# with ISIN, but no instrument names. Used only for history before that date.
LEGACY_BHAV_URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{y}/{m}/cm{d}bhav.csv.zip"
UDIFF_START = date(2024, 7, 8)
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
CORP_ACTIONS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
CORP_ACTIONS_URL = ("https://www.nseindia.com/api/corporates-corporateActions"
                    "?index=equities&from_date={f}&to_date={t}")
SECTOR_LISTS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
]


@dataclass
class BhavRow:
    isin: str
    symbol: str
    series: str
    name: str
    close: float
    prev_close: Optional[float]
    volume: float
    trade_date: date


def _client() -> httpx.Client:
    return httpx.Client(timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": config.USER_AGENT, "Accept": "*/*"})


def _f(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_bhavcopy(text: str) -> list[BhavRow]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        isin = (r.get("ISIN") or "").strip()
        close = _f(r.get("ClsPric"))
        if len(isin) != 12 or not close:
            continue
        rows.append(BhavRow(
            isin=isin,
            symbol=(r.get("TckrSymb") or "").strip(),
            series=(r.get("SctySrs") or "").strip(),
            name=(r.get("FinInstrmNm") or "").strip(),
            close=close,
            prev_close=_f(r.get("PrvsClsgPric")),
            volume=_f(r.get("TtlTradgVol")) or 0.0,
            trade_date=datetime.strptime(r["TradDt"].strip(), "%Y-%m-%d").date(),
        ))
    return rows


def parse_legacy_bhavcopy(text: str) -> list[BhavRow]:
    """Old 'cmDDMONYYYYbhav.csv': SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,
    PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        isin = (r.get("ISIN") or "").strip()
        close = _f(r.get("CLOSE"))
        if len(isin) != 12 or not close:
            continue
        symbol = (r.get("SYMBOL") or "").strip()
        rows.append(BhavRow(
            isin=isin, symbol=symbol, series=(r.get("SERIES") or "").strip(), name=symbol,
            close=close, prev_close=_f(r.get("PREVCLOSE")), volume=_f(r.get("TOTTRDQTY")) or 0.0,
            trade_date=datetime.strptime(r["TIMESTAMP"].strip(), "%d-%b-%Y").date(),
        ))
    return rows


def _unzip(content: bytes) -> Optional[str]:
    if not content.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


def fetch_bhavcopy(d: date, client: Optional[httpx.Client] = None) -> Optional[list[BhavRow]]:
    """Bhavcopy for one trading day, or None for holidays / not yet published.
    Falls back to the legacy format for dates before UDiFF."""
    c = client or _client()
    if d >= UDIFF_START:
        r = c.get(BHAV_URL.format(d=d.strftime("%Y%m%d")))
        text = _unzip(r.content) if r.status_code == 200 else None
        return parse_bhavcopy(text) if text else None
    r = c.get(LEGACY_BHAV_URL.format(y=d.year, m=d.strftime("%b").upper(), d=d.strftime("%d%b%Y").upper()))
    text = _unzip(r.content) if r.status_code == 200 else None
    return parse_legacy_bhavcopy(text) if text else None


def fetch_latest_bhavcopies(today: date, max_back: int = 10) -> tuple[list[BhavRow], list[BhavRow]]:
    """(latest trading day rows, previous trading day rows)."""
    found: list[list[BhavRow]] = []
    with _client() as c:
        d = today
        for _ in range(max_back):
            if d.weekday() < 5:
                rows = fetch_bhavcopy(d, c)
                if rows:
                    found.append(rows)
                    if len(found) == 2:
                        break
            d -= timedelta(days=1)
    if not found:
        return [], []
    return found[0], (found[1] if len(found) > 1 else [])


def fetch_index_closes(d: date, client: Optional[httpx.Client] = None) -> list[dict]:
    if client is not None:
        r = client.get(INDEX_URL.format(d=d.strftime("%d%m%Y")))
    else:
        with _client() as c:
            r = c.get(INDEX_URL.format(d=d.strftime("%d%m%Y")))
    if r.status_code != 200:
        return []
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        close = _f(row.get("Closing Index Value"))
        if close is None:
            continue
        out.append({
            "name": row.get("Index Name", "").strip(),
            "close": close,
            "change_pct": _f(row.get("Change(%)")),
        })
    return out


def fetch_sectors() -> dict[str, str]:
    """ISIN → industry, from Nifty 500 + Microcap 250 constituent files."""
    out: dict[str, str] = {}
    with _client() as c:
        for url in SECTOR_LISTS:
            try:
                r = c.get(url)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            for row in csv.DictReader(io.StringIO(r.text)):
                isin = (row.get("ISIN Code") or "").strip()
                ind = (row.get("Industry") or "").strip()
                if isin and ind:
                    out.setdefault(isin, ind)
    return out


# ---------------------------------------------------------------- corporate actions

_BONUS = re.compile(r"\bbonus\s*(\d+)\s*:\s*(\d+)", re.I)
_FACE_VALUE = re.compile(r"from\s+r[se]s?\.?\s*([\d.]+).*?\bto\s+r[se]s?\.?\s*([\d.]+)", re.I)


def price_factor(subject: str) -> Optional[float]:
    """Multiplier for closes before the ex-date, from an NSE corporate-action
    subject. None for actions that don't change the share count (dividends,
    rights, buybacks...)."""
    f = 1.0
    m = _BONUS.search(subject)
    if m and int(m.group(1)) > 0:
        new, held = int(m.group(1)), int(m.group(2))
        f *= held / (new + held)
    if re.search(r"split|sub-?division|consolidat", subject, re.I):
        m = _FACE_VALUE.search(subject)
        if m and float(m.group(1)) > 0:
            f *= float(m.group(2)) / float(m.group(1))
    return None if f == 1.0 else f


def fetch_corporate_actions(start: date, end: date, chunk_days: int = 90) -> list[dict]:
    """Splits / bonus issues / consolidations with ex-dates in [start, end].
    The JSON API needs the cookies NSE sets on its web page first."""
    out: list[dict] = []
    with _client() as c:
        c.headers.update({"Referer": CORP_ACTIONS_PAGE, "Accept": "application/json"})
        c.get(CORP_ACTIONS_PAGE)
        lo = start
        while lo <= end:
            hi = min(end, lo + timedelta(days=chunk_days - 1))
            r = c.get(CORP_ACTIONS_URL.format(f=lo.strftime("%d-%m-%Y"), t=hi.strftime("%d-%m-%Y")))
            r.raise_for_status()
            for row in r.json():
                subject = (row.get("subject") or "").strip()
                factor = price_factor(subject)
                isin = (row.get("isin") or "").strip()
                try:
                    ex = datetime.strptime(row.get("exDate") or "", "%d-%b-%Y").date()
                except ValueError:
                    continue
                if factor and len(isin) == 12:
                    out.append({"isin": isin, "symbol": (row.get("symbol") or "").strip() or None,
                                "ex_date": ex, "subject": subject[:300], "factor": factor})
            lo = hi + timedelta(days=1)
    return out
