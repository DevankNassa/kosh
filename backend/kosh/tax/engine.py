"""Tax computation on realised capital gains for one client and one FY:
loss set-off, the s.112A exemption, surcharge and cess."""

from dataclasses import dataclass, field
from datetime import date

from .rules import (
    BUCKET_LABELS,
    LONG_BUCKETS,
    LTCG_112,
    LTCG_112A,
    SHORT_BUCKETS,
    SLAB_50AA,
    STCG_111A,
    STCG_SLAB,
    bucket_rate,
    ruleset_for,
)

ALL_BUCKETS = (STCG_111A, LTCG_112A, STCG_SLAB, LTCG_112, SLAB_50AA)


@dataclass
class TaxProfile:
    slab_rate: float = 0.30
    surcharge_rate: float = 0.0
    cf_stcl: float = 0.0  # carried-forward short-term loss (positive number)
    cf_ltcl: float = 0.0  # carried-forward long-term loss (positive number)


@dataclass
class TaxResult:
    gross: dict[str, float]          # net gain/loss per bucket before set-off
    after_setoff: dict[str, float]   # per bucket after loss set-off
    exemption_used: float
    exemption_remaining: float
    taxable: dict[str, float]        # after exemption
    tax: dict[str, float]            # base tax per bucket
    surcharge: float
    cess: float
    total: float
    unabsorbed_stcl: float
    unabsorbed_ltcl: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "buckets": [
                {
                    "bucket": b,
                    "label": BUCKET_LABELS[b],
                    "gross": round(self.gross.get(b, 0.0), 2),
                    "after_setoff": round(self.after_setoff.get(b, 0.0), 2),
                    "taxable": round(self.taxable.get(b, 0.0), 2),
                    "tax": round(self.tax.get(b, 0.0), 2),
                }
                for b in ALL_BUCKETS
            ],
            "exemption_used": round(self.exemption_used, 2),
            "exemption_remaining": round(self.exemption_remaining, 2),
            "surcharge": round(self.surcharge, 2),
            "cess": round(self.cess, 2),
            "total": round(self.total, 2),
            "unabsorbed_stcl": round(self.unabsorbed_stcl, 2),
            "unabsorbed_ltcl": round(self.unabsorbed_ltcl, 2),
            "notes": self.notes,
        }


def compute_tax(gains: dict[str, float], profile: TaxProfile, on: date) -> TaxResult:
    """`gains`: net realised gain (negative = loss) per bucket for the FY."""
    rs = ruleset_for(on)
    gross = {b: float(gains.get(b, 0.0)) for b in ALL_BUCKETS}
    pos = {b: max(0.0, v) for b, v in gross.items()}
    st_loss = sum(-v for b, v in gross.items() if b in SHORT_BUCKETS and v < 0) + profile.cf_stcl
    lt_loss = sum(-v for b, v in gross.items() if b in LONG_BUCKETS and v < 0) + profile.cf_ltcl

    def rate(b: str) -> float:
        return bucket_rate(b, profile.slab_rate, rs)

    # Long-term losses can only reduce long-term gains. Use them first on
    # s.112 gains, then s.112A gains (whose first ₹1.25L is exempt anyway).
    for b in (LTCG_112, LTCG_112A):
        use = min(lt_loss, pos[b])
        pos[b] -= use
        lt_loss -= use

    # Short-term losses can reduce any gain: apply to the highest-taxed first;
    # among equal rates, keep s.112A last so the exemption is not wasted.
    order = sorted(ALL_BUCKETS, key=lambda b: (-rate(b), b == LTCG_112A))
    for b in order:
        use = min(st_loss, pos[b])
        pos[b] -= use
        st_loss -= use

    exemption = rs.equity_ltcg_exemption
    exemption_used = min(exemption, pos[LTCG_112A])
    taxable = dict(pos)
    taxable[LTCG_112A] = pos[LTCG_112A] - exemption_used

    tax = {b: taxable[b] * rate(b) for b in ALL_BUCKETS}
    capped = min(profile.surcharge_rate, rs.special_surcharge_cap)
    surcharge = 0.0
    for b, t in tax.items():
        surcharge += t * (capped if b in (STCG_111A, LTCG_112A, LTCG_112) else profile.surcharge_rate)
    base = sum(tax.values())
    cess = (base + surcharge) * rs.cess

    notes = []
    if rs.note:
        notes.append(rs.note)
    if taxable[STCG_SLAB] or taxable[SLAB_50AA]:
        notes.append(f"Slab-rate gains use the client's marginal rate of {profile.slab_rate:.0%}.")
    return TaxResult(
        gross=gross, after_setoff=pos, exemption_used=exemption_used,
        exemption_remaining=exemption - exemption_used, taxable=taxable, tax=tax,
        surcharge=surcharge, cess=cess, total=base + surcharge + cess,
        unabsorbed_stcl=st_loss, unabsorbed_ltcl=lt_loss, notes=notes,
    )
