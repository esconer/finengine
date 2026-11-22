"""`transaction_cost_bps` must charge the statutory NSE delivery round trip.

THE DEFECT.  One flat, symmetric, undated constant sat on both entry points --
`backtest_service.run_walk_forward_backtest`'s signature and
`analytics.BacktestRequest`'s field -- as the literal `10.0`, with nothing
anywhere saying what unit it was expressed in.

THE UNIT IS THE PART THAT WAS ACTUALLY WRONG, and it is not the part the
"~2x understated" framing names. `run_walk_forward_backtest` measures

    turnover = 0.5 * sum|dw|          # explicitly ONE-WAY, per its own comment

and charges `cost_factor = transaction_cost_bps / 10000` against it. So a book
that is fully exited and fully re-entered accrues 2.0 of turnover and pays
`2 * transaction_cost_bps / 10000` for the round trip. The parameter is a
ONE-WAY rate, and 10.0 therefore modelled a **20.0 bps** round trip against a
statutory ~22.25 -- understated by ~11%, not 2x.

So there were two independent faults, and fixing only the first would have
made things worse:

  1. UNDOCUMENTED UNIT. A caller who reads the source note's "~22-23bps round
     trip" and passes 22.25 gets a modelled 44.5 bps round trip -- a 2x
     OVERSTATEMENT. The literal cannot be judged without knowing which
     quantity it is, and nothing said.
  2. WRONG VALUE, for the delivery line, once the unit is pinned.

This file pins both. It does NOT build the date-keyed schedule that the
underlying source issue calls for: that is a modelling project, and the brief
for this change is a defect fix. What it does instead is state, at the
constant, that the figure is undated and symmetric, and that equity-delivery
STT was left unchanged across the 01-Apr-2026 Finance Act boundary (the option
and futures lines moved; the delivery line did not).

THE SOURCE OF THE COMPONENT TABLE is the repo's own note at
`.scratch/data-correctness-2026-09/p1-bfinance-0.2.0/issues/
16-costs-date-keyed-schedule.md`, which cites the NSE investor levies pages.
It is recomputed from components below rather than pasted as a total, so the
test fails if the arithmetic is edited rather than the constant.

BROKERAGE IS DELIBERATELY EXCLUDED. It is broker- and size-dependent -- the
same note models a Rs 20/order cap -- so no single constant is honest for it.
Adding it would make the round trip schedule-dependent, which is the
date-keyed model this change is not attempting.

No DB, no network: seeded RNG, and the optimizer is stubbed so the fixture is
deterministic and the test costs nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import BacktestRequest
from app.services import backtest_service
from app.services.backtest_service import (
    DEFAULT_TRANSACTION_COST_BPS,
    run_walk_forward_backtest,
)

# --- the statutory component table, recomputed, in bps ----------------------
# Percentages as published; the round trip is derived from them, never pasted.
STT_PCT = 0.100               # buy AND sell, equity delivery
STAMP_DUTY_PCT = 0.015        # BUY ONLY
NSE_TXN_PCT = 0.0030699       # buy AND sell
SEBI_TURNOVER_PCT = 10 / 1e7 * 100   # Rs 10 per crore -> percent, both sides
GST_RATE = 0.18               # on (exchange txn + SEBI) only -- not STT, not stamp

#: The band the source note states, and the band this file asserts against.
ROUND_TRIP_LOWER_BPS = 22.0
ROUND_TRIP_UPPER_BPS = 23.0


def _statutory_round_trip_bps() -> float:
    """Delivery round trip from the component table, in bps."""
    buy = (
        STT_PCT + STAMP_DUTY_PCT + NSE_TXN_PCT + SEBI_TURNOVER_PCT
        + GST_RATE * (NSE_TXN_PCT + SEBI_TURNOVER_PCT)
    )
    sell = (
        STT_PCT + NSE_TXN_PCT + SEBI_TURNOVER_PCT
        + GST_RATE * (NSE_TXN_PCT + SEBI_TURNOVER_PCT)
    )
    return (buy + sell) * 100.0


STATUTORY_ROUND_TRIP_BPS = _statutory_round_trip_bps()


def _frame(rows: int = 300, seed: int = 99):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.normal(0.0006, 0.011, (rows, 2)),
        index=pd.bdate_range("2024-01-01", periods=rows),
        columns=["A", "B"],
    )


@pytest.fixture()
def stubbed_optimizer(monkeypatch):
    """Pin the rebalance target so turnover -- and therefore cost -- is exact.

    `run_walk_forward_backtest` charges friction against the weights it is
    handed, so the round trip it actually pays is only observable if turnover
    is non-zero and known. An equal-weight book never trades against itself, so
    without this the friction path is dead code under test.
    """

    def _fake(returns, strategy=None, risk_free_rate=None):
        return {"weights": {"A": 0.8, "B": 0.2}}

    monkeypatch.setattr(backtest_service, "optimize", _fake)


def _paid_round_trip_bps(res) -> float:
    """Recover the round trip the backtester actually charged, in bps.

    Read back off the payload's own `rebalance_events` rather than asserted
    from the constant, so this measures the ARITHMETIC -- that a one-way rate
    applied to one-way turnover bills a round trip at 2x -- rather than merely
    restating the default.
    """
    turnover = sum(e["turnover"] for e in res["rebalance_events"])
    cost = sum(e["cost_penalty"] for e in res["rebalance_events"])
    assert turnover > 0, "no turnover, so no friction was charged to recover"
    one_way_bps = cost / turnover * 10000.0
    return 2.0 * one_way_bps


# ---------------------------------------------------------------------------
# The value
# ---------------------------------------------------------------------------
class TestTheDefaultIsTheMeasuredFigure:
    def test_the_statutory_table_reproduces_the_documented_band(self):
        """Guards the fixture itself: if this drifts, everything below is void."""
        assert ROUND_TRIP_LOWER_BPS <= STATUTORY_ROUND_TRIP_BPS <= ROUND_TRIP_UPPER_BPS

    def test_the_default_charges_the_statutory_round_trip(self):
        """RED at 10.0, which bills 2 * 10.0 = 20.0 bps.

        The constant is a ONE-WAY rate, so the round trip it implies is twice
        its face value. 11.1 -> 22.2bps, inside the documented band.
        """
        charged = 2.0 * DEFAULT_TRANSACTION_COST_BPS

        assert ROUND_TRIP_LOWER_BPS <= charged <= ROUND_TRIP_UPPER_BPS, (
            f"the default charges a {charged:.2f}bps round trip; the measured NSE "
            f"delivery round trip is {STATUTORY_ROUND_TRIP_BPS:.4f}bps "
            f"({ROUND_TRIP_LOWER_BPS}-{ROUND_TRIP_UPPER_BPS}). At the pre-change "
            f"value of 10.0 this was 20.0bps."
        )
        assert charged == pytest.approx(STATUTORY_ROUND_TRIP_BPS, abs=0.15)

    def test_the_default_is_not_the_round_trip_figure_itself(self):
        """The trap a naive fix walks into.

        Raising 10.0 straight to 22.25 -- the number the source note leads with
        -- would bill a 44.5bps round trip, a 2x OVERSTATEMENT rather than a
        fix. This is the assertion that distinguishes the two.
        """
        assert DEFAULT_TRANSACTION_COST_BPS < ROUND_TRIP_LOWER_BPS, (
            "the default must be the ONE-WAY rate, not the round-trip figure. "
            "It is applied to 0.5*sum|dw|, so a full exit and re-entry bills "
            "twice this number."
        )


# ---------------------------------------------------------------------------
# The unit -- proven through the engine, not asserted from the constant
# ---------------------------------------------------------------------------
class TestTheUnitIsOneWayPerTheEngineItself:
    def test_a_full_exit_and_reentry_bills_the_round_trip(self, stubbed_optimizer):
        """RED at 10.0, which would bill 20.0bps here."""
        res = run_walk_forward_backtest(
            _frame(), strategy="hrp", lookback_days=100, rebalance_freq_days=21,
        )

        assert res["total_turnover"] > 0, "the fixture stopped trading"
        charged = _paid_round_trip_bps(res)

        assert ROUND_TRIP_LOWER_BPS <= charged <= ROUND_TRIP_UPPER_BPS, (
            f"the engine billed a {charged:.2f}bps round trip over "
            f"{res['total_rebalances']} rebalances; statutory delivery is "
            f"{STATUTORY_ROUND_TRIP_BPS:.4f}bps."
        )

    def test_cost_tracks_the_rate_the_caller_passes(self, stubbed_optimizer):
        """The parameter still drives the cost -- it is not ignored or clamped.

        Deliberately a DIRECTION test, not an exact-doubling test. The payload
        rounds `cost_penalty` to 6dp against values of ~1e-3, so only ~3
        significant digits survive publication; asserting exact linearity would
        be asserting that rounding, and a tolerance loose enough to admit the
        rounding would equally admit an additive floor. What is worth pinning
        is that raising the rate raises the charge.
        """
        kw = dict(strategy="hrp", lookback_days=100, rebalance_freq_days=21)
        base = run_walk_forward_backtest(_frame(), **kw)
        dearer = run_walk_forward_backtest(
            _frame(), transaction_cost_bps=2 * DEFAULT_TRANSACTION_COST_BPS, **kw,
        )

        def paid(res):
            return sum(e["cost_penalty"] for e in res["rebalance_events"])

        assert base["total_turnover"] == dearer["total_turnover"]
        assert paid(dearer) > paid(base)


# ---------------------------------------------------------------------------
# One constant, two entry points -- the `risk_free_rate` duplication, again
# ---------------------------------------------------------------------------
class TestBothEntryPointsShareOneConstant:
    def test_the_request_field_reads_the_service_default(self):
        assert BacktestRequest().transaction_cost_bps == DEFAULT_TRANSACTION_COST_BPS, (
            "the API field and the service default have drifted apart. That is "
            "how `risk_free_rate` ended up as two books, and it means the "
            "documented figure and the charged figure can disagree."
        )

    def test_the_service_signature_default_is_the_constant(self):
        import inspect

        assert (
            inspect.signature(run_walk_forward_backtest)
            .parameters["transaction_cost_bps"].default
            == DEFAULT_TRANSACTION_COST_BPS
        )


# ---------------------------------------------------------------------------
# The guard that must not regress with the default
# ---------------------------------------------------------------------------
class TestTheNegativeGuardIsIntact:
    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_a_negative_or_nonfinite_bps_is_still_refused(self, bad):
        with pytest.raises(ValueError):
            run_walk_forward_backtest(
                _frame(), strategy="hrp", transaction_cost_bps=bad,
            )

    def test_zero_is_still_accepted(self):
        """Frictionless is a legitimate request, not an error."""
        res = run_walk_forward_backtest(
            _frame(), strategy="hrp", transaction_cost_bps=0.0,
        )
        assert res["total_rebalances"] > 0