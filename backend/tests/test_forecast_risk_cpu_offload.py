"""`/analytics/forecast-risk` must run its refit band through `_run_cpu`.

THE WORK.  `get_forecast_risk` publishes a measured interval for the portfolio
leg's conditional sigma, and measuring it means re-fitting the ARCH model on
every one of `FORECAST_PORTFOLIO_REFIT_RESAMPLES` (1000) circular moving-block
draws - 1001 optimiser runs, of which the module's own comment
(`analytics_engine.py:6863`) records 17.3 s on the real 14-position book.  The
estimator is `volatility_forecast_statistics`, reached through
`_observed_volatility_statistics` (:5074).

WHAT WAS WRONG.  Not that the band ran on the loop: it did not.  It ran on
`asyncio.to_thread` directly, which is off the loop but UNBOUNDED.  Every other
heavy quant route in this module hands its heaviest call to `_run_cpu` (:205),
the per-loop `asyncio.Semaphore(2)` wrapper, so at most two CPU sections run at
once however many requests arrive.  `get_forecast_risk` was the one route holding
a thousand-refit bootstrap that did not count against that budget, so N
concurrent forecast-risk requests each started their own refit storm,
competing with `/optimize` and `/backtest` for the same cores.  This file pins
the budget it now shares, and pins that sharing it moved no figure.

WHY OFFLOADING IS SAFE HERE.  `measure_estimate_uncertainty` draws its resample
indices from `moving_block_indices(..., UNCERTAINTY_BOOTSTRAP_SEED)` through a
FRESH `np.random.default_rng` - no global RNG anywhere on the path - and
`volatility_forecast_statistics` walks those columns in index order.  The one
stochastic branch, the multi-step EGARCH simulation, builds a fresh distribution
instance at `EGARCH_SIMULATION_SEED` on every call
(`analytics_engine.py:6816`), so its stream restarts rather than advancing.  A
worker thread and the loop therefore read the same numbers, which
`test_the_offloaded_band_is_byte_identical_to_the_same_band_on_the_loop` proves
by hash rather than by taking it on trust.

FIVE PROOFS, none of them a timing threshold:
  1. the route hands both of its CPU sections to `_run_cpu` and holds no
     `asyncio.to_thread` of its own (structural);
  2. the refit band does not ENTER while the module's per-loop CPU budget is
     fully held, and does complete once a permit comes back (behavioural);
  3. a concurrent request is served while the refit band is parked on a
     `threading.Event` (the invariant the offload exists for);
  4. no refit runs on the event-loop thread, by thread identity;
  5. the payload is byte-identical to the digest captured before the offload,
     and the offloaded block is byte-identical to the same block computed
     inline on the loop.

No network: seeded RNG only.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import _forecast_portfolio_uncertainty, get_forecast_risk
from app.services.analytics_engine import (
    FORECAST_PORTFOLIO_REFIT_RESAMPLES,
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    UNCERTAINTY_BOOTSTRAP_SEED,
    AnalyticsEngine,
    aggregate_active_returns,
    volatility_forecast_statistics,
)

TICKERS = ("AAA.NS", "BBB.NS", "CCC.NS")
OBSERVATIONS = 60
MODEL = "GARCH"
HORIZON = 1

#: Deadlock guards, NOT performance thresholds.  The assertions are binary facts
#: - "the refit did not start", "the wait expired" - and none of them measures
#: how long anything took.
BUDGET_GUARD_SECONDS = 3.0
RELEASE_GUARD_SECONDS = 15.0

#: SHA-256 over the canonical JSON of the whole payload, captured from this route
#: BEFORE its band was handed to `_run_cpu` (the band ran on a bare
#: `asyncio.to_thread`):
#:
#:     before  a4aa9aa62378aa348fededbceb3e2e3da7b0f7c5b93388c46f4ac0ea69370507
#:     after   a4aa9aa62378aa348fededbceb3e2e3da7b0f7c5b93388c46f4ac0ea69370507
#:
#: Same fixture, same seed, same published draw count, so an offload that moved
#: a number moves this digest.  It is a digest of the WHOLE payload - the fitted
#: volatility, the 1001-draw band, every leg block, the classified precision
#: node - because a byte comparison of one field would miss a figure that moved
#: elsewhere.
PRE_OFFLOAD_PAYLOAD_SHA256 = (
    "a4aa9aa62378aa348fededbceb3e2e3da7b0f7c5b93388c46f4ac0ea69370507"
)


def _prices(seed: int = 3, tickers=TICKERS, observations: int = OBSERVATIONS):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=observations)
    out = {}
    for ticker in tickers:
        walk = np.cumsum(rng.normal(0.0003, 0.010, observations))
        out[ticker] = pd.Series(100.0 * np.exp(walk), index=dates)
    return out


def _allocation(tickers=TICKERS):
    return list(tickers), {t: 1.0 / len(tickers) for t in tickers}


def _sha(node) -> str:
    """SHA-256 over canonical JSON: sorted keys, no insignificant whitespace."""
    canonical = json.dumps(
        node, sort_keys=True, separators=(",", ":"), default=repr
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _route_payload(*, engine=None, model: str = MODEL, horizon: int = HORIZON):
    """`get_forecast_risk` called the way the route is called, on a real engine."""
    series = _prices()

    async def allocation(_tickers, _db):
        return _allocation()

    engine = engine or AnalyticsEngine()
    with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
         patch("app.api.analytics._fetch_price_series_dict",
               new=AsyncMock(return_value=series)):
        return await get_forecast_risk(
            model=model, horizon=horizon, tickers=",".join(TICKERS),
            start=series[TICKERS[0]].index[0].date(),
            end=series[TICKERS[0]].index[-1].date(),
            db=Mock(), data_service=Mock(), analytics_engine=engine,
        )


def _portfolio_block(payload: dict) -> dict:
    return payload["precision"]["estimated_statistics"]["portfolio"]


def _park_refit(monkeypatch) -> dict:
    """Park the FIRST entry into the refit estimator on a `threading.Event`.

    `volatility_forecast_statistics` is the engine's own factory, imported into
    this module at :71 and looked up as a MODULE GLOBAL by
    `_observed_volatility_statistics` (:5074) - so patching it here is seen by
    the offloaded call exactly as the real one is.  Only the first entry waits,
    and it waits on a plain `Event`, which is safe from either side: from a
    worker thread it wakes the loop through `call_soon_threadsafe`, and from the
    loop thread it would only schedule a waiter the caller has already prevented
    from running.

    Called from inside the test (not a fixture) because it needs the running
    loop, which a sync fixture does not have.
    """
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    released = threading.Event()
    wait_outcome: list[bool] = []
    state = {"count": 0, "thread": None}
    real = analytics_mod.volatility_forecast_statistics

    def parked(*args, **kwargs):
        if state["count"] == 0:
            state["count"] = 1
            state["thread"] = threading.get_ident()
            loop.call_soon_threadsafe(entered.set)
            wait_outcome.append(released.wait(RELEASE_GUARD_SECONDS))
        return real(*args, **kwargs)

    monkeypatch.setattr(analytics_mod, "volatility_forecast_statistics", parked)
    return {
        "entered": entered,
        "released": released,
        "wait_outcome": wait_outcome,
        "thread": state,
    }


# ---------------------------------------------------------------------------
# 1. the route uses the module's bounded helper, and nothing else
# ---------------------------------------------------------------------------
def test_the_route_hands_both_of_its_cpu_sections_to_the_bounded_helper():
    assert asyncio.iscoroutinefunction(analytics_mod._run_cpu)
    helper = inspect.getsource(analytics_mod._run_cpu)
    assert "_cpu_semaphore()" in helper
    assert "asyncio.to_thread" in helper

    route = inspect.getsource(analytics_mod.get_forecast_risk)
    assert route.count("await _run_cpu(") == 2, (
        "expected the portfolio band and the per-leg band to be the route's two "
        "offloaded CPU sections"
    )
    # `await asyncio.to_thread(`, not the bare name: the comment beside the
    # handoff has to be able to NAME what it replaced, and a substring check on
    # the name would fail on its own explanation.
    assert "await asyncio.to_thread(" not in route, (
        "the route still holds an unbounded offload of its own: `_run_cpu` is "
        "the module's bounded helper, and a bare to_thread bypasses the per-loop "
        "CPU budget every other heavy route shares"
    )
    # The helpers stay synchronous and CPU-pure, which is what makes them
    # `_run_cpu` arguments rather than coroutines.
    for worker in (
        analytics_mod._forecast_portfolio_uncertainty,
        analytics_mod._forecast_leg_uncertainty,
        analytics_mod._observed_volatility_statistics,
    ):
        assert not inspect.iscoroutinefunction(worker), worker.__name__
        assert "asyncio" not in inspect.getsource(worker), worker.__name__


# ---------------------------------------------------------------------------
# 2. the behavioural proof: the refit waits for the shared CPU budget
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_refit_band_waits_for_the_shared_per_loop_cpu_budget(monkeypatch):
    """A thousand-refit bootstrap must not start while the budget is spent.

    The binary fact is "it had not entered", not "it was slow".  Holding both
    permits of the module's per-loop semaphore and observing that the refit
    estimator is still unentered is a statement about the ROUTE'S OWN HANDOFF: a
    bare `asyncio.to_thread` ignores the semaphore entirely and enters
    immediately, so this test is red before the fix and green after it.  The
    release half then proves the wait is a queue and not a deadlock.
    """
    park = _park_refit(monkeypatch)
    semaphore = analytics_mod._cpu_semaphore()
    assert semaphore is analytics_mod._cpu_semaphore(), (
        "the per-loop semaphore is one module global; a second instance would "
        "make this test measure nothing"
    )
    await semaphore.acquire()
    await semaphore.acquire()

    task = asyncio.create_task(_route_payload())
    entered_while_spent = False
    try:
        await asyncio.wait_for(park["entered"].wait(), BUDGET_GUARD_SECONDS)
        entered_while_spent = True
    except asyncio.TimeoutError:
        pass
    assert entered_while_spent is False, (
        "the refit estimator ran while every permit of the module's per-loop CPU "
        "budget was held: this route's offload is not the bounded one"
    )
    assert not task.done()
    park["released"].set()
    semaphore.release()
    semaphore.release()
    payload = await asyncio.wait_for(task, RELEASE_GUARD_SECONDS * 4)

    assert park["wait_outcome"] == [True]
    assert _portfolio_block(payload)["status"] == "computed"


# ---------------------------------------------------------------------------
# 3. a concurrent request is served while the refit is parked
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_concurrent_request_is_served_while_the_refit_band_recomputes(
    async_client, monkeypatch
):
    park = _park_refit(monkeypatch)
    health: dict[str, object] = {}

    async def concurrent_health() -> None:
        await park["entered"].wait()
        response = await async_client.get("/api/v1/health")
        health["status_code"] = response.status_code
        health["body"] = response.json()
        park["released"].set()

    other = asyncio.create_task(concurrent_health())
    try:
        payload = await _route_payload()
    finally:
        park["released"].set()
        await other

    assert park["wait_outcome"] == [True], (
        "the parked refit never woke, which is what an occupied event loop looks "
        f"like after {RELEASE_GUARD_SECONDS}s"
    )
    assert health.get("status_code") == 200, health
    assert health["body"]["status"] == "healthy", health
    assert _portfolio_block(payload)["status"] == "computed"


# ---------------------------------------------------------------------------
# 4. thread identity: the band is not computed on the loop thread
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_refit_band_runs_on_the_event_loop_thread(monkeypatch):
    park = _park_refit(monkeypatch)
    park["released"].set()  # this test is about WHERE, not about waiting
    loop_thread = threading.get_ident()

    payload = await _route_payload()

    assert _portfolio_block(payload)["status"] == "computed"
    assert park["thread"]["thread"] is not None, (
        "the spy never fired, so this proves nothing"
    )
    assert park["thread"]["thread"] != loop_thread, (
        "the refit estimator ran on the event-loop thread"
    )


# ---------------------------------------------------------------------------
# 5. no figure moved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_offloaded_band_is_byte_identical_to_the_same_band_on_the_loop():
    """Same seeded inputs, two threads, one digest.

    This is the offload's own no-figure-moved proof and it needs no golden: the
    block the route computed on a worker thread and the same block computed
    inline on the loop are hashed and compared, so any dependence the estimator
    has on WHERE it runs - a global RNG, an advancing simulation stream, a
    thread-local cache - shows up as two different digests.
    """
    series = _prices()
    price_data = pd.DataFrame(series).sort_index().replace([np.inf, -np.inf], np.nan)
    returns = price_data.pct_change(fill_method=None).iloc[1:]
    portfolio_returns = aggregate_active_returns(returns, _allocation()[1])

    engine = AnalyticsEngine()
    forecast_result = await engine.forecast_volatility(
        portfolio_returns, MODEL, HORIZON
    )

    async def allocation_seam(_tickers, _db):
        return _allocation()

    with patch("app.api.analytics.resolve_allocation", side_effect=allocation_seam), \
         patch("app.api.analytics._fetch_price_series_dict",
               new=AsyncMock(return_value=series)):
        offloaded = await get_forecast_risk(
            model=MODEL, horizon=HORIZON, tickers=",".join(TICKERS),
            start=series[TICKERS[0]].index[0].date(),
            end=series[TICKERS[0]].index[-1].date(),
            db=Mock(), data_service=Mock(), analytics_engine=engine,
        )
    on_loop = _forecast_portfolio_uncertainty(
        portfolio_returns, MODEL, HORIZON, forecast_result
    )

    block = _portfolio_block(offloaded)
    assert block["status"] == "computed"
    assert block["bootstrap_resamples"] == FORECAST_PORTFOLIO_REFIT_RESAMPLES
    assert _sha(block) == _sha(on_loop), (
        "the measured band differs between a worker thread and the event loop: "
        "the estimator is not thread-invariant and the offload is unsafe"
    )


@pytest.mark.asyncio
async def test_the_payload_is_byte_identical_to_the_pre_offload_golden():
    payload = await _route_payload()

    block = _portfolio_block(payload)
    # Non-vacuity: a real band over the published draw count, or this digest
    # would be comparing two degraded payloads.
    assert FORECAST_PORTFOLIO_REFIT_RESAMPLES == UNCERTAINTY_BOOTSTRAP_RESAMPLES
    assert block["bootstrap_resamples"] == FORECAST_PORTFOLIO_REFIT_RESAMPLES
    assert block["estimates"]["volatility_forecast"]["status"] == "computed"
    assert block["estimates"]["volatility_forecast"]["conf_int"] is not None

    digest = _sha(payload)
    assert digest == PRE_OFFLOAD_PAYLOAD_SHA256, (
        f"the payload moved when the band was routed through `_run_cpu`: "
        f"{digest}"
    )


# ---------------------------------------------------------------------------
# 6. the seeded? claim the offload rests on
# ---------------------------------------------------------------------------
def test_the_refit_statistic_is_deterministic_across_calls():
    """The property that makes the offload safe, checked where it is relied on.

    Two calls over the SAME resample block must produce the same numbers.  The
    draws come from a seeded index matrix and the fit is deterministic given a
    draw, so this is the fact an unseeded or advancing source of randomness
    would break.
    """
    rng = np.random.default_rng(11)
    block = rng.normal(0.0003, 0.01, (90, 4, 1))
    statistic = volatility_forecast_statistics(MODEL, HORIZON)
    first = {k: np.asarray(v).tolist() for k, v in statistic(block).items()}
    second = {k: np.asarray(v).tolist() for k, v in statistic(block).items()}
    assert first == second
    assert np.isfinite(first["volatility_forecast"]).any()


@pytest.mark.asyncio
async def test_the_published_band_names_the_seed_its_draws_came_from():
    payload = await _route_payload()
    block = _portfolio_block(payload)

    assert block["resample_seed"] == UNCERTAINTY_BOOTSTRAP_SEED
    assert block["block_size"] > 0
    source = inspect.getsource(volatility_forecast_statistics)
    assert "np.random" not in source, (
        "the statistic must not draw its own randomness; every draw has to come "
        "from the seeded index matrix `measure_estimate_uncertainty` builds"
    )