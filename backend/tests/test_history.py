"""History backfill: batching inside API limits, resume after a failure, no duplicates on re-run."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import requests

from backend.database import SQLiteRepository
from backend.history import binance as binance_history
from backend.history import wise as wise_history
from backend.history.engine import (
    MS_PER_DAY,
    IdPagedDataset,
    Pacer,
    WindowedDataset,
    date_to_ms,
    run_dataset,
    with_rate_limit_retry,
)

DAY = MS_PER_DAY
START = date_to_ms("2024-01-01")


@pytest.fixture
def repo():
    with TemporaryDirectory() as tmp:
        repo = SQLiteRepository(Path(tmp) / "test.db")
        repo.initialise_schema()
        yield repo
        repo.close()


class FakeWindowApi:
    """Rows at fixed times; answers a window query like Binance, truncated at `limit`."""

    def __init__(self, times: list[int], limit: int = 1000, fail_on_call: int | None = None):
        self.rows = [{"id": i, "t": t, "status": "pending"} for i, t in enumerate(times)]
        self.limit, self.fail_on_call = limit, fail_on_call
        self.calls: list[tuple[int, int]] = []

    def fetch(self, start: int, end: int) -> list[dict]:
        self.calls.append((start, end))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("network down")
        return [dict(r) for r in self.rows if start <= r["t"] <= end][: self.limit]


def windowed(api: FakeWindowApi, window_days: int = 10, page_size: int | None = 1000, **kw) -> WindowedDataset:
    return WindowedDataset("test", "rows", api.fetch, lambda r: r["id"], lambda r: r["t"],
                           window_days * DAY, START, page_size=page_size, **kw)


def stored_ids(repo, dataset="rows") -> list[str]:
    return [r["record_id"] for r in repo.list_history_records("test", dataset)]


class TestWindowedBatching:

    def test_windows_cover_the_whole_range_without_gaps_or_exceeding_the_limit(self, repo):
        api = FakeWindowApi([START + d * DAY for d in range(0, 35, 3)])
        now = START + 35 * DAY

        result = run_dataset(repo, windowed(api), now_ms=now)

        assert result.status == "ok"
        assert api.calls[0][0] == START and api.calls[-1][1] == now
        for (s1, e1), (s2, _) in zip(api.calls, api.calls[1:]):
            assert s2 == e1 + 1  # contiguous, no gap, no overlap
        assert all(end - start < 10 * DAY for start, end in api.calls)
        assert len(stored_ids(repo)) == len(api.rows)

    def test_a_full_page_is_split_until_nothing_is_truncated(self, repo):
        times = [START + i * 3_600_000 for i in range(24)]  # one row per hour on one day
        api = FakeWindowApi(times, limit=5)

        run_dataset(repo, windowed(api, window_days=1, page_size=5), now_ms=START + DAY - 1)

        assert sorted(int(i) for i in stored_ids(repo)) == list(range(24))
        assert len(api.calls) > 1

    def test_max_lookback_starts_at_what_the_api_still_keeps(self, repo):
        api = FakeWindowApi([])
        now = START + 400 * DAY
        run_dataset(repo, windowed(api, window_days=29, max_lookback_ms=30 * DAY), now_ms=now)
        assert api.calls[0][0] == now - 30 * DAY
        assert len(api.calls) == 2

    def test_since_overrides_the_earliest_date(self, repo):
        api = FakeWindowApi([])
        run_dataset(repo, windowed(api), now_ms=START + 100 * DAY, since_ms=START + 90 * DAY)
        assert api.calls[0][0] == START + 90 * DAY


class TestResume:

    def test_a_failed_run_resumes_from_the_last_saved_window(self, repo):
        times = [START + d * DAY for d in range(0, 60, 2)]
        now = START + 60 * DAY
        failing = FakeWindowApi(times, fail_on_call=4)

        first = run_dataset(repo, windowed(failing), now_ms=now)

        assert first.status == "error" and "network down" in first.note
        saved = len(stored_ids(repo))
        assert saved == sum(1 for t in times if t < START + 30 * DAY)  # three full windows kept
        cursor = repo.get_history_cursor("test.rows")
        assert int(cursor["position"]) == START + 30 * DAY and cursor["status"] == "error"

        healthy = FakeWindowApi(times)
        second = run_dataset(repo, windowed(healthy), now_ms=now)

        assert second.status == "ok"
        # Resumes just before the saved position (overlap), not from the beginning.
        assert healthy.calls[0][0] == START + 30 * DAY - 3 * DAY
        assert sorted(int(i) for i in stored_ids(repo)) == list(range(len(times)))
        assert repo.get_history_cursor("test.rows")["status"] == "ok"

    def test_an_up_to_date_dataset_only_rereads_the_overlap(self, repo):
        api = FakeWindowApi([START + DAY])
        now = START + 50 * DAY
        run_dataset(repo, windowed(api), now_ms=now)
        api.calls.clear()

        run_dataset(repo, windowed(api), now_ms=now + DAY)

        assert api.calls == [(now + 1 - 3 * DAY, now + DAY)]


class TestDedupe:

    def test_rerunning_from_scratch_adds_nothing(self, repo):
        api = FakeWindowApi([START + d * DAY for d in range(20)])
        now = START + 20 * DAY
        first = run_dataset(repo, windowed(api), now_ms=now)
        again = run_dataset(repo, windowed(api), now_ms=now, restart=True)

        assert first.new == 20
        assert again.fetched == 20 and again.new == 0
        assert len(stored_ids(repo)) == 20

    def test_a_record_seen_again_is_refreshed_not_duplicated(self, repo):
        api = FakeWindowApi([START + DAY])
        run_dataset(repo, windowed(api), now_ms=START + 2 * DAY)
        api.rows[0]["status"] = "credited"
        run_dataset(repo, windowed(api), now_ms=START + 2 * DAY, restart=True)

        [record] = repo.list_history_records("test", "rows")
        assert json.loads(record["payload"])["status"] == "credited"
        assert record["occurred_at"] == "2024-01-02T00:00:00+00:00"

    def test_same_id_in_another_dataset_is_another_record(self, repo):
        row = {"record_id": "1", "occurred_at": None, "payload": "{}"}
        assert repo.save_history_batch("test", "a", [row]) == 1
        assert repo.save_history_batch("test", "b", [row]) == 1
        assert repo.save_history_batch("test", "a", [row, row]) == 0


class FakeTrades:
    def __init__(self, n: int):
        self.trades = [{"symbol": "BTCUSDT", "id": i, "time": START + i} for i in range(n)]
        self.from_ids: list[int] = []

    def fetch(self, from_id: int, page: int = 3) -> list[dict]:
        self.from_ids.append(from_id)
        return [t for t in self.trades if t["id"] >= from_id][:page]


def id_paged(api: FakeTrades) -> IdPagedDataset:
    return IdPagedDataset("test", "trades", "test.trades:BTCUSDT", api.fetch, lambda r: r["id"],
                          lambda r: f"{r['symbol']}:{r['id']}", lambda r: r["time"], page_size=3)


class TestIdPaging:

    def test_pages_by_id_and_resumes_after_the_last_stored_one(self, repo):
        api = FakeTrades(7)
        result = run_dataset(repo, id_paged(api))
        assert api.from_ids == [0, 3, 6]
        assert result.new == 7

        api.trades += [{"symbol": "BTCUSDT", "id": 7, "time": START + 7}]
        api.from_ids.clear()
        again = run_dataset(repo, id_paged(api))
        assert api.from_ids == [7]
        assert again.new == 1
        assert len(repo.list_history_records("test", "trades")) == 8


class TestPacing:

    def test_calls_are_spaced_by_the_minimum_interval(self):
        now = [100.0]
        slept: list[float] = []

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        pacer = Pacer(6.0, sleep=sleep, clock=lambda: now[0])
        pacer.wait()          # first call: immediate
        now[0] += 2.0
        pacer.wait()          # 2 s later: waits the 4 s left
        now[0] += 10.0
        pacer.wait()          # already 10 s later: no wait
        assert slept == [4.0]

    def test_rate_limited_call_waits_retry_after_then_succeeds(self):
        class Resp:
            status_code, headers = 429, {"Retry-After": "7"}

        attempts, slept = [], []

        def call():
            attempts.append(1)
            if len(attempts) == 1:
                raise requests.HTTPError(response=Resp())
            return "ok"

        assert with_rate_limit_retry(call, sleep=slept.append) == "ok"
        assert slept == [7.0]

    def test_other_http_errors_are_not_retried(self):
        class Resp:
            status_code, headers = 500, {}

        def call():
            raise requests.HTTPError(response=Resp())

        with pytest.raises(requests.HTTPError):
            with_rate_limit_retry(call, sleep=lambda s: pytest.fail("must not wait"))


NOW = date_to_ms("2026-11-08")


class FakeBinance:
    """Signed endpoints shaped after developers.binance.com, with call checks."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def signed(self, endpoint, params=None, base_url=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        start, end = params.get("startTime", params.get("beginTime")), params.get("endTime")
        if endpoint == "/sapi/v1/accountSnapshot":
            assert end - start < 30 * DAY and start >= NOW - 30 * DAY
            return {"code": 200, "msg": "", "snapshotVos": [
                {"type": "spot", "updateTime": NOW - DAY,
                 "data": {"totalAssetOfBtc": "0.1", "balances": [{"asset": "SOL", "free": "2", "locked": "0"}]}}
            ] if start <= NOW - DAY <= end else []}
        if endpoint == "/sapi/v1/capital/deposit/hisrec":
            assert end - start < 90 * DAY
            t = date_to_ms("2021-03-01")
            return [{"id": "d1", "coin": "ETH", "amount": "1", "insertTime": t, "status": 1}] if start <= t <= end else []
        if endpoint == "/sapi/v1/capital/withdraw/history":
            assert end - start < 90 * DAY
            return []
        if endpoint in ("/sapi/v1/fiat/orders", "/sapi/v1/fiat/payments"):
            assert params["transactionType"] in (0, 1)
            t = date_to_ms("2022-05-01")
            hit = endpoint.endswith("payments") and params["transactionType"] == 0 and start <= t <= end
            return {"code": "000000", "data": [
                {"orderNo": "f1", "fiatCurrency": "CHF", "cryptoCurrency": "BTC", "createTime": t}
            ] if hit else [], "total": int(hit), "success": True}
        if endpoint == "/sapi/v1/convert/tradeFlow":
            assert end - start <= 30 * DAY
            return {"list": [], "moreData": False}
        if endpoint == "/api/v3/account":
            return {"balances": [{"asset": "ADA", "free": "10", "locked": "0"}]}
        if endpoint == "/api/v3/myTrades":
            assert params["limit"] == 1000
            if params["symbol"] == "ETHBTC" and params["fromId"] == 0:
                return [{"symbol": "ETHBTC", "id": 5, "time": date_to_ms("2021-04-01")}]
            return []
        raise AssertionError(f"unexpected endpoint {endpoint}")

    def public(self, endpoint, params=None, base_url=None):
        assert endpoint == "/api/v3/exchangeInfo"
        return {"symbols": [
            {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC"},
            {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT"},
            {"symbol": "ADACHF", "baseAsset": "ADA", "quoteAsset": "CHF"},
            {"symbol": "DOGEUSDT", "baseAsset": "DOGE", "quoteAsset": "USDT"},  # never held
        ]}


class TestBinanceBackfill:

    def run(self, repo, fake):
        with (
            patch("backend.history.binance.api._signed_request", side_effect=fake.signed),
            patch("backend.history.binance.api._public_request", side_effect=fake.public),
        ):
            return binance_history.backfill_binance(repo, now_ms=NOW, sleep=lambda s: None)

    def test_reads_every_dataset_and_trades_of_pairs_ever_held(self, repo):
        fake = FakeBinance()
        results = {r.key: r for r in self.run(repo, fake)}

        assert all(r.status == "ok" for r in results.values()), [r.line() for r in results.values()]
        assert results["binance.deposits"].new == 1
        assert results["binance.fiat_buys"].new == 1
        assert results["binance.spot_snapshots"].new == 1
        assert results["binance.trades"].new == 1
        traded = sorted({p["symbol"] for e, p in fake.calls if e == "/api/v3/myTrades"})
        assert traded == ["ADACHF", "ETHBTC", "SOLUSDT"]  # DOGE never appears in the account
        # Deposits walked from Binance's opening day in under-90-day windows.
        deposit_calls = [p for e, p in fake.calls if e == "/sapi/v1/capital/deposit/hisrec"]
        assert deposit_calls[0]["startTime"] == date_to_ms("2017-07-01")
        assert deposit_calls[-1]["endTime"] == NOW

    def test_second_run_adds_no_duplicates_and_only_rereads_recent_windows(self, repo):
        self.run(repo, FakeBinance())
        fake = FakeBinance()
        results = {r.key: r for r in self.run(repo, fake)}

        assert sum(r.new for r in results.values()) == 0
        deposit_calls = [p for e, p in fake.calls if e == "/sapi/v1/capital/deposit/hisrec"]
        assert len(deposit_calls) == 1
        trade_calls = [p for e, p in fake.calls if e == "/api/v3/myTrades" and p["symbol"] == "ETHBTC"]
        assert trade_calls == [{"symbol": "ETHBTC", "fromId": 6, "limit": 1000}]

    def test_one_failing_dataset_does_not_stop_the_others(self, repo):
        fake = FakeBinance()
        original = fake.signed

        def flaky(endpoint, params=None, base_url=None):
            if endpoint == "/sapi/v1/capital/withdraw/history":
                raise RuntimeError("HTTP 500")
            return original(endpoint, params, base_url)

        fake.signed = flaky
        results = {r.key: r for r in self.run(repo, fake)}
        assert results["binance.withdrawals"].status == "error"
        assert results["binance.deposits"].status == "ok"
        assert results["binance.trades"].status == "ok"


class WiseResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.headers = payload, status, {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class TestWiseBackfill:

    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setenv("WISE_API_TOKEN", "test-token")
        monkeypatch.setenv("WISE_PROFILE_ID", "123")

    def run(self, repo, handler, since="2026-01-01"):
        calls = []

        def get(url, params=None, headers=None, timeout=None):
            path = url.removeprefix("https://api.wise.com")
            assert "balance-statements" not in path, "statements need SCA: never requested"
            calls.append((path, dict(params or {})))
            return handler(path, params or {})

        with patch("backend.sources.wise.requests.get", side_effect=get):
            results = wise_history.backfill_wise(repo, now_ms=NOW, since_ms=date_to_ms(since), sleep=lambda s: None)
        return {r.key: r for r in results}, calls

    def test_activities_follow_the_cursor_and_transfers_the_offset(self, repo):
        def handler(path, params):
            if path == "/v1/profiles/123/activities":
                if "nextCursor" not in params:
                    return WiseResp({"cursor": "c2", "activities": [
                        {"id": "a1", "type": "CARD_PAYMENT", "primaryAmount": "12 CHF", "createdOn": "2026-03-01T10:00:00Z"}]})
                return WiseResp({"cursor": None, "activities": [
                    {"id": "a2", "type": "TRANSFER", "primaryAmount": "50 EUR", "createdOn": "2026-03-02T10:00:00Z"}]})
            if path == "/v1/transfers":
                assert params["profile"] == 123 and params["limit"] == 100
                page = [{"id": 1000 + params["offset"] + i, "created": "2026-03-03 09:00:00"} for i in range(100)]
                return WiseResp(page if params["offset"] == 0 else page[:7])
            raise AssertionError(path)

        results, _ = self.run(repo, handler)
        assert results["wise.activities"].new == 2
        assert results["wise.transfers"].new == 107
        transfer = repo.list_history_records("wise", "transfers")[0]
        assert transfer["occurred_at"] == "2026-03-03T09:00:00+00:00"

    def test_sca_refusal_is_recorded_and_not_retried(self, repo):
        def handler(path, params):
            if path == "/v1/profiles/123/activities":
                return WiseResp({"error": "SCA required"}, status=403)
            return WiseResp([])

        results, calls = self.run(repo, handler)

        assert results["wise.activities"].status == "refused"
        assert "SCA" in results["wise.activities"].note
        assert sum(1 for p, _ in calls if p.endswith("/activities")) == 1  # one try, no workaround
        assert results["wise.transfers"].status == "ok"
        assert repo.get_history_cursor("wise.activities")["status"] == "refused"


class TestCommand:

    def test_skips_sources_without_credentials(self, monkeypatch, capsys, tmp_path):
        from backend.history.__main__ import main

        monkeypatch.setenv("FINANCE_DASH_DB_FILE", str(tmp_path / "x.db"))
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "binance: skipped" in out and "wise: skipped" in out
