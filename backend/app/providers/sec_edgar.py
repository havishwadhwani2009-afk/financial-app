"""SEC EDGAR: ticker->CIK map, XBRL company facts (official, US filers only).

SEC requires a descriptive User-Agent with contact details (set SEC_USER_AGENT) and asks for <=10 req/s.
Every fact carries its `filed` date, which we store as the public-availability date.
"""
from __future__ import annotations

import time
from datetime import date

from app.config import get_settings
from app.providers.base import FactRecord, FundamentalsResult, ProviderError, http_get

NAME = "sec_edgar"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# normalised concept -> ordered candidate (taxonomy, tag). First tag with data wins per period-end.
CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "revenue": [("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "Revenues"), ("us-gaap", "SalesRevenueNet")],
    "gross_profit": [("us-gaap", "GrossProfit")],
    "operating_income": [("us-gaap", "OperatingIncomeLoss")],
    "net_income": [("us-gaap", "NetIncomeLoss")],
    "eps_diluted": [("us-gaap", "EarningsPerShareDiluted")],
    "cfo": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities")],
    "capex": [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
              ("us-gaap", "PaymentsToAcquireProductiveAssets")],
    "total_assets": [("us-gaap", "Assets")],
    "total_liabilities": [("us-gaap", "Liabilities")],
    "equity": [("us-gaap", "StockholdersEquity")],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue")],
    "debt_long_term": [("us-gaap", "LongTermDebtNoncurrent"), ("us-gaap", "LongTermDebt")],
    "debt_current": [("us-gaap", "LongTermDebtCurrent"), ("us-gaap", "DebtCurrent")],
    "interest_expense": [("us-gaap", "InterestExpense")],
    "shares_outstanding": [("dei", "EntityCommonStockSharesOutstanding")],
    "shares_diluted_wavg": [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")],
}
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = 0.15 - (time.monotonic() - _last_call)  # ~6 req/s, under SEC's 10 req/s cap
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _headers() -> dict:
    return {"User-Agent": get_settings().sec_user_agent, "Accept-Encoding": "gzip"}


def parse_ticker_map(payload: dict) -> dict[str, dict]:
    out = {}
    for row in payload.values():
        out[str(row["ticker"]).upper()] = {"cik": str(row["cik_str"]).zfill(10), "name": row.get("title")}
    return out


def fetch_ticker_map() -> dict[str, dict]:
    _throttle()
    return parse_ticker_map(http_get(TICKERS_URL, headers=_headers()).json())


def parse_company_facts(symbol: str, payload: dict) -> FundamentalsResult:
    cik = str(payload.get("cik", "")).zfill(10)
    if not payload.get("facts"):
        raise ProviderError(f"no XBRL facts for {symbol}")
    facts: list[FactRecord] = []
    rejected = 0
    for concept, candidates in CONCEPTS.items():
        for taxonomy, tag in candidates:
            node = (payload["facts"].get(taxonomy) or {}).get(tag)
            if not node:
                continue
            for unit, rows in node.get("units", {}).items():
                for f in rows:
                    try:
                        if f.get("form") not in FORMS:
                            continue
                        end = date.fromisoformat(f["end"])
                        start = date.fromisoformat(f["start"]) if f.get("start") else None
                        facts.append(FactRecord(concept, f"{taxonomy}:{tag}", start, end,
                                                f.get("fy"), f.get("fp"), f.get("form"),
                                                date.fromisoformat(f["filed"]), f["accn"],
                                                float(f["val"]), unit))
                    except (KeyError, ValueError, TypeError):
                        rejected += 1
    return FundamentalsResult(symbol, cik, NAME, facts, payload.get("entityName"), rejected)


def fetch_company_facts(symbol: str, cik: str) -> FundamentalsResult:
    _throttle()
    return parse_company_facts(symbol, http_get(FACTS_URL.format(cik=cik), headers=_headers()).json())


def fetch_sic_description(cik: str) -> str | None:
    _throttle()
    return http_get(SUBMISSIONS_URL.format(cik=cik), headers=_headers()).json().get("sicDescription")
