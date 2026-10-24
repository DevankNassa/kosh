"""Command line: `python -m kosh <command>`.

  serve             start the app (first run: loads market data and demo clients)
  refresh            fetch today's market data
  seed               add the demo clients and sample scenarios
  snapshot           save market data for the demo instruments (offline fallback)
  history            store past end-of-day data (NSE securities + indices, AMFI NAVs)
                     e.g. `history --years 2`; days already stored are skipped
  backfill-indices   fetch historical sector/benchmark index closes for a date range
"""

import argparse
import json
import logging
import webbrowser
from datetime import date

from sqlalchemy import func, select

from .db import init_db, session_scope


def _first_run_setup() -> None:
    from .demo.seed import seed_demo
    from .marketdata.refresh import refresh_market_data
    from .models import Client, Instrument

    with session_scope() as s:
        if s.scalar(select(func.count(Instrument.isin))) == 0:
            print("First run: loading market data from AMFI and NSE (about 30 seconds)...")
            st = refresh_market_data(s)
            for k in ("amfi", "nse", "snapshot"):
                if k in st:
                    print(f"  {k}: {'ok' if st[k].get('ok') else 'failed'} {st[k].get('asof') or st[k].get('error') or ''}")
        if s.scalar(select(func.count(Client.id))) == 0:
            print("Adding demo clients...")
            seed_demo(s)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="kosh")
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("serve")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--no-browser", action="store_true")
    sp.add_argument("--reload", action="store_true")
    sp.add_argument("--no-auto-refresh", action="store_true",
                    help="don't refresh market data automatically each evening")
    sub.add_parser("refresh")
    sub.add_parser("seed")
    sub.add_parser("snapshot")
    hp = sub.add_parser("history")
    hp.add_argument("--years", type=float, default=1.0)
    hp.add_argument("--from", dest="start", help="YYYY-MM-DD (overrides --years)")
    hp.add_argument("--to", dest="end", help="YYYY-MM-DD (default today)")
    hp.add_argument("--sources", default="indices,nse,amfi", help="comma-separated: indices,nse,amfi")
    bp = sub.add_parser("backfill-indices")
    bp.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    bp.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()
    init_db()

    if args.cmd in (None, "serve"):
        import uvicorn

        _first_run_setup()
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        url = f"http://{host}:{port}"
        print(f"\nKosh is running at {url}  (press Ctrl+C to stop)\n")
        from . import config
        if not (config.AUTH_USER and config.AUTH_PASS):
            print("No KOSH_AUTH_USER/KOSH_AUTH_PASS set — fine for localhost, but set them "
                  "before exposing this over a tunnel or public URL.\n")
        if not getattr(args, "no_auto_refresh", False):
            from .marketdata.jobs import REFRESH_AFTER_HOUR, start_scheduler
            start_scheduler()
            print(f"Market data refreshes automatically after {REFRESH_AFTER_HOUR}:00 each day "
                  "while Kosh is running.\n")
        if not getattr(args, "no_browser", False):
            try:
                webbrowser.open(url)
            except Exception:
                pass
        uvicorn.run("kosh.api.app:app", host=host, port=port, reload=getattr(args, "reload", False),
                    log_level="warning")
    elif args.cmd == "refresh":
        from .marketdata.refresh import refresh_market_data
        with session_scope() as s:
            print(json.dumps(refresh_market_data(s), indent=1, default=str))
    elif args.cmd == "history":
        from datetime import timedelta

        from .marketdata.backfill import backfill_history
        end = date.fromisoformat(args.end) if args.end else date.today()
        start = date.fromisoformat(args.start) if args.start else end - timedelta(days=round(365 * args.years))
        last = [0.0]

        def show(p):
            import time
            if p["total"] and (time.time() - last[0] > 2 or p["done"] == p["total"]):
                last[0] = time.time()
                print(f"  {p['done']}/{p['total']}  {p['source'] or 'done'} {p['date'] or ''}", flush=True)

        print(f"Storing market history {start} → {end} (Ctrl+C to stop; re-run to resume)")
        with session_scope() as s:
            print(json.dumps(backfill_history(s, start, end, sources=args.sources.split(","), progress=show),
                             indent=1, default=str))
    elif args.cmd == "seed":
        from .demo.seed import seed_demo
        with session_scope() as s:
            print(seed_demo(s))
    elif args.cmd == "snapshot":
        from .demo.seed import BONDS, EQ, MF
        from .marketdata.refresh import write_snapshot
        with session_scope() as s:
            write_snapshot(s, set(MF.values()) | set(EQ.values()) | set(BONDS.values()))
        print("Snapshot written")
    elif args.cmd == "backfill-indices":
        from .analytics.classify import BROAD_MARKET_INDEX, SECTOR_INDEX
        from .marketdata.backfill import backfill_indices
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        names = sorted(set(SECTOR_INDEX.values()) | {BROAD_MARKET_INDEX})
        with session_scope() as s:
            print(json.dumps(backfill_indices(s, names, start, end)))


if __name__ == "__main__":
    main()
