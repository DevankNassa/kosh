# Kosh — notes for Claude

Portfolio review app for an independent financial consultant in India. Kosh shows
each client's holdings, how market moves and news affect them, and the tax effect
of a change before it is made. Full product spec: `docs/SPEC.md`. Setup and demo
script: `README.md`.

## Decisions already made (don't re-open without asking)

- **The consultant is an AMFI-registered Mutual Fund Distributor (MFD), not a
  SEBI RIA.** Kosh is an information / what-if tool and must never recommend a
  buy or sell. UI and export wording: "what-if", "scenario", "impact", "review";
  never "advice", "recommendation" or "adviser". Every page and export carries
  the disclaimer and the ARN (`api/app.py` DISCLAIMER, Settings). The what-if
  planner only models changes the user enters or a target mix the client chose.
- **Holdings come from CAS PDFs** (CAMS/KFintech, NSDL/CDSL) parsed with
  `casparser`. Depository CAS has no purchase cost → "cost unknown" lots, excluded
  from tax until the user adds cost basis in Holdings.
- **Market data: free end-of-day sources** behind loaders in `marketdata/`:
  AMFI NAV files, NSE bhavcopy (equities, ETFs, G-secs, SGBs, corporate bonds),
  NSE index closes and Nifty 500 sector lists. No live feed. A bundled snapshot
  (`marketdata/snapshot/`) keeps the demo working offline.
- **Corporate bonds:** priced from NSE trades, else a model (indicative G-sec
  curve derived from NSE trades + rating spread). Buy a CRISIL/ICRA valuation
  feed only if model-priced corporate bonds exceed ~10% of the book (SPEC §5.5).
- **Unknowns:** which brokers clients use, and how much is in corporate bonds.
  Kosh will measure these from real imports.
- Runs locally on the consultant's laptop (showcase MVP): single user, no login.

## Layout

```
backend/kosh/
  models.py        tables; transactions are the source of truth, lots are derived
  marketdata/      amfi.py, nse.py, curve.py, refresh.py (+ snapshot/)
  importer/cas.py  CAS → preview (savepoint, nothing saved) → commit; dedupe keys make re-import safe
  analytics/       portfolio.py (FIFO lots, PriceBook, holdings, allocations), bonds.py, classify.py, xirr.py
  tax/             rules.py (versioned by transfer date), engine.py (set-off, 112A exemption, surcharge, cess), planner.py (what-if)
  impact/shocks.py events/scenarios as "shocks" → per-client impact
  demo/seed.py     8 fictional demo clients holding real instruments; sample "what if" events
  api/app.py       FastAPI; also serves the built web app from kosh/web_dist
frontend/src/      React + Vite + TS; pages/ and components/; builds into backend/kosh/web_dist
```

## Commands

```bash
cd backend && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
python -m kosh serve        # app at http://127.0.0.1:8000 (first run fetches data + seeds demo)
python -m kosh refresh      # fetch latest market data
pytest                      # backend tests (pip install -e ".[dev]" first)
cd frontend && npm run build    # type-check + build web app (re-run after frontend changes)
cd frontend && npm run dev      # dev server with /api proxied to :8000
```

## Conventions

- Indian formatting: ₹ with lakh/crore (`frontend/src/format.ts`), FY April–March.
- Tax rules live as data in `tax/rules.py` with effective dates. Add a new
  `RuleSet` for a Budget change rather than editing old ones. All tax output is
  labelled an estimate; rules still need a CA's review.
- Chart colours: asset classes use fixed slots (equity blue, debt orange, hybrid
  aqua, gold yellow, other magenta) defined as CSS tokens in `styles.css`, with
  light and dark values. Colour follows the asset class, never its rank.
- Keep the backend tests passing; add a test with any tax or import change.

## Privacy

`data/` (SQLite DB) and `*.pdf` are git-ignored. Don't open real client CAS
PDFs or `data/kosh.db`; ask the user for error messages instead.

## Status and next steps

Built: market data, CAS import, portfolio views, tax view, what-if planner with
Excel export, events/scenarios, demo data. 22 tests pass. Not yet verified with
a real CAS PDF.

Likely next:
1. Test import with the user's real CAS; fix parsing/mapping issues.
2. Generic tradebook CSV import for demat cost basis (SPEC F2.6), then
   broker-specific parsers once imports show which brokers clients use.
3. CA review of `tax/rules.py` (30+ worked examples, SPEC milestone M3).
4. Later: MF portfolio look-through, RTA distributor feeds, alerts, login/roles
   if staff will use it, ESOP/RSU module (SPEC §7.4).
