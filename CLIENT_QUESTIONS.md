# Questions for the client

Open questions to go through with the consultant. Record answers here (or in
the relevant spec) and strike out a question once it is answered. Numbers
refer to the spec each question comes from.

---

## 1. Past similar events ("Precedents"), see `docs/SPEC-precedents.md`

| # | Question | Why we need to know |
|---|---|---|
| P1 | Is it acceptable for Kosh to show **what happened after past similar events, compared with how often that happens normally** ("lower in 7 of 9 past events; normally lower 46% of the time"), rather than a **probability of what will happen**? | As an MFD he can't show forecasts or anything that reads like advice. This also changes a decision already recorded in SPEC F5. |
| P2 | Is this view **only for him**, or will he show it to clients (on screen in meetings, or in exports)? | If clients will see it, the wording must be reviewed by a compliance professional first. |
| P3 | What kinds of news does he react to most often: RBI or Fed rate decisions, the Union Budget, oil prices or geopolitics, a company or business-group shock, rating actions, elections, SEBI or RBI regulation? | Tells us which event types to add to the library first. |
| P4 | Over what period does he want to see what happened: the next day, a week, a month? | Sets the horizons Kosh measures. |
| P5 | When he says "families of stocks", does he mean sectors (IT, banks, oil & gas), market cap (large, mid, small), asset classes (equity, debt, gold), or mutual fund categories (small-cap funds, gilt funds…)? | Mutual fund categories are probably the most useful for his book, but they need more data work first. |
| P6 | Does he also want to see how the **individual stocks and funds his clients hold** behaved after past events, or only families? | Individual holdings have more noise and less history. |
| P7 | Who will build and look after the library of past events? Would he spend an hour or two once to review or tag a list of past events that we prepare? | The quality of the library limits how useful the feature is. |
| P8 | Is history **from 2020** enough, or does he want older episodes (2008 crisis, 2013 taper tantrum, 2016 demonetisation, 2020 COVID)? | Free NSE files before 2020 may be missing or in other formats. Older history might need paid data. |
| P9 | When a new event comes in, should Kosh **alert** him (and how: in the app, by email, on WhatsApp), or is it enough to see it in the event list when he opens Kosh? | Affects whether this connects to alerts (SPEC F7). |
| P10 | Where does he hear about news today (which websites, apps, newsletters, WhatsApp groups)? | Tells us which feeds are worth automating later. |
| P11 | Some event types need data we don't store yet, e.g. a crude oil price series to spot oil shocks automatically. Is a small paid data source acceptable, or should we stay at ₹0 and keep those events hand-curated? | Budget (SPEC §5.5) is ₹0 per month for data today. |

---

## 2. Still open from the main spec (`docs/SPEC.md` §12)

| # | Question | Why we need to know |
|---|---|---|
| Q2 | How many clients does he have, and roughly how many holdings per client? | Performance, and how far the laptop setup will stretch |
| Q5 | Does he need holdings that aren't in a CAS (FDs, PPF, NPS, PMS, AIFs, insurance, real estate) entered by hand? | Scope of client and portfolio screens |
| Q6 | Does he have NRI clients? How many? | NRI tax rules are different and not built yet |
| Q7 | Will his staff use Kosh? | Login and roles (not built; single user today) |
| Q8 | Which reports does he share with clients today, and in what format (PDF, Excel, printed)? Can he share a sample with names removed? | Export design |
| Q9 | Will it stay on his laptop, or does he want it hosted? Any budget for hosting? | Architecture |
| Q10 | How do his clients invest in bonds and stocks: through him as an Authorised Person of a broker, via an online bond platform, or on their own? | How non-MF holdings are described in exports |
| Q11 | Does he want commission/trail tracking by ARN (AUM under his ARN vs bought direct or through others)? | Possible feature using distributor feeds |

---

## 3. Other things to confirm

| # | Question | Why we need to know |
|---|---|---|
| O1 | Can he run an import with **one real CAS** (CAMS/KFintech and NSDL/CDSL) on his laptop and send us any error messages or wrong numbers? We won't open the PDF ourselves. | Import hasn't been tested on a real CAS yet. This is the next step. |
| O2 | Which **CA** will review the tax rules and the 30+ worked examples? When are they available? | Tax output is only an estimate until a CA signs it off (milestone M3). |
| O3 | Does he have a **compliance professional** to review the disclaimer and the wording on screens and exports? | Required by SPEC §9.1, and for P1/P2 above. |
| O4 | For shares held in demat (no purchase cost in the CAS), will he or his clients enter cost by hand, or can they get **tradebooks / contract notes** from their brokers? From which brokers? | Decides whether we build the tradebook import (SPEC F2.6) next. |
| O5 | What is his **ARN** and the exact name to print on exports? | Required on every page and export. |
| O6 | Is a mostly accurate **model price** acceptable for corporate bonds that rarely trade, or does he need vendor (CRISIL/ICRA) prices? | Feeds the paid bond-feed decision (SPEC §5.5). |
| O7 | Laptop: Windows or Mac? Is it backed up? Is it OK for Kosh to fetch market data in the background after 7 pm while it is open? | Install steps, backups of `data/kosh.db`, and the daily auto-refresh. |
