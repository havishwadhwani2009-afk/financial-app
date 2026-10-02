import json
from datetime import date

import pytest

from app.providers import fred, sec_edgar, stooq, yahoo
from app.providers.base import ProviderError

YAHOO = {"chart": {"error": None, "result": [{
    "meta": {"longName": "Test Corp", "currency": "USD", "exchangeName": "NMS", "gmtoffset": -18000,
             "instrumentType": "EQUITY", "regularMarketTime": 1700000000},
    "timestamp": [1699972200, 1700058600, 1700145000, 1700145001],
    "events": {"dividends": {"1700058600": {"amount": 0.24, "date": 1700058600}},
               "splits": {"1700145000": {"date": 1700145000, "numerator": 4, "denominator": 1}}},
    "indicators": {"quote": [{"open": [1, 2, None, 4], "high": [2, 3, None, 5], "low": [1, 1, None, 3],
                              "close": [1.5, 2.5, None, 4.5], "volume": [100, 200, None, 400]}],
                   "adjclose": [{"adjclose": [1.4, 2.4, None, 4.4]}]}}]}}


def test_yahoo_parse_rejects_null_close_and_parses_events():
    r = yahoo.parse_chart("TST", YAHOO)
    assert [b.close for b in r.bars] == [1.5, 2.5, 4.5]
    assert r.rejected == 1
    assert r.meta["name"] == "Test Corp" and r.meta["currency"] == "USD"
    kinds = {a.action_type: a.value for a in r.actions}
    assert kinds == {"dividend": 0.24, "split": 4.0}
    assert r.bars[0].adj_close == 1.4


def test_yahoo_error_payload_raises():
    with pytest.raises(ProviderError):
        yahoo.parse_chart("X", {"chart": {"error": {"code": "Not Found"}, "result": None}})


def test_stooq_parse_and_html_rejected():
    csv_text = "Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,1,1.5,100\n2024-01-03,x,2,1,1.5,100\n"
    r = stooq.parse_csv("TST", csv_text)
    assert len(r.bars) == 1 and r.rejected == 1 and r.bars[0].adj_close is None
    with pytest.raises(ProviderError):
        stooq.parse_csv("TST", "<html>blocked</html>")


def test_fred_csv_marks_assumed_lag_and_drops_missing():
    text = "observation_date,CPIAUCSL\n2024-01-01,300.1\n2024-02-01,.\n2024-03-01,301.5\n"
    r = fred.parse_csv("CPIAUCSL", text, 45)
    assert len(r.points) == 2 and r.rejected == 1
    assert r.points[0].pit_quality == "assumed_lag"
    assert (r.points[0].published_date - r.points[0].observation_date).days == 45


def test_fred_api_vintage_publication_date():
    payload = {"observations": [{"date": "2024-01-01", "realtime_start": "2024-02-13", "value": "300.1"},
                                {"date": "2024-01-01", "realtime_start": "2024-03-12", "value": "300.4"}]}
    r = fred.parse_api("CPIAUCSL", payload)
    assert [p.published_date for p in r.points] == [date(2024, 2, 13), date(2024, 3, 12)]
    assert all(p.pit_quality == "vintage" for p in r.points)
    with pytest.raises(ProviderError):
        fred.parse_api("X", {"error_message": "Bad Request"})


SEC = {"cik": 320193, "entityName": "Test Inc", "facts": {
    "us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2022-10-01", "end": "2023-09-30", "val": 383, "accn": "0000320193-23-000106", "fy": 2023,
         "fp": "FY", "form": "10-K", "filed": "2023-11-03"},
        {"start": "2022-10-01", "end": "2023-09-30", "val": 1, "accn": "x", "fy": 2023, "fp": "FY",
         "form": "8-K", "filed": "2023-11-03"}]}}},
    "dei": {}}}


def test_sec_facts_normalised_with_filed_date_and_form_filter():
    r = sec_edgar.parse_company_facts("TST", SEC)
    assert r.cik == "0000320193" and len(r.facts) == 1
    f = r.facts[0]
    assert f.concept == "revenue" and f.filed == date(2023, 11, 3) and f.period_end == date(2023, 9, 30)


def test_sec_ticker_map_pads_cik():
    m = sec_edgar.parse_ticker_map({"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."}})
    assert m["AAPL"]["cik"] == "0000320193"
