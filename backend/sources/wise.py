"""Wise: balances (net worth) from a personal API token.

- Profiles: `GET /v2/profiles` (the personal profile is used unless WISE_PROFILE_ID is set).
- Balances: `GET /v4/profiles/{profileId}/balances?types=STANDARD`.

Wise no longer supports request signing (SCA) on personal accounts (PSD2), so its
statement endpoint is out of reach: statement transactions are not available through the
API and are deliberately not requested. Only balances sync, and that is not an error.
The past that needs no SCA (activity feed, sent transfers) is read by `backend/history/wise.py`.
Docs: https://docs.wise.com/api-reference/balance
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient, convert_to_chf

WISE_API_BASE = "https://api.wise.com"
SOURCE = "wise"

# Statement detail types that move money between the user's own balances, or into
# Wise, rather than spending it.
INTERNAL_DETAIL_TYPES = frozenset({
    "CONVERSION",
    "INCOMING_CROSS_BALANCE",
    "OUTGOING_CROSS_BALANCE",
    "MONEY_ADDED",
    "DEPOSIT",
    "BALANCE_INTEREST",
    "INVESTMENT_TRADE_ORDER",
})


def _token() -> str:
    return os.environ.get("WISE_API_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_token())


def _get(path: str, params: dict | None = None, base_url: str = WISE_API_BASE) -> requests.Response:
    token = _token()
    if not token:
        raise RuntimeError("WISE_API_TOKEN must be set in environment")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{base_url}{path}", params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp


def get_profile_id() -> int:
    override = os.environ.get("WISE_PROFILE_ID", "").strip()
    if override:
        return int(override)
    profiles = _get("/v2/profiles").json()
    for profile in profiles:
        if str(profile.get("type", "")).upper() == "PERSONAL":
            return int(profile["id"])
    if profiles:
        return int(profiles[0]["id"])
    raise RuntimeError("Wise returned no profile for this token")


def get_balances(profile_id: int) -> list[dict]:
    balances = _get(f"/v4/profiles/{profile_id}/balances", {"types": "STANDARD"}).json()
    return [
        {"id": int(b["id"]), "currency": b["currency"], "value": float(b["amount"]["value"])}
        for b in balances
    ]


def sync_wise(repo: SQLiteRepository, fx_client: Optional[FrankfurterClient] = None) -> int:
    profile_id = get_profile_id()
    balances = get_balances(profile_id)

    holdings = []
    for b in balances:
        if b["value"] == 0:
            continue
        conv = convert_to_chf(repo, b["value"], b["currency"], fx_client)
        holdings.append({
            "label": f"Wise {b['currency']}",
            "asset_class": "cash",
            "value_chf": conv["amount_chf"],
            "native_amount": b["value"],
            "native_currency": b["currency"],
        })
    repo.replace_source_holdings(SOURCE, "api", holdings)
    return len(holdings)
