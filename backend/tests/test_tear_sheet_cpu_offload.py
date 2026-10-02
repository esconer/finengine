"""`/analytics/tear-sheet` must not run its CPU work on the event loop.

The route is the heaviest analytics endpoint and it was the only one that
skipped `_run_cpu` (`analytics.py:205`) - the per-loop
`asyncio.Semaphore(2)` offload that `/optimize`, `/backtest`, `/regime`,
`/correlation-stability`, `/vol-cone` and `/tails` all hand their own
heaviest call to. It runs a lazy `import quantstats`, 23 `quantstats.stats.*`
calls and FIVE `_tear_sheet_uncertainty` blocks, each of which calls the
SYNCHRONOUS `measure_estimate_uncertainty` with
`UNCERTAINTY_BOOTSTRAP_RESAMPLES = 1000`. On the loop that blocks every
other request - dashboard, websockets, health - for its whole duration, and
unlike `/tails` the route has no response cache in front of it.

Two independent proofs, because either alone is weak:

1. `test_a_concurrent_request_is_served_while_the_tear_sheet_computes` is
   the behavioural one, and it is the only one that can FAIL on a loaded
   machine without being a timing test. It parks a metric call on a
   `threading.Event` and waits for a concurrent `GET /api/v1/health` to
   finish. Off the loop the loop is free, health is served, the parked call
   is released. On the loop nothing else can run and the wait can only
   expire. (Counting loop iterations cannot do this job: the one legitimate
   `await` between the two CPU sections ticks the loop on the old code too,
   and a single worker run ticks it not at all.)

2. `test_no_tear_sheet_call_runs_on_the_event_loop_thread` pins the same
   fact by THREAD IDENTITY, so it names the mechanism rather than the
   symptom.

Both are non-vacuous: each asserts its spy actually fired.

3. `test_the_payload_is_byte_identical_to_the_pre_offload_golden` is the
   no-figure-changed proof. `fixtures/tear_sheet_pre_cpu_offload.json` was
   captured from this route BEFORE the offload, and the whole 88 KB payload
   - eleven metrics, five uncertainty blocks, the full-history block, the
   relative blocks, the monthly grid, the drawdown walk - must compare
   equal. The bootstrap is seeded (`resample_seed`) and every input is a
   fixed synthetic frame, so this is a byte comparison, not a tolerance.

No network: seeded RNG only, isolated in-memory DB.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.api import analytics as analytics_mod
from app.models.database import PortfolioPosition

GOLDEN = Path(__file__).parent / "fixtures" / "tear_sheet_pre_cpu_offload.json"

TICKERS = ["ALPHA.NS", "BETA.NS"]
SEEDS = {"ALPHA.NS": 7, "BETA.NS": 13}
START = "2024-01-02"
END = "2026-01-02"
DAYS = 520

#: Deadlock guard for the concurrency test. NOT a performance threshold: the
#: assertion is the binary fact that a second request completed while a metric
#: call was parked, not how long that took.
RELEASE_GUARD_SECONDS = 15.0


def _frame(ticker: str) -> pd.DataFrame:
    """The project's lowercase cache schema (DataService shape)."""
    dates = pd.date_range(start=START, periods=DAYS, freq="B")
    rng = np.random.default_rng(SEEDS[ticker])
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, DAYS)))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.004, DAYS)),
        "high": close * 1.008,
        "low": close * 0.992,
        "close": close,
        "adj_close": close,
        "volume": rng.integers(100_000, 1_000_000, DAYS).astype(float),
        "ticker": ticker,
    })


@pytest.fixture
def tear_sheet_services():
    """A two-leg book and a benchmark, both fixed-seed synthetic frames."""
    frames = {t: _frame(t) for t in TICKERS}
    data = Mock()
    data.fetch_historical_data = AsyncMock(side_effect=lambda t, *a, **k: frames[t])
    bench_rng = np.random.default_rng(99)
    bench_dates = frames[TICKERS[0]]["date"]
    bench = pd.Series(
        bench_rng.normal(0.0003, 0.011, len(bench_dates)),
        index=pd.to_datetime(bench_dates),
    )
    bench_service = Mock()
    bench_service.get_returns = AsyncMock(return_value=bench)
    bench_service.get_benchmark_df = AsyncMock(return_value=pd.DataFrame({"close": bench}))
    return data, bench_service


async def _book(test_db) -> None:
    await test_db.execute(delete(PortfolioPosition))
    for ticker, weight in zip(TICKERS, (0.6, 0.4)):
        test_db.add(PortfolioPosition(
            ticker=ticker, weight=weight, quantity=10.0, buy_price=100.0,
            last_price=100.0, market_value=1000.0,
            added_on=datetime(2024, 1, 2),
        ))
    await test_db.commit()


async def _drive(async_client, data, bench_service):
    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: data
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: bench_service
    try:
        return await async_client.get(
            "/api/v1/analytics/tear-sheet",
            params={"start": START, "end": END},
        )
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)
        app.dependency_overrides.pop(analytics_mod.get_benchmark_service, None)


def _spy_on_cpu(monkeypatch, record) -> None:
    """Wrap the three module-level seams the route's CPU section calls.

    `_q` wraps every `quantstats.stats.*` call (23 across the holding,
    full-depth and benchmark blocks); the two uncertainty helpers wrap the
    five bootstrap blocks. All three are plain module globals, which is what
    the worker thread resolves too, so patching them on `analytics_mod` sees
    the offloaded calls as well.
    """
    real_q = analytics_mod._q
    real_block = analytics_mod._tear_sheet_uncertainty
    real_relative = analytics_mod._tear_sheet_relative_uncertainty

    def q(*args, **kwargs):
        record()
        return real_q(*args, **kwargs)

    def block(*args, **kwargs):
        record()
        return real_block(*args, **kwargs)

    def relative(*args, **kwargs):
        record()
        return real_relative(*args, **kwargs)

    monkeypatch.setattr(analytics_mod, "_q", q)
    monkeypatch.setattr(analytics_mod, "_tear_sheet_uncertainty", block)
    monkeypatch.setattr(analytics_mod, "_tear_sheet_relative_uncertainty", relative)


# ---------------------------------------------------------------------------
# 1. the behavioural proof: a concurrent request is served
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_concurrent_request_is_served_while_the_tear_sheet_computes(
    async_client, test_db, tear_sheet_services, monkeypatch
):
    await _book(test_db)
    data, bench_service = tear_sheet_services

    entered = asyncio.Event()
    released = threading.Event()
    loop = asyncio.get_running_loop()
    released_in_time: list[bool] = []
    health: dict[str, object] = {}
    calls = {"metric": 0}
    first = True

    real_q = analytics_mod._q

    def q(*args, **kwargs):
        nonlocal first
        calls["metric"] += 1
        if first:
            first = False
            # Thread-safe from BOTH sides: from a worker thread this wakes the
            # loop, and from the loop thread it only schedules the waiter that
            # the very next line prevents from ever running.
            loop.call_soon_threadsafe(entered.set)
            released_in_time.append(released.wait(RELEASE_GUARD_SECONDS))
        return real_q(*args, **kwargs)

    monkeypatch.setattr(analytics_mod, "_q", q)

    async def concurrent_health() -> None:
        await entered.wait()
        response = await async_client.get("/api/v1/health")
        health["status_code"] = response.status_code
        health["body"] = response.json()
        released.set()

    other = asyncio.create_task(concurrent_health())
    try:
        response = await _drive(async_client, data, bench_service)
    finally:
        released.set()
        await other

    assert response.status_code == 200, response.text
    assert calls["metric"] >= 20, f"only {calls['metric']} metric calls - proves nothing"
    assert released_in_time == [True], (
        "a concurrent request could not be served while the tear sheet was "
        f"parked inside a metric call: the wait expired after "
        f"{RELEASE_GUARD_SECONDS}s, which is what an occupied event loop looks "
        "like"
    )
    assert health.get("status_code") == 200, health
    assert health["body"]["status"] == "healthy", health


# ---------------------------------------------------------------------------
# 2. the structural proof: thread identity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_tear_sheet_call_runs_on_the_event_loop_thread(
    async_client, test_db, tear_sheet_services, monkeypatch
):
    await _book(test_db)
    data, bench_service = tear_sheet_services

    loop_thread = threading.get_ident()
    counts = {"quantstats_metric": 0, "uncertainty_block": 0, "relative_block": 0}
    on_loop: list[str] = []

    def note_for(name: str):
        def note() -> None:
            counts[name] += 1
            if threading.get_ident() == loop_thread:
                on_loop.append(name)
        return note

    real_q = analytics_mod._q
    real_block = analytics_mod._tear_sheet_uncertainty
    real_relative = analytics_mod._tear_sheet_relative_uncertainty
    metric_note = note_for("quantstats_metric")
    block_note = note_for("uncertainty_block")
    relative_note = note_for("relative_block")

    def q(*args, **kwargs):
        metric_note()
        return real_q(*args, **kwargs)

    def block(*args, **kwargs):
        block_note()
        return real_block(*args, **kwargs)

    def relative(*args, **kwargs):
        relative_note()
        return real_relative(*args, **kwargs)

    monkeypatch.setattr(analytics_mod, "_q", q)
    monkeypatch.setattr(analytics_mod, "_tear_sheet_uncertainty", block)
    monkeypatch.setattr(analytics_mod, "_tear_sheet_relative_uncertainty", relative)

    response = await _drive(async_client, data, bench_service)

    assert response.status_code == 200, response.text
    assert counts["quantstats_metric"] >= 20, counts
    assert counts["uncertainty_block"] >= 4, counts
    assert counts["relative_block"] >= 2, counts
    assert on_loop == [], (
        f"{len(on_loop)} CPU calls ran on the event-loop thread: "
        f"{sorted(set(on_loop))}"
    )


# ---------------------------------------------------------------------------
# 3. the offload is the module's own bounded helper, and it is actually used
# ---------------------------------------------------------------------------
def test_the_tear_sheet_offload_is_the_modules_own_bounded_helper():
    from app.services.analytics_engine import UNCERTAINTY_BOOTSTRAP_RESAMPLES

    assert UNCERTAINTY_BOOTSTRAP_RESAMPLES == 1000
    assert asyncio.iscoroutinefunction(analytics_mod._run_cpu)

    helper = inspect.getsource(analytics_mod._run_cpu)
    assert "_cpu_semaphore()" in helper
    assert "asyncio.to_thread" in helper

    route = inspect.getsource(analytics_mod.get_tear_sheet)
    assert route.count("await _run_cpu(") == 2, (
        "expected exactly the two offloaded CPU sections of this route"
    )
    # And no lazy quantstats import is left inside the coroutine.
    assert "import quantstats" not in route


# ---------------------------------------------------------------------------
# 4. no published figure moved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_payload_is_byte_identical_to_the_pre_offload_golden(
    async_client, test_db, tear_sheet_services
):
    await _book(test_db)
    data, bench_service = tear_sheet_services

    response = await _drive(async_client, data, bench_service)
    assert response.status_code == 200, response.text
    payload = response.json()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert set(payload) == set(golden), sorted(set(payload) ^ set(golden))
    assert payload == golden, [
        key for key in golden if payload.get(key) != golden[key]
    ]
    # Non-vacuity: the golden is a real tear sheet, not a degraded one.
    assert payload["metrics"]["sharpe"] is not None
    assert payload["full_history"]["metrics"]["sharpe"] is not None
    assert payload["estimate_uncertainty"]["metrics"]["status"] == "computed"
    assert (
        payload["estimate_uncertainty"]["relative_vs_nifty"]["market_model"]["status"]
        == "computed"
    )
    assert len(payload["underwater"]) > 0
    assert payload["monthly_returns"]