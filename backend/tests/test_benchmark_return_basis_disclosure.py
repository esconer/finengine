"""C-3: the benchmark is a price index, and nothing said so.

`benchmark_service` picks its price leg out of `_CLOSE_CANDIDATES` in a fixed
order and `pct_change`s it. Whether the resulting return series shares a basis
with the equity leg is therefore decided silently, by vendor output, and was
published nowhere. It is not a rounding note: `^NSEI` is a PRICE index, so its
dividends are not reinvested, and every figure measured against that leg -
`beta_vs_benchmark`, `alpha`, `annualized_alpha`, `r_squared`, the tear sheet's
`benchmark_cagr` / `sharpe` / `volatility`, AND the whole HMM regime
classification, which is fitted on exactly these returns - is a comparison
against a price index whether or not the payload admits it.

WHAT THIS FIXES: the disclosure half. `return_basis` and the resolved close
column are now published on the objects this service returns, and a consumer has
a ready-made block to merge into its own metadata.

WHAT IT DOES NOT FIX, deliberately: the data half. Sourcing a total-return index
is a procurement decision, not a code fix. There is no `^NSEI` TRI on the
available feed, and a sector ETF proxy is a DIFFERENT index rather than the same
one with dividends - substituting one would be the stand-in this disclosure
exists to prevent. So `BENCHMARK_RETURN_BASIS` names what the leg is, and the
missing TRI is recorded as deferred rather than approximated.

NO VALUE CHANGES. Nothing here alters a price, a return, a weight or a
classification; every test below pins that the numbers are byte-identical with
and without the disclosure attached.

No network. The service's `ensure_history` is stubbed.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from app.services.benchmark_service import (
    BENCHMARK_NAME,
    BENCHMARK_PRICE_COLUMN_ATTR,
    BENCHMARK_RETURN_BASIS,
    BENCHMARK_RETURN_BASIS_ATTR,
    BENCHMARK_SYMBOL,
    BenchmarkService,
    _close_series,
    benchmark_basis_disclosure,
    resolve_close_column,
)

DAYS = 120


def _frame(column="adj_close", rows=DAYS, seed=3):
    """A DataService-shaped frame: a `date` column plus a price column."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=rows)
    level = 22000.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.009, rows)))
    return pd.DataFrame({"date": dates, column: level, "volume": np.arange(rows)})


def _service(monkeypatch, frame):
    svc = BenchmarkService(db_session=Mock())

    async def fake_ensure(days=756, start=None, end=None):
        return frame

    monkeypatch.setattr(svc, "ensure_history", fake_ensure)
    return svc


# ===========================================================================
# 1. The disclosure itself
# ===========================================================================
class TestTheBasisIsNamed:
    def test_the_basis_is_a_price_index(self):
        """The one claim. `^NSEI` dividends are not compounded back in, so a
        total-return comparison is not what any of these figures is."""
        assert BENCHMARK_RETURN_BASIS == "price_index"

    def test_the_symbol_and_name_are_named_constants(self):
        """`regime_service` hardcoded `"NIFTY 50"` beside the symbol. One name
        for both, so a consumer cannot disagree with the service about which
        index it was measured on."""
        assert BENCHMARK_SYMBOL == "^NSEI"
        assert BENCHMARK_NAME == "NIFTY 50"

    def test_the_disclosure_block_carries_both_halves(self):
        block = benchmark_basis_disclosure(_frame())
        assert block == {
            "symbol": "^NSEI",
            "name": "NIFTY 50",
            "price_column": "adj_close",
            "return_basis": "price_index",
        }

    def test_the_block_is_json_serialisable(self):
        """It is destined for a response body, not a repr."""
        assert json.loads(json.dumps(benchmark_basis_disclosure(_frame()))) == (
            benchmark_basis_disclosure(_frame())
        )


class TestTheResolvedColumnIsPublished:
    @pytest.mark.parametrize(
        "column,expected",
        [
            ("adj_close", "adj_close"),
            ("close", "close"),
            ("Adj Close", "Adj Close"),
            ("Close", "Close"),
        ],
    )
    def test_each_vendor_spelling_resolves(self, column, expected):
        assert resolve_close_column(_frame(column=column)) == expected

    def test_the_adjusted_leg_wins_when_both_are_present(self):
        """`_CLOSE_CANDIDATES` order is the contract. The disclosure NAMES the
        column, so this order is now published behaviour rather than an
        implementation detail."""
        frame = _frame(column="close")
        frame["adj_close"] = frame["close"] * 1.0001
        assert resolve_close_column(frame) == "adj_close"

    def test_a_frame_with_no_close_column_names_nothing(self):
        """Not a stand-in column: the measurement was never taken, and the null
        says so."""
        frame = pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=5),
                              "volume": [1, 2, 3, 4, 5]})
        assert resolve_close_column(frame) is None
        assert benchmark_basis_disclosure(frame)["price_column"] is None

    def test_none_input_is_handled(self):
        assert resolve_close_column(None) is None

    def test_the_disclosure_column_is_the_column_actually_served(self):
        """Not a re-derivation. `_close_series` names its output after the
        column it read, so the published name and the served data cannot
        disagree."""
        for column in ("adj_close", "close", "Adj Close", "Close"):
            series = _close_series(_frame(column=column))
            assert series is not None
            assert series.name == column
            assert benchmark_basis_disclosure(_frame(column=column))["price_column"] == (
                series.name
            )


# ===========================================================================
# 2. It reaches the objects this service actually returns
# ===========================================================================
class TestTheDisclosureTravelsOnTheReturnedObjects:
    async def test_get_returns_carries_the_disclosure(self, monkeypatch):
        svc = _service(monkeypatch, _frame())
        returns = await svc.get_returns(start="2024-01-02", end="2024-06-01")

        assert returns is not None
        assert returns.attrs[BENCHMARK_PRICE_COLUMN_ATTR] == "adj_close"
        assert returns.attrs[BENCHMARK_RETURN_BASIS_ATTR] == "price_index"

    async def test_get_benchmark_df_carries_the_disclosure(self, monkeypatch):
        svc = _service(monkeypatch, _frame())
        frame = await svc.get_benchmark_df()

        assert frame is not None
        assert frame.attrs[BENCHMARK_PRICE_COLUMN_ATTR] == "adj_close"
        assert frame.attrs[BENCHMARK_RETURN_BASIS_ATTR] == "price_index"

    async def test_the_disclosure_is_metadata_only(self, monkeypatch):
        """`attrs` carries no value, index or name. Proven by comparing the
        frame and the series against the same computation with the disclosure
        stripped - if the disclosure could move a number, this fails."""
        frame = _frame()
        svc = _service(monkeypatch, frame)
        with_attrs = await svc.get_returns(start="2024-01-02", end="2024-06-01")

        plain = _close_series(frame)
        plain = plain.loc[
            (plain.index >= pd.Timestamp("2024-01-02"))
            & (plain.index <= pd.Timestamp("2024-06-01"))
        ]
        expected = plain.pct_change(fill_method=None).dropna()
        expected.name = "benchmark"

        pd.testing.assert_series_equal(with_attrs, expected)
        assert with_attrs.name == "benchmark"

    async def test_a_missing_price_column_is_disclosed_as_null(self, monkeypatch):
        """`get_returns` returns None with no series to attach to, so the null
        column case is proven at the resolver, which is where the decision
        happens."""
        frame = pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=5),
                              "volume": [1, 2, 3, 4, 5]})
        svc = _service(monkeypatch, frame)
        assert await svc.get_returns(start="2024-01-02", end="2024-03-01") is None
        assert resolve_close_column(frame) is None

    async def test_the_dataframe_disclosure_names_the_surviving_column(
        self, monkeypatch
    ):
        """`get_benchmark_df` dropna's on the resolved column, so the published
        name is the column that actually survived the drop - not a candidate
        that merely existed."""
        frame = _frame(column="close")
        frame.loc[frame.index[3], "close"] = np.nan
        svc = _service(monkeypatch, frame)
        out = await svc.get_benchmark_df()

        assert out.attrs[BENCHMARK_PRICE_COLUMN_ATTR] == "close"
        assert out["close"].notna().all()
        assert len(out) == DAYS - 1


# ===========================================================================
# 3. NO VALUE CHANGES - and the deferred half, stated rather than approximated
# ===========================================================================
class TestNothingMeasuredMoved:
    async def test_the_return_series_is_identical_to_the_pre_disclosure_one(
        self, monkeypatch
    ):
        frame = _frame()
        svc = _service(monkeypatch, frame)
        returns = await svc.get_returns(start="2024-01-02", end="2024-06-01")

        # The pre-disclosure computation, verbatim from `get_returns`.
        series = _close_series(frame)
        series = series.loc[
            (series.index >= pd.Timestamp("2024-01-02"))
            & (series.index <= pd.Timestamp("2024-06-01"))
        ]
        before = series.pct_change(fill_method=None).dropna()
        before.name = "benchmark"

        pd.testing.assert_series_equal(returns, before)
        assert returns.sum() == pytest.approx(before.sum(), abs=0.0)

    async def test_the_frame_is_identical_to_the_pre_disclosure_one(
        self, monkeypatch
    ):
        frame = _frame()
        svc = _service(monkeypatch, frame)
        out = await svc.get_benchmark_df()

        before = frame.copy()
        before.index = pd.to_datetime(before["date"], errors="coerce")
        before = before.dropna(subset=["adj_close"])

        pd.testing.assert_frame_equal(out, before)

    def test_the_data_half_is_recorded_as_deferred_not_approximated(self):
        """The TRI does not exist on this feed and a sector proxy is a
        different index. Pinned so nobody reads `price_index` as an oversight to
        be tidied away by swapping in a proxy."""
        import inspect

        from app.services import benchmark_service

        src = inspect.getsource(benchmark_service)
        assert "total-return index" in src or "total return index" in src.lower()
        # No proxy was substituted.
        assert "NIFTYBEES" not in src
        assert "NIFTYIETF" not in src
        assert "^NSEITRI" not in src and "^NSEI TRI" not in src
        # And the symbol itself is untouched: still the price index.
        assert BENCHMARK_SYMBOL == "^NSEI"