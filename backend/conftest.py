from __future__ import annotations

import pytest

SOURCE_ENV_VARS = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "WISE_API_TOKEN",
    "WISE_PROFILE_ID",
    "WISE_PRIVATE_KEY_PATH",
    "IBKR_FLEX_TOKEN",
    "IBKR_FLEX_QUERY_ID",
)


@pytest.fixture(autouse=True)
def no_real_source_credentials(monkeypatch):
    """Tests never reach a real account: every source starts unconfigured."""
    for name in SOURCE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
