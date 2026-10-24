# Kosh

Portfolio review for a mutual fund distributor managing client investments in
Indian markets: one view of each client's holdings, what market moves and news
do to them, and the tax effect of a change before it is made.

- Product specification: [docs/SPEC.md](docs/SPEC.md)
- Status: **showcase MVP**. It runs on one computer and has no login, so use
  it for demos. Don't put real client data on a shared machine.

## Run it on your computer

You need **Python 3.10+** and **Node.js 18+** (Node is only needed to build
the web app once).

```bash
# 1. Backend
cd backend
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
#   .venv\Scripts\Activate.ps1
pip install -e .

# 2. Web app (one time, and again after pulling changes)
cd ../frontend
npm install
npm run build

# 3. Start
cd ../backend
python -m kosh serve
```

The browser opens at <http://127.0.0.1:8000>. On first start Kosh downloads
today's market data from AMFI and NSE (about 30 seconds) and adds eight demo
clients. If the internet is unavailable it falls back to a bundled snapshot.

Other commands (run from `backend/` with the virtualenv active):

| Command | What it does |
|---|---|
| `python -m kosh refresh` | Fetch the latest end-of-day market data (also a button in Settings) |
| `python -m kosh history --years 2` | Store past end-of-day data (also in Settings → Load past history); re-run to resume |
| `python -m kosh seed` | Add the demo clients and sample scenarios |
| `python -m kosh serve --port 8080` | Use another port |

Data is stored in `data/kosh.db` (SQLite; ignored by git). Delete that file to
start again from scratch.

### Stored market data

Every price Kosh fetches is kept in the database, one row per instrument per
trading day. Kosh never fetches prices live while you work: screens read the
stored data.

- **Daily:** while `kosh serve` is running, Kosh refreshes after 7 pm (when
  NSE and AMFI have published) and fills in any trading days it missed while
  the laptop was off. Turn this off with `--no-auto-refresh`.
- **History:** Settings → *Load past history*, or `python -m kosh history`,
  stores past NSE bhavcopies (every listed share, ETF, bond, SGB), NSE index
  closes, AMFI NAVs (every scheme), and NSE's list of splits and bonus issues.
  NSE takes about 3–5 minutes per year. Days already stored are skipped.
- **Size:** NSE is roughly 75 MB per year. AMFI NAVs for every scheme are much
  bigger (several hundred MB per year); use `--sources actions,indices,nse` to
  skip them.
- **Splits and bonus issues:** closing prices are stored as published. Charts
  and day-change figures restate them using NSE's corporate-actions list.
- **Backup:** Settings → *Download database backup* saves a copy of the
  whole database (clients included).

## A five-minute demo

1. **Morning review.** Total value across clients, what moved each client since
   the previous close (real NSE/AMFI prices), the biggest movers, and an events inbox.
2. **Events & impact.** Open *"What if: PSU financiers re-rate 10% lower"*.
   Kosh finds the clients holding those companies' shares *and* bonds, linked
   through the issuer code inside the ISIN. Then click **Log an event** and type
   a real headline, e.g. "RBI cuts repo by 25 bps", modelled as −25 bps on yields.
3. **Scenarios.** Try *Nifty −20%, rates −50 bps* to stress every portfolio at once.
4. **Client → Vikram Rao → What-if planner.** Option A: sell all ITC (bought
   2017). Option B: sell ₹5 L of the balanced advantage fund. Compare tax,
   exit load and the asset mix afterwards, then **Export to Excel**.
5. **Client → Priya Sharma → Tax.** Realised gains this year, the ₹1.25 L
   exemption left, purchases turning long-term in the next 60 days, and the
   cost of selling ₹1 lakh from each holding.
6. **Client → Farhan Qureshi → Holdings.** Demat holdings imported without a
   purchase cost; click one and use **Add cost basis**.
7. **Import statement.** Upload a real CAS PDF and its password. Kosh shows a
   preview with reconciliation before anything is saved.

## Letting a client view it remotely

Kosh has no login, so don't put it on the open internet as-is. This is the
exact recipe used to demo it to a client over a free Cloudflare Tunnel.

**One-time setup:**

```bash
# in the repo root — this file is git-ignored, never commit it
cat > .kosh_auth.env <<'EOF'
KOSH_AUTH_USER=client
KOSH_AUTH_PASS=pick-a-password
EOF

# install cloudflared once, e.g.:
#   https://pkg.cloudflare.com (Linux package), or `brew install cloudflared` (macOS)
```

**Every time you want to demo it:**

```bash
# 1. Start the server with basic auth turned on
cd backend && source .venv/bin/activate
set -a && source ../.kosh_auth.env && set +a
python -m kosh serve --no-browser

# 2. In another terminal, start the tunnel
cloudflared tunnel --url http://127.0.0.1:8000
```

`cloudflared` prints a block containing a `https://<random-words>.trycloudflare.com`
link — that's what you send the client, along with the username/password from
`.kosh_auth.env` (send the credentials over a different channel than wherever
the link itself is public, e.g. don't put the password on a public webpage).

Both processes have to keep running on your machine for the link to work; closing
either one kills it. The URL also changes every time you restart `cloudflared`,
so update any link you've shared (e.g. on a personal site) if you restart it.

**To change the password:** edit `.kosh_auth.env`, then restart the Kosh
server (`Ctrl+C` and re-run step 1) — the tunnel doesn't need restarting,
only the server reads the env vars.

**For a link that doesn't change** each time, use a **named tunnel** instead
(needs a Cloudflare account and a domain you control, with that domain's DNS
on Cloudflare): `cloudflared tunnel login`, `cloudflared tunnel create kosh`,
then `cloudflared tunnel route dns kosh kosh.yourdomain.com` and
`cloudflared tunnel run --url http://127.0.0.1:8000 kosh`.

If you'd rather not depend on your laptop staying on, the same basic-auth +
`python -m kosh serve` setup works unchanged on a small VPS (e.g. a ~$5/mo
Hetzner or DigitalOcean box) — just open port 8000 (or put nginx/Caddy in
front for TLS on a real domain) instead of running a tunnel.

## What's real and what isn't

| | Source |
|---|---|
| Prices, NAVs, previous close | Real: AMFI NAV files and the NSE bhavcopy, end of day |
| Sectors | Real: NSE Nifty 500 / Microcap 250 constituent lists |
| Index strip | Real: NSE index closes |
| Price history (compare up to 5) | Real: stored NSE / AMFI end-of-day data, adjusted for splits and bonus issues |
| G-sec yield curve | Indicative, derived from G-secs traded on NSE that day |
| Demo clients and their purchase prices | Made up (generated from today's price) |
| Sample events | Hypothetical "what if" scenarios, clearly labelled |
| Bond ratings for demo bonds | Entered by hand; there is no ratings feed yet |
| Tax rules | Working model of FY 2025-26 onwards rules; **must be checked by a CA** |

Kosh is positioned as an information and what-if tool for an AMFI-registered
Mutual Fund Distributor. It never recommends a purchase or sale (see
[SPEC §9](docs/SPEC.md#9-compliance-considerations)).

## Code layout

```
backend/kosh/
  marketdata/   AMFI + NSE loaders, history backfill, auto-refresh, yield curve, offline snapshot
  importer/     CAS PDF import (casparser) with preview and reconciliation
  analytics/    FIFO lots, valuation, allocations, bond maths, XIRR
  tax/          versioned capital-gains rules, tax engine, what-if planner
  impact/       events and scenarios → per-client impact
  demo/         demo clients and sample events
  api/          FastAPI app (also serves the built web app) and Excel export
frontend/src/   React web app (built into backend/kosh/web_dist)
```

Run the tests with `cd backend && pip install -e ".[dev]" && pytest`.
During web development, run `python -m kosh serve` and `cd frontend && npm run dev`
(Vite proxies `/api` to port 8000).
