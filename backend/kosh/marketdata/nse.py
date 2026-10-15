"""NSE end-of-day files from nsearchives.nseindia.com (free, published daily).

- Bhavcopy (UDiFF format): every security traded in the cash market, with
  ISIN — equities, ETFs, G-secs, SDLs, T-bills, SGBs, corporate bonds.
- Index closes: Nifty 50, sectoral and debt indices.
- Nifty 500 constituents: industry classification for listed stocks."""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from .. import config

BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
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


def fetch_bhavcopy(d: date, client: Optional[httpx.Client] = None) -> Optional[list[BhavRow]]:
    c = client or _client()
    r = c.get(BHAV_URL.format(d=d.strftime("%Y%m%d")))
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        text = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    return parse_bhavcopy(text)


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


def fetch_index_closes(d: date) -> list[dict]:
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
