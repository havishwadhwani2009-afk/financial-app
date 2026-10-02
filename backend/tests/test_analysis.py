from datetime import date

import pandas as pd
import pytest

from app.analysis import fundamentals as fa
from app.analysis import macro as ma
from app.models import Fundamental, Instrument, MacroObservation, Price


def _fact(i, concept, end, val, filed, start=None, unit="USD", acc="a1", form="10-K"):
    return Fundamental(instrument_id=i, concept=concept, source_tag="t:" + concept,
                       period_start=start or (date(end.year - 1, end.month, end.day) if concept not in
                                              fa.STOCK else None), period_end=end, filed=filed, accession=acc,
                       value=val, unit=unit, provider="test", form=form, fiscal_period="FY")


@pytest.fixture()
def co(db):
    i = Instrument(symbol="TCO", exchange="US", instrument_type="stock")
    db.add(i)
    db.commit()
    e1, e2 = date(2022, 12, 31), date(2023, 12, 31)
    for end, filed, rev, ni, eq, cfo, capex in [(e1, date(2023, 2, 1), 100.0, 10.0, 50.0, 20.0, 5.0),
                                                (e2, date(2024, 2, 1), 120.0, 15.0, 60.0, 30.0, 10.0)]:
        for c, v in (("revenue", rev), ("net_income", ni), ("equity", eq), ("cfo", cfo), ("capex", capex),
                     ("gross_profit", rev * 0.4), ("debt_long_term", 30.0), ("cash", 10.0), ("eps_diluted", ni / 10)):
            unit = "USD/shares" if c == "eps_diluted" else "USD"
            db.add(_fact(i.id, c, end, v, filed, unit=unit, acc=f"acc{end.year}"))
    db.add(Fundamental(instrument_id=i.id, concept="shares_outstanding", source_tag="dei:x", period_end=date(2024, 1, 20),
                       filed=date(2024, 2, 1), accession="acc2023", value=10.0, unit="shares", provider="test", form="10-K"))
    db.add(Price(instrument_id=i.id, date=date(2024, 3, 1), provider="test", close=30.0, adj_close=30.0))
    db.commit()
    return i


def test_ratios_and_definitions(db, co):
    m = fa.annual_metrics(db, co.id)
    last = m["periods"][-1]
    assert last["metrics"]["revenue_growth"] == pytest.approx(0.2)
    assert last["metrics"]["net_income_growth"] == pytest.approx(0.5)
    assert last["metrics"]["gross_margin"] == pytest.approx(0.4)
    assert last["metrics"]["fcf"] == pytest.approx(20.0)
    assert last["metrics"]["roe"] == pytest.approx(15 / 55)
    assert last["metrics"]["debt_to_equity"] == pytest.approx(0.5)
    assert last["metrics"]["interest_coverage"] is None      # inputs missing -> not computed
    assert "revenue_growth" in m["definitions"] and last["publicly_available_from"] == "2024-02-01"


def test_point_in_time_view_hides_later_filings(db, co):
    m = fa.annual_metrics(db, co.id, as_of=date(2023, 6, 1))
    assert [p["period_end"] for p in m["periods"]] == ["2022-12-31"]


def test_restatement_uses_latest_filing_and_flags(db, co):
    db.add(_fact(co.id, "revenue", date(2023, 12, 31), 125.0, date(2024, 8, 1), acc="acc-restated", form="10-K/A"))
    db.commit()
    p = fa.annual_metrics(db, co.id)["periods"][-1]
    assert p["values"]["revenue"] == 125.0 and p["restated"] is True


def test_non_usd_facts_excluded_not_mixed(db, co):
    db.add(_fact(co.id, "revenue", date(2023, 12, 31), 999.0, date(2024, 3, 1), unit="EUR", acc="eur"))
    db.commit()
    m = fa.annual_metrics(db, co.id)
    assert m["periods"][-1]["values"]["revenue"] == 120.0 and any("non-USD" in w for w in m["warnings"])


def test_valuation(db, co):
    v = fa.valuation(db, co.id)
    assert v["market_cap"] == pytest.approx(300.0)
    assert v["pe"] == pytest.approx(30.0 / 1.5)
    assert v["ps"] == pytest.approx(300 / 120) and v["fcf_yield"] == pytest.approx(20 / 300)
    assert v["ev_revenue"] == pytest.approx((300 + 30 - 10) / 120)


def test_macro_pillars_are_point_in_time_and_disclose_missing(db):
    from app.models import MacroSeries
    db.add(MacroSeries(series_id="VIXCLS", title="VIX", category="volatility", provider="fred", assumed_lag_days=1))
    db.commit()
    days = pd.bdate_range("2014-01-01", "2024-06-28")
    vals = [15.0] * (len(days) - 1) + [40.0]
    db.execute(MacroObservation.__table__.insert(), [
        dict(series_id="VIXCLS", observation_date=d.date(), published_date=d.date(), value=v,
             pit_quality="vintage", provider="fred") for d, v in zip(days, vals)])
    db.commit()
    now = ma.pillar_scores(db, date(2024, 6, 28))["pillars"]
    assert now["volatility"]["label"] == "elevated" and now["volatility"]["score"] > 3
    before = ma.pillar_scores(db, date(2024, 6, 27))["pillars"]
    assert before["volatility"]["score"] is None or before["volatility"]["score"] < 1  # spike not yet published
    assert now["liquidity"]["score"] is None and all(i["status"] == "missing" for i in now["liquidity"]["inputs"])
