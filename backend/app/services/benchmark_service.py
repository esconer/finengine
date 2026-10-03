"""
Benchmark index service - ingests and serves NIFTY 50 (^NSEI) returns.

The benchmark unlocks beta/alpha, R-squared, regime detection and honest
tear-sheet comparisons. Data flows through the existing DataService cache
(stock_timeseries table), so ^NSEI rows are fetched once per TTL window.
"""

from datetime import datetime, timedelta
import inspect
from typing import Optional

import pandas as pd

from app.services.data_service import DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

BENCHMARK_SYMBOL = "^NSEI"  # NIFTY 50
BENCHMARK_NAME = "NIFTY 50"

# Close-price column candidates, in DataService (lowercase) and yfinance
# (Title-case) spellings — single source shared by frame and series readers.
_CLOSE_CANDIDATES = ("adj_close", "close", "Adj Close", "Close")

#: WHAT THE BENCHMARK LEG OF EVERY RELATIVE MEASUREMENT IS.
#:
#: `^NSEI` is a PRICE index. Its daily returns are `pct_change` of an index
#: LEVEL, so constituent dividends are not reinvested into them; a total-return
#: index would compound them back in. Nothing in this service corrects for that,
#: so every figure measured against this leg is a comparison against a price
#: index: `beta_vs_benchmark`, `alpha`, `annualized_alpha`, `r_squared`, the
#: `benchmark_cagr` / `sharpe` / `volatility` a tear sheet prints, AND the whole
#: HMM regime classification — the regime model is fitted on exactly these
#: returns, so a basis that is unstated is not a rounding note, it is an input.
#:
#: Before this constant, which column of which vendor response supplied the leg
#: was decided silently by `_CLOSE_CANDIDATES` order and published nowhere. That
#: is a disclosure defect, not a value defect: no number below changes.
#:
#: THE DATA HALF IS DEFERRED, and deliberately. Sourcing a total-return index is
#: a procurement decision, not a code fix: there is no `^NSEI` TRI on the
#: available feed, and a sector ETF proxy is a different index, not the same one
#: with dividends. Substituting one would be exactly the stand-in this
#: disclosure exists to prevent, so the basis is named instead.
BENCHMARK_RETURN_BASIS = "price_index"

#: Attribute keys carrying the disclosure on the objects this service returns.
BENCHMARK_PRICE_COLUMN_ATTR = "benchmark_price_column"
BENCHMARK_RETURN_BASIS_ATTR = "benchmark_return_basis"


def resolve_close_column(df: pd.DataFrame) -> Optional[str]:
    """Which column of `df` supplied the price leg, or None if there is none.

    Single source for the `_CLOSE_CANDIDATES` order, so the column a disclosure
    NAMES is by construction the column a reader was actually served. The
    candidates run adjusted-close first, so a vendor response carrying both
    `adj_close` and `close` resolves to the adjusted leg — which for an INDEX is
    the same series, but that is a property of indices and not something a
    consumer of this service should have to know.
    """
    if df is None:
        return None
    return next((c for c in _CLOSE_CANDIDATES if c in df.columns), None)


def benchmark_basis_disclosure(df: pd.DataFrame) -> dict:
    """The `symbol` / `name` / basis block a benchmark-relative payload needs.

    Meant to be merged into a metadata block so the reader is told which index
    and which BASIS its relative figures were measured on, instead of inferring
    it from the symbol alone. `price_column` is None when the frame carried no
    close column at all: the measurement was then never taken, and the null says
    so rather than naming a column that was not there.
    """
    return {
        "symbol": BENCHMARK_SYMBOL,
        "name": BENCHMARK_NAME,
        "price_column": resolve_close_column(df),
        "return_basis": BENCHMARK_RETURN_BASIS,
    }


def _close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Date-indexed close-price series from any DataService frame shape."""
    if df is None or df.empty:
        return None
    price_col = resolve_close_column(df)
    if price_col is None:
        return None
    values = df[price_col]
    for dcol in ("date", "Date"):
        if dcol in df.columns:
            idx = pd.to_datetime(df[dcol], errors="coerce")
            return pd.Series(values.values, index=idx, name=price_col).dropna()
    if isinstance(df.index, pd.DatetimeIndex):
        out = values.copy()
        out.index = pd.to_datetime(df.index)
        return out
    return None


class BenchmarkService:
    """Fetch/cache the NIFTY 50 index and expose daily returns."""

    def __init__(self, db_session):
        self.data_service = DataService(db_session)

    async def ensure_history(
        self,
        days: int = 756,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        """Fetch ^NSEI through the shared cache for an explicit date window.

        ``start``/``end`` are part of the service contract so historical
        callers are not silently anchored to the server's current date.
        ``days`` remains the default-window convenience for existing callers.
        """
        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = (
            datetime.strptime(start, "%Y-%m-%d")
            if start
            else end_dt - timedelta(days=int(days))
        )
        return await self.data_service.fetch_historical_data(
            BENCHMARK_SYMBOL,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
        )

    async def get_benchmark_df(self, days: int = 1100) -> Optional[pd.DataFrame]:
        """Date-indexed OHLCV DataFrame of the benchmark.

        Carries the basis disclosure in `df.attrs` (see
        `BENCHMARK_RETURN_BASIS`), set on the object that is actually returned
        rather than relying on `attrs` surviving the `copy()` and the index
        assignment above.
        """
        df = await self.ensure_history(days=days)
        if df is None or df.empty:
            return None
        out = df.copy()
        for dcol in ("date", "Date"):
            if dcol in out.columns:
                out.index = pd.to_datetime(out[dcol], errors="coerce")
                break
        close_col = resolve_close_column(out)
        result = out.dropna(subset=[close_col]) if close_col else out
        _attach_basis_disclosure(result, close_col)
        return result

    async def get_returns(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        days: int = 756,
    ) -> Optional[pd.Series]:
        """Daily simple returns of the benchmark, indexed by date.

        The fetch window is anchored to the requested ``end`` date, not to
        ``datetime.now()``.  This is essential for historical tear sheets and
        factor windows.

        The basis disclosure rides on the returned series in `series.attrs` (see
        `BENCHMARK_RETURN_BASIS`), so a consumer that holds this leg knows which
        index it is and whether dividends are in it WITHOUT having to re-derive
        it from the vendor column name. `attrs` is metadata only - it changes no
        value, no index and no name.
        """
        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = (
            datetime.strptime(start, "%Y-%m-%d")
            if start
            else end_dt - timedelta(days=int(days))
        )
        start_text = start_dt.strftime("%Y-%m-%d")
        end_text = end_dt.strftime("%Y-%m-%d")
        span_days = max(0, (end_dt - start_dt).days)
        fetch_days = max(int(days), span_days)

        # Keep compatibility with lightweight test doubles/older subclasses
        # that expose the historical ``ensure_history(days=...)`` signature.
        try:
            parameters = inspect.signature(self.ensure_history).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_explicit_window = (
            "start" in parameters
            or "end" in parameters
            or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        )
        if accepts_explicit_window:
            df = await self.ensure_history(
                days=fetch_days, start=start_text, end=end_text
            )
        else:
            df = await self.ensure_history(days=fetch_days)

        series = _close_series(df)
        if series is None:
            logger.warning("No benchmark data available for %s", BENCHMARK_SYMBOL)
            return None

        series = series.loc[
            (series.index >= pd.Timestamp(start_text))
            & (series.index <= pd.Timestamp(end_text))
        ]
        returns = series.pct_change(fill_method=None).dropna()
        returns.name = "benchmark"
        # `series.name` IS the resolved column (`_close_series` names the series
        # after it), so the disclosure reads the resolution rather than
        # re-deriving it and risking a disagreement.
        _attach_basis_disclosure(returns, series.name)
        return returns if not returns.empty else None


def _attach_basis_disclosure(obj, price_column: Optional[str]) -> None:
    """Stamp the basis disclosure onto a returned frame or series, in place.

    Only metadata: `attrs` carries no value, index or name, so this cannot move
    a number. `price_column` is stored even when it is None, because "no close
    column was present" is the answer a reader needs when a measurement was not
    taken - a missing key would be read as an unrecorded disclosure.
    """
    obj.attrs[BENCHMARK_PRICE_COLUMN_ATTR] = price_column
    obj.attrs[BENCHMARK_RETURN_BASIS_ATTR] = BENCHMARK_RETURN_BASIS
