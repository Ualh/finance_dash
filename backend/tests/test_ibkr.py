from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from backend.database import SQLiteRepository
from backend.sources import ibkr


@pytest.fixture
def repo():
    with TemporaryDirectory() as tmp:
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        yield repo


@pytest.fixture
def flex_token(monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "secret-flex-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "987654")


class MockFXClient:
    def fetch_rate(self, base, quote, valuation_date):
        return {("USD", "CHF"): 0.80}[(base, quote)]


class Resp:
    def __init__(self, body: str, status: int = 200):
        self.content, self.status_code = body.encode(), status


SEND_OK = """<FlexStatementResponse timestamp="04 November, 2026 06:00 AM EST">
<Status>Success</Status><ReferenceCode>5550001</ReferenceCode>
<Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
</FlexStatementResponse>"""
IN_PROGRESS = """<FlexStatementResponse timestamp="04 November, 2026 06:00 AM EST">
<Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
</FlexStatementResponse>"""
BAD_TOKEN = """<FlexStatementResponse timestamp="04 November, 2026 06:00 AM EST">
<Status>Fail</Status><ErrorCode>1012</ErrorCode><ErrorMessage>Token has expired.</ErrorMessage>
</FlexStatementResponse>"""
NAV_REPORT = """<FlexQueryResponse queryName="finance_dash" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1234567" fromDate="20261102" toDate="20261103" period="LastBusinessDay">
<AccountInformation accountId="U1234567" currency="USD" />
<EquitySummaryInBase>
<EquitySummaryByReportDateInBase accountId="U1234567" currency="USD" reportDate="20261102" cash="100" stock="9800" total="9900" />
<EquitySummaryByReportDateInBase accountId="U1234567" currency="USD" reportDate="20261103" cash="100" stock="9900" total="10000" />
</EquitySummaryInBase>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""
CHANGE_IN_NAV_REPORT = """<FlexQueryResponse queryName="finance_dash" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1234567" fromDate="20261103" toDate="20261103">
<ChangeInNAV accountId="U1234567" currency="USD" startingValue="9900" endingValue="12500" />
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""


def flex_server(responses):
    """Answer SendRequest once, then GetStatement from `responses` in order."""
    calls = []
    queue = list(responses)

    def _get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers))
        if url.endswith("/SendRequest"):
            return Resp(SEND_OK)
        return Resp(queue.pop(0))
    return _get, calls


class TestIbkrFlex:

    def test_sync_reads_latest_nav_and_converts(self, repo, flex_token):
        server, calls = flex_server([NAV_REPORT])
        with patch("backend.sources.ibkr.requests.get", side_effect=server):
            assert ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=lambda s: None) == 1

        (holding,) = repo.list_holdings()
        assert holding["label"] == "IBKR"
        assert holding["source"] == "ibkr" and holding["asset_class"] == "stock"
        assert holding["native_amount"] == 10_000.0 and holding["native_currency"] == "USD"
        assert holding["value_chf"] == 8_000.0

        send, get = calls
        assert send[0].endswith("/FlexWebService/SendRequest")
        assert send[1] == {"t": "secret-flex-token", "q": "987654", "v": "3"}
        assert get[1] == {"t": "secret-flex-token", "q": "5550001", "v": "3"}
        assert send[2]["User-Agent"]

    def test_polls_while_statement_is_generating(self, repo, flex_token):
        server, calls = flex_server([IN_PROGRESS, IN_PROGRESS, NAV_REPORT])
        sleeps = []
        with patch("backend.sources.ibkr.requests.get", side_effect=server):
            ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=sleeps.append)
        assert len(sleeps) == 2
        assert len(calls) == 4

    def test_falls_back_to_change_in_nav(self, repo, flex_token):
        server, _ = flex_server([CHANGE_IN_NAV_REPORT])
        with patch("backend.sources.ibkr.requests.get", side_effect=server):
            ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=lambda s: None)
        assert repo.list_holdings()[0]["native_amount"] == 12_500.0

    def test_flex_error_is_reported_without_the_token(self, repo, flex_token):
        def server(url, params=None, headers=None, timeout=None):
            return Resp(BAD_TOKEN)

        with patch("backend.sources.ibkr.requests.get", side_effect=server):
            with pytest.raises(RuntimeError, match="1012") as err:
                ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=lambda s: None)
        assert "secret-flex-token" not in str(err.value)

    def test_http_error_is_reported_without_the_token(self, repo, flex_token):
        with patch("backend.sources.ibkr.requests.get", return_value=Resp("", status=503)):
            with pytest.raises(RuntimeError, match="HTTP 503") as err:
                ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=lambda s: None)
        assert "secret-flex-token" not in str(err.value)

    def test_report_without_nav_section_says_what_to_add(self, repo, flex_token):
        empty = '<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="U1"/></FlexStatements></FlexQueryResponse>'
        server, _ = flex_server([empty])
        with patch("backend.sources.ibkr.requests.get", side_effect=server):
            with pytest.raises(RuntimeError, match="Net Asset Value"):
                ibkr.sync_ibkr(repo, fx_client=MockFXClient(), sleep=lambda s: None)

    def test_configured_only_with_token_and_query_id(self, monkeypatch):
        assert ibkr.is_configured() is False
        monkeypatch.setenv("IBKR_FLEX_TOKEN", "x")
        assert ibkr.is_configured() is False
        monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "1")
        assert ibkr.is_configured() is True
