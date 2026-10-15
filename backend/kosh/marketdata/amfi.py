"""AMFI mutual fund NAV files (free, published daily)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import httpx

from .. import config

NAV_ALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
NAV_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={frm}&todt={to}"


@dataclass
class NavRow:
    scheme_code: str
    isins: list[str]
    name: str
    nav: float
    nav_date: date
    category: str  # AMFI section header, e.g. 'Open Ended Schemes(Debt Scheme - Liquid Fund)'
    amc: str
    plan: Optional[str]


def _get(url: str) -> str:
    r = httpx.get(url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT},
                  follow_redirects=True)
    r.raise_for_status()
    return r.text


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _plan(name: str, plan_col: str = "") -> Optional[str]:
    t = f"{plan_col} {name}".lower()
    if "direct" in t:
        return "Direct"
    if "regular" in t:
        return "Regular"
    return None


def parse_nav_all(text: str) -> list[NavRow]:
    """NAVAll.txt: 'Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;
    Scheme Name;[Plan;Option;]Net Asset Value;Date' with section headers."""
    rows: list[NavRow] = []
    category, amc = "", ""
    header: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            if "Schemes" in line and "(" in line:
                category = line
            else:
                amc = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if parts[0].lower().startswith("scheme code"):
            header = [p.lower() for p in parts]
            continue
        if not parts[0].isdigit():
            continue
        col = {h: parts[i] if i < len(parts) else "" for i, h in enumerate(header)} if header else {}
        name = col.get("scheme name") or parts[3]
        plan_col, option = col.get("plan", ""), col.get("option", "")
        if plan_col and plan_col.lower() not in name.lower():
            name = f"{name} - {plan_col}"
        if option and option.lower() not in name.lower():
            name = f"{name} - {option}"
        nav_s = col.get("net asset value") or parts[-2]
        d = _parse_date(col.get("date") or parts[-1])
        try:
            nav = float(nav_s)
        except ValueError:
            continue
        if d is None or nav <= 0:
            continue
        isins = [p for p in (parts[1], parts[2]) if p and p != "-" and len(p) == 12]
        if not isins:
            continue
        rows.append(NavRow(parts[0], isins, name, nav, d, category, amc, _plan(name, plan_col)))
    return rows


def parse_nav_history(text: str) -> list[NavRow]:
    """History report: 'Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;
    ISIN Div Reinvestment;Net Asset Value;Date'."""
    rows: list[NavRow] = []
    category, amc = "", ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            if "Schemes" in line and "(" in line:
                category = line
            else:
                amc = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if not parts[0].isdigit() or len(parts) < 8:
            continue
        try:
            nav = float(parts[6])
        except ValueError:
            continue
        d = _parse_date(parts[7])
        isins = [p for p in (parts[4], parts[5]) if p and len(p) == 12]
        if d is None or nav <= 0 or not isins:
            continue
        rows.append(NavRow(parts[0], isins, parts[1], nav, d, category, amc, _plan(parts[1], parts[2])))
    return rows


def fetch_latest() -> list[NavRow]:
    return parse_nav_all(_get(NAV_ALL_URL))


def fetch_history(start: date, end: date) -> list[NavRow]:
    url = NAV_HISTORY_URL.format(frm=start.strftime("%d-%b-%Y"), to=end.strftime("%d-%b-%Y"))
    return parse_nav_history(_get(url))


def previous_navs(latest: Iterable[NavRow], lookback_days: int = 7) -> dict[str, tuple[date, float]]:
    """For each ISIN, the most recent NAV strictly before its latest NAV date."""
    latest = list(latest)
    if not latest:
        return {}
    newest = max(r.nav_date for r in latest)
    hist = fetch_history(newest - timedelta(days=lookback_days), newest)
    cur_date = {i: r.nav_date for r in latest for i in r.isins}
    best: dict[str, tuple[date, float]] = {}
    for r in hist:
        for i in r.isins:
            cd = cur_date.get(i)
            if cd is None or r.nav_date >= cd:
                continue
            if i not in best or r.nav_date > best[i][0]:
                best[i] = (r.nav_date, r.nav)
    return best
