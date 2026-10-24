"""Background market-data work while `kosh serve` runs:

- a history load started from Settings (backfill.backfill_history in a thread,
  with progress the page polls), and
- the automatic daily refresh: once the day's end-of-day files are out (after
  REFRESH_AFTER_HOUR, local time), refresh and fill any trading days missed
  while the laptop was off.

Only one of these runs at a time."""

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from .. import settings_store
from ..db import session_scope

log = logging.getLogger(__name__)

REFRESH_AFTER_HOUR = 19  # NSE/AMFI files are usually out by ~6-7pm IST
CHECK_EVERY_SECONDS = 30 * 60

_busy = threading.Lock()
_stop = threading.Event()
_progress: dict = {}


def history_status() -> dict:
    """Live progress while a load runs, else the last finished load."""
    if _progress.get("running"):
        return dict(_progress)
    with session_scope() as s:
        return settings_store.get(s, "history_status") or {"running": False}


def start_history(start: date, end: date, sources: Optional[list[str]] = None) -> bool:
    """Start loading [start, end] in the background. False if a job is running."""
    if not _busy.acquire(blocking=False):
        return False
    _stop.clear()
    _progress.clear()
    _progress.update(running=True, start=start, end=end, done=0, total=None, source=None, date=None,
                     started=datetime.now().isoformat(timespec="seconds"))
    threading.Thread(target=_run_history, args=(start, end, sources), daemon=True, name="kosh-history").start()
    return True


def stop_history() -> None:
    _stop.set()


def _run_history(start: date, end: date, sources: Optional[list[str]]) -> None:
    from ..models import audit
    from .backfill import SOURCES, backfill_history

    result: dict = {}
    try:
        with session_scope() as s:
            result = backfill_history(s, start, end, sources=sources or SOURCES,
                                      progress=_progress.update, should_stop=_stop.is_set)
    except Exception as e:
        log.exception("history load failed")
        result = {"error": str(e)[:300]}
    finally:
        final = {**_progress, **result, "running": False,
                 "finished": datetime.now().isoformat(timespec="seconds")}
        try:
            with session_scope() as s:
                settings_store.put(s, "history_status", final)
                audit(s, "market_history_load", None, start=str(start), end=str(end),
                      stopped=bool(result.get("stopped")), error=result.get("error"))
        except Exception:
            log.exception("could not save history status")
        _progress.clear()
        _busy.release()


# ---------------------------------------------------------------- daily refresh

def refresh_due(last: Optional[dict], now: Optional[datetime] = None) -> bool:
    """True if no refresh has run since the most recent REFRESH_AFTER_HOUR,
    or the last one failed (e.g. offline) more than an hour ago."""
    now = now or datetime.now()
    publish = now.replace(hour=REFRESH_AFTER_HOUR, minute=0, second=0, microsecond=0)
    if now < publish:
        publish -= timedelta(days=1)
    try:
        finished = datetime.fromisoformat((last or {})["finished"])
    except (KeyError, TypeError, ValueError):
        return True
    if finished < publish:
        return True
    failed = not ((last.get("nse") or {}).get("ok") and (last.get("amfi") or {}).get("ok"))
    return failed and now - finished > timedelta(hours=1)


def auto_refresh_once(now: Optional[datetime] = None) -> Optional[dict]:
    """Refresh + catch up if due and nothing else is running."""
    from ..models import audit
    from .backfill import catch_up
    from .refresh import refresh_market_data

    with session_scope() as s:
        last = settings_store.get(s, "market_status")
    if not refresh_due(last, now) or not _busy.acquire(blocking=False):
        return None
    try:
        with session_scope() as s:
            st = refresh_market_data(s)
            st["catch_up"] = catch_up(s, (now or datetime.now()).date())
            settings_store.put(s, "market_status", st)
            audit(s, "market_refresh", None, auto=True,
                  ok={k: v.get("ok") for k, v in st.items() if isinstance(v, dict) and "ok" in v})
        return st
    except Exception:
        log.exception("automatic refresh failed")
        return None
    finally:
        _busy.release()


def start_scheduler() -> None:
    def loop():
        _stop_wait = threading.Event()
        _stop_wait.wait(60)  # let the server start first
        while True:
            try:
                if auto_refresh_once():
                    log.info("automatic market data refresh done")
            except Exception:
                log.exception("scheduler tick failed")
            _stop_wait.wait(CHECK_EVERY_SECONDS)

    threading.Thread(target=loop, daemon=True, name="kosh-auto-refresh").start()
