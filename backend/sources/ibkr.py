"""Interactive Brokers: account net asset value from the Flex Web Service.

A Flex token is a reporting-only credential (it cannot trade or move money), created
in Client Portal under Performance & Reports > Flex Queries > Flex Web Service
Configuration, next to an Activity Flex Query that includes the "Net Asset Value (NAV)
in Base" section (or "Change in NAV"). Two calls fetch it:

1. `SendRequest?t=<token>&q=<queryId>&v=3` returns a ReferenceCode.
2. `GetStatement?t=<token>&q=<referenceCode>&v=3` returns the report XML, or error
   1019 ("statement generation in progress") while it is still being built.

Docs: https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service
Flex data is end of previous business day, which is fine for a daily sync.
"""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import requests

from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient, convert_to_chf

logger = logging.getLogger(__name__)

FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
SOURCE = "ibkr"
IN_PROGRESS_CODES = {"1019"}
POLL_ATTEMPTS = 10
POLL_SECONDS = 5.0


def _credentials() -> tuple[str, str]:
    return os.environ.get("IBKR_FLEX_TOKEN", "").strip(), os.environ.get("IBKR_FLEX_QUERY_ID", "").strip()


def is_configured() -> bool:
    token, query_id = _credentials()
    return bool(token and query_id)


def _call(endpoint: str, token: str, q: str) -> ET.Element:
    # IBKR rejects requests without a User-Agent; the token never goes to the logs.
    # Errors are re-raised without the request URL, which carries the token.
    try:
        resp = requests.get(
            f"{FLEX_BASE}/{endpoint}",
            params={"t": token, "q": q, "v": "3"},
            headers={"User-Agent": "finance_dash/1.0"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"IBKR Flex {endpoint} unreachable ({type(exc).__name__})") from None
    if resp.status_code >= 400:
        raise RuntimeError(f"IBKR Flex {endpoint} returned HTTP {resp.status_code}")
    return ET.fromstring(resp.content)


def _flex_error(root: ET.Element) -> Optional[tuple[str, str]]:
    if root.tag != "FlexStatementResponse":
        return None
    status = (root.findtext("Status") or "").strip()
    if status == "Success":
        return None
    return (root.findtext("ErrorCode") or "").strip(), (root.findtext("ErrorMessage") or status).strip()


def fetch_statement(sleep: Callable[[float], None] = time.sleep) -> ET.Element:
    token, query_id = _credentials()
    if not token or not query_id:
        raise RuntimeError("IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set in environment")

    sent = _call("SendRequest", token, query_id)
    error = _flex_error(sent)
    if error:
        raise RuntimeError(f"IBKR Flex SendRequest failed ({error[0]}): {error[1]}")
    reference = (sent.findtext("ReferenceCode") or "").strip()

    for attempt in range(POLL_ATTEMPTS):
        report = _call("GetStatement", token, reference)
        error = _flex_error(report)
        if error is None:
            return report
        if error[0] not in IN_PROGRESS_CODES:
            raise RuntimeError(f"IBKR Flex GetStatement failed ({error[0]}): {error[1]}")
        if attempt < POLL_ATTEMPTS - 1:
            sleep(POLL_SECONDS)
    raise RuntimeError("IBKR Flex statement still not ready after polling")


def parse_net_asset_value(report: ET.Element) -> list[dict]:
    """One `{"account", "currency", "value"}` per account in the Flex report."""
    accounts = []
    for statement in report.iter("FlexStatement"):
        account = statement.get("accountId") or "IBKR"
        info = statement.find("AccountInformation")
        base_currency = info.get("currency") if info is not None else None

        value = currency = None
        summaries = [e for e in statement.iter("EquitySummaryByReportDateInBase") if e.get("total")]
        if summaries:
            latest = max(summaries, key=lambda e: e.get("reportDate", ""))
            value, currency = float(latest.get("total")), latest.get("currency")
        else:
            nav = statement.find(".//ChangeInNAV")
            if nav is not None and nav.get("endingValue"):
                value, currency = float(nav.get("endingValue")), nav.get("currency")
        if value is None:
            raise RuntimeError(
                "IBKR Flex report has no 'Net Asset Value (NAV) in Base' or 'Change in NAV' section; "
                "add one to the Flex Query"
            )
        currency = currency or base_currency
        if not currency:
            raise RuntimeError("IBKR Flex report does not say which currency the NAV is in")
        accounts.append({"account": account, "currency": currency, "value": value})
    if not accounts:
        raise RuntimeError("IBKR Flex report contains no FlexStatement")
    return accounts


def sync_ibkr(repo: SQLiteRepository, fx_client: Optional[FrankfurterClient] = None,
              sleep: Callable[[float], None] = time.sleep) -> int:
    accounts = parse_net_asset_value(fetch_statement(sleep))
    holdings = []
    for acc in accounts:
        conv = convert_to_chf(repo, acc["value"], acc["currency"], fx_client)
        holdings.append({
            "label": "IBKR" if len(accounts) == 1 else f"IBKR {acc['account']}",
            "asset_class": "stock",
            "value_chf": conv["amount_chf"],
            "native_amount": acc["value"],
            "native_currency": acc["currency"],
        })
    repo.replace_source_holdings(SOURCE, "api", holdings)
    return len(holdings)
