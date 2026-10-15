from datetime import date

import pytest

from kosh.tax import rules
from kosh.tax.engine import TaxProfile, compute_tax

D = date(2026, 10, 15)


def test_equity_holding_period_boundary():
    acq = date(2025, 10, 15)
    # exactly 12 months is not "more than 12 months"
    assert rules.bucket_for("equity", acq, date(2026, 10, 15)) == rules.STCG_111A
    assert rules.bucket_for("equity", acq, date(2026, 10, 16)) == rules.LTCG_112A


def test_specified_debt_after_april_2023_is_always_slab():
    assert rules.bucket_for("specified_debt", date(2023, 4, 1), D) == rules.SLAB_50AA
    assert rules.long_term_from("specified_debt", date(2023, 5, 1), D) is None


def test_debt_fund_bought_before_april_2023_is_long_term_after_24_months():
    assert rules.bucket_for("specified_debt", date(2022, 6, 1), D) == rules.LTCG_112
    assert rules.bucket_for("specified_debt", date(2025, 6, 1), D) == rules.SLAB_50AA


def test_listed_bond_and_unlisted_bond():
    assert rules.bucket_for("listed_other", date(2025, 1, 1), D) == rules.LTCG_112
    assert rules.bucket_for("listed_other", date(2026, 1, 1), D) == rules.STCG_SLAB
    assert rules.bucket_for("unlisted_bond", date(2015, 1, 1), D) == rules.SLAB_50AA


def test_older_ruleset_rates():
    rs = rules.ruleset_for(date(2024, 1, 10))
    assert rs.equity_stcg_rate == 0.15 and rs.equity_ltcg_exemption == 100_000
    assert rules.ruleset_for(date(2024, 7, 23)).equity_stcg_rate == 0.20


def test_fy_labels():
    assert rules.fy_of(date(2026, 3, 31)) == "FY 2025-26"
    assert rules.fy_of(date(2026, 4, 1)) == "FY 2026-27"


def test_ltcg_exemption_and_rates():
    r = compute_tax({rules.LTCG_112A: 200_000, rules.STCG_111A: 50_000}, TaxProfile(slab_rate=0.3), D)
    assert r.exemption_used == 125_000
    base = 75_000 * 0.125 + 50_000 * 0.20
    assert r.total == pytest.approx(base * 1.04)


def test_lt_loss_only_against_lt_gains():
    r = compute_tax({rules.LTCG_112A: -50_000, rules.STCG_111A: 100_000}, TaxProfile(), D)
    assert r.after_setoff[rules.STCG_111A] == 100_000
    assert r.unabsorbed_ltcl == 50_000


def test_st_loss_goes_to_highest_rate_first():
    prof = TaxProfile(slab_rate=0.30)
    r = compute_tax({rules.STCG_111A: -40_000, rules.SLAB_50AA: 40_000, rules.LTCG_112A: 40_000}, prof, D)
    assert r.after_setoff[rules.SLAB_50AA] == 0
    assert r.after_setoff[rules.LTCG_112A] == 40_000
    assert r.total == 0  # LTCG within exemption


def test_carried_forward_losses_and_surcharge_cap():
    prof = TaxProfile(slab_rate=0.3, surcharge_rate=0.25, cf_ltcl=25_000)
    r = compute_tax({rules.LTCG_112A: 250_000}, prof, D)
    taxable = 250_000 - 25_000 - 125_000
    assert r.taxable[rules.LTCG_112A] == taxable
    assert r.surcharge == pytest.approx(taxable * 0.125 * 0.15)  # capped at 15%
