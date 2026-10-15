"""Command line: `python -m kosh <command>`.

  serve      start the app (first run: loads market data and demo clients)
  refresh    fetch today's market data
  seed       add the demo clients and sample scenarios
  snapshot   save market data for the demo instruments (offline fallback)
"""

import argparse
import json
import logging
import webbrowser

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
    sub.add_parser("refresh")
    sub.add_parser("seed")
    sub.add_parser("snapshot")
    args = ap.parse_args()
    init_db()

    if args.cmd in (None, "serve"):
        import uvicorn

        _first_run_setup()
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        url = f"http://{host}:{port}"
        print(f"\nKosh is running at {url}  (press Ctrl+C to stop)\n")
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


if __name__ == "__main__":
    main()
