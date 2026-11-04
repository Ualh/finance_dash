"""Wise: balances (net worth) and statement lines (spending) from a personal API token.

- Profiles: `GET /v2/profiles` (the personal profile is used unless WISE_PROFILE_ID is set).
- Balances: `GET /v4/profiles/{profileId}/balances?types=STANDARD`.
- Statement: `GET /v1/profiles/{profileId}/balance-statements/{balanceId}/statement.json`.

The statement endpoint is SCA-protected for profiles outside US/AU/NZ/SG/CA/MY. Wise
answers 403 with `x-2fa-approval-result: REJECTED` and a one-time token in
`x-2fa-approval`; the client signs that token with the private key whose public half
was uploaded under Settings > API tokens > Manage public keys, and repeats the request
with `X-2FA-Approval` and `X-Signature` (base64 SHA256withRSA). Wise asks for this at
most once every 90 days. Without WISE_PRIVATE_KEY_PATH the balances still sync and the
sync reports why the statement was skipped.
Docs: https://docs.wise.com/api-reference/balance-statement/balancestatementget
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from backend.database import SQLiteRepository
from backend.fx.service import FrankfurterClient, convert_to_chf

logger = logging.getLogger(__name__)

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

STATEMENT_CURSOR_KEY = "wise_statement_synced_until"
FIRST_SYNC_DAYS = 120
OVERLAP_DAYS = 3


class WiseStatementUnavailable(RuntimeError):
    """Balances synced, but the statement (spending) could not be read."""


def _token() -> str:
    return os.environ.get("WISE_API_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_token())


def _sign(one_time_token: str, key_path: str) -> str:
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path],
        input=one_time_token.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return base64.b64encode(result.stdout).decode("ascii")


def _get(path: str, params: dict | None = None, base_url: str = WISE_API_BASE) -> requests.Response:
    token = _token()
    if not token:
        raise RuntimeError("WISE_API_TOKEN must be set in environment")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{base_url}{path}", params=params, headers=headers, timeout=20)
    one_time_token = resp.headers.get("x-2fa-approval")
    if resp.status_code == 403 and one_time_token:
        key_path = os.environ.get("WISE_PRIVATE_KEY_PATH", "").strip()
        if not key_path:
            raise WiseStatementUnavailable(
                "Wise asks for strong customer authentication on the statement; set WISE_PRIVATE_KEY_PATH "
                "to the private key whose public key is uploaded in Wise (API tokens > Manage public keys)"
            )
        headers["X-2FA-Approval"] = one_time_token
        headers["X-Signature"] = _sign(one_time_token, key_path)
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


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def get_statement(profile_id: int, balance: dict, start: datetime, end: datetime) -> list[dict]:
    data = _get(
        f"/v1/profiles/{profile_id}/balance-statements/{balance['id']}/statement.json",
        {"currency": balance["currency"], "intervalStart": _iso(start), "intervalEnd": _iso(end), "type": "COMPACT"},
    ).json()
    lines: list[dict] = []
    for tx in data.get("transactions", []):
        value = abs(float(tx["amount"]["value"]))
        amount = -value if tx.get("type") == "DEBIT" else value
        details = tx.get("details") or {}
        lines.append({
            "reference_number": tx["referenceNumber"],
            "currency": tx["amount"].get("currency", balance["currency"]),
            "date": str(tx["date"])[:10],
            "amount": amount,
            "detail_type": details.get("type"),
            "description": details.get("description"),
        })
    return lines


def sync_wise(repo: SQLiteRepository, fx_client: Optional[FrankfurterClient] = None,
              now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
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

    cursor = repo.get_setting(STATEMENT_CURSOR_KEY)
    start = (datetime.fromisoformat(cursor) - timedelta(days=OVERLAP_DAYS)) if cursor else now - timedelta(days=FIRST_SYNC_DAYS)
    lines: list[dict] = []
    for b in balances:
        for line in get_statement(profile_id, b, start, now):
            line["amount_chf"] = convert_to_chf(repo, line["amount"], line["currency"], fx_client)["amount_chf"]
            lines.append(line)
    repo.import_wise_transactions(lines)
    repo.set_setting(STATEMENT_CURSOR_KEY, now.isoformat(timespec="seconds"))
    return len(holdings)
