"""Agent B deterministic regression gates for audit issues B-01..B-16."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest
import requests
from pydantic import ValidationError
from sqlalchemy import select

from app.models.database import (
    AnalyticsCache,
    AppSetting,
    NSEBhavcopy,
    NSEInstitutionalFlow,
    PortfolioPosition,
    StockTimeseries,
)
from app.models.schemas import PortfolioPositionCreate, PortfolioPositionUpdate
from app.services import cointegration_service
from app.services.alpha_vantage_service import (
    AlphaVantageIdentityError,
    AlphaVantageNotConfiguredError,
    AlphaVantageService,
    KeyPool,
    to_av_symbol,
)
from app.services.cache_service import (
    CacheService,
    ProviderRateLimitError,
    advance_cache_generation,
    clear_market_data_cache,
    get_cache_generation,
)
from app.services.company_data_service import CompanyDataService
from app.services.currency_service import (
    CurrencyConversionService,
    CurrencyUnavailableError,
    FXRate,
    coerce_live_fx_rate,
)
from app.services.data_service import DataService, accept_vendor_frame
from app.services.india_data_service import (
    IndiaDataService,
    compute_amihud_illiquidity,
    compute_days_to_liquidate,
)
from app.services.source_preference_service import set_primary_source


def _raw(start="2025-01-02", days=2, ticker="B.NS"):
    dates = pd.bdate_range(start, periods=days)
    close = np.linspace(100.0, 100.0 + days, days)
    frame = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(days, 1000),
        },
        index=dates,
    )
    frame.index.name = "Date"
    return frame


def _lower(frame, ticker="B.NS"):
    out = frame.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    out["ticker"] = ticker
    return out


@pytest.fixture(autouse=True)
def _clear_agent_b_memos():
    DataService._in_memory_df_cache.clear()
    DataService._quote_memo.clear()
    DataService._l1_sources.clear()
    DataService._l1_preferences.clear()
    DataService._quote_sources.clear()
    yield
    DataService._in_memory_df_cache.clear()
    DataService._quote_memo.clear()
    DataService._l1_sources.clear()
    DataService._quote_sources.clear()
    cointegration_service._IN_MEMORY_COINT_CACHE.clear()


@pytest.mark.asyncio
async def test_b01_runtime_controls_bypass_and_ttl(test_db):
    test_db.add(AppSetting(key="enable_cache", value="false"))
    await test_db.commit()
    service = DataService(test_db)
    vendor = AsyncMock(return_value=_raw())
    with patch.object(service, "_download_with_timeout", new=vendor):
        result = await service.fetch_historical_data("B01.NS", "2025-01-02", "2025-01-03", source_order=["yfinance"])
    assert result is not None and not result.empty
    assert vendor.await_count == 1
    assert (await test_db.execute(select(StockTimeseries))).scalars().all() == []

    await test_db.execute(AppSetting.__table__.delete().where(AppSetting.key == "enable_cache"))
    test_db.add(AppSetting(key="enable_cache", value="true"))
    test_db.add(AppSetting(key="cache_ttl_minutes", value="1"))
    await test_db.commit()
    cache = CacheService(test_db, ttl_minutes=60)
    before = datetime.utcnow()
    await cache.set_cached_analytics("B01.NS", "ttl", 1.0, before)
    row = (await test_db.execute(select(AnalyticsCache))).scalar_one()
    assert 55 <= (row.expires_at - before).total_seconds() <= 65
    service._in_memory_df_cache["B01TTL.NS"] = (datetime.now(timezone.utc).timestamp(), pd.DataFrame())
    await test_db.execute(AppSetting.__table__.update().where(AppSetting.key == "cache_ttl_minutes").values(value="2"))
    await test_db.commit()
    await service._refresh_runtime_config()
    assert "B01TTL.NS" not in service._in_memory_df_cache


@pytest.mark.asyncio
async def test_b02_purge_clears_all_memos_and_fences_inflight(test_db):
    test_db.add(StockTimeseries(
        ticker="B02.NS", date=datetime(2025, 1, 2), open=1, high=2, low=.5,
        close=1.5, adj_close=1.5, volume=10,
    ))
    test_db.add(PortfolioPosition(ticker="B02.NS", weight=1, quantity=1, buy_price=1))
    await test_db.commit()
    DataService._in_memory_df_cache["B02.NS"] = (datetime.now(timezone.utc).timestamp(), _lower(_raw(ticker="B02.NS")))
    cointegration_service._IN_MEMORY_COINT_CACHE["pair"] = (datetime.now(timezone.utc).replace(tzinfo=None), {})
    result = await clear_market_data_cache(test_db)
    assert result["portfolio_preserved"] is True
    assert not DataService._in_memory_df_cache
    assert not cointegration_service._IN_MEMORY_COINT_CACHE
    assert (await test_db.execute(select(PortfolioPosition))).scalar_one().ticker == "B02.NS"

    started = asyncio.Event()
    release = asyncio.Event()
    service = DataService(test_db)
    frame = _raw(ticker="B02RACE.NS")
    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return frame
    with patch.object(service, "_download_with_timeout", new=delayed):
        task = asyncio.create_task(service.fetch_historical_data("B02RACE.NS", "2025-01-02", "2025-01-03", source_order=["yfinance"]))
        await started.wait()
        await clear_market_data_cache(test_db)
        release.set()
        fetched = await task
    assert fetched is None or fetched.empty
    assert not (await test_db.execute(select(StockTimeseries))).scalars().all()


@pytest.mark.asyncio
async def test_b02_stale_timeseries_write_is_rejected_after_generation_change(test_db):
    service = DataService(test_db)
    generation = get_cache_generation()
    advance_cache_generation("stale-write regression")
    stored = await service._store_timeseries_data(
        "B02STALE.NS", _lower(_raw(ticker="B02STALE.NS")), generation=generation
    )
    assert stored is False
    rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
    assert not any(row.ticker == "B02STALE.NS" for row in rows)


@pytest.mark.asyncio
async def test_b02_fetch_captures_generation_before_runtime_config_await(test_db):
    service = DataService(test_db)

    async def refresh_then_advance():
        config = await service.cache.get_runtime_config()
        advance_cache_generation("purge during fetch startup")
        return config

    vendor = AsyncMock(return_value=_raw(ticker="B02START.NS"))
    with patch.object(service, "_refresh_runtime_config", new=refresh_then_advance), patch.object(
        service, "_download_with_timeout", new=vendor
    ):
        fetched = await service.fetch_historical_data(
            "B02START.NS",
            "2025-01-02",
            "2025-01-03",
            force_refresh=True,
            source_order=["yfinance"],
        )

    assert fetched is None
    vendor.assert_awaited_once()
    rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
    assert not any(row.ticker == "B02START.NS" for row in rows)


@pytest.mark.asyncio
async def test_b02_generation_change_during_upsert_rolls_back_write(test_db):
    service = DataService(test_db)
    generation = get_cache_generation()
    real_execute = test_db.execute
    execute_count = 0

    async def execute_then_advance(statement):
        nonlocal execute_count
        result = await real_execute(statement)
        execute_count += 1
        if execute_count == 2:  # runtime-config read, then timeseries upsert
            advance_cache_generation("purge during stale upsert")
        return result

    with patch.object(test_db, "execute", new=execute_then_advance):
        stored = await service._store_timeseries_data(
            "B02UPSERT.NS",
            _lower(_raw(ticker="B02UPSERT.NS")),
            generation=generation,
        )

    assert stored is False
    rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
    assert not any(row.ticker == "B02UPSERT.NS" for row in rows)


@pytest.mark.asyncio
async def test_b03_source_switch_invalidates_ticker_rows(test_db):
    test_db.add(StockTimeseries(
        ticker="B03.NS", date=datetime(2025, 1, 2), open=1, high=2, low=.5,
        close=1.5, adj_close=1.5, volume=10, source_used="bfinance",
    ))
    await test_db.commit()
    await set_primary_source(test_db, "yfinance")
    service = DataService(test_db)
    vendor = AsyncMock(return_value=_raw(ticker="B03.NS"))
    with patch.object(service, "_download_with_timeout", new=vendor):
        result = await service.fetch_historical_data("B03.NS", "2025-01-02", "2025-01-03", source_order=["yfinance"])
    assert result is not None and not result.empty
    assert vendor.await_count == 1
    assert all(row.source_used == "yfinance" for row in (await test_db.execute(select(StockTimeseries))).scalars().all())


def test_b04_typed_coverage_predicate_rejects_outside_frame():
    outside = _raw("2020-01-02", 2)
    valid = _raw("2025-01-02", 2)
    rejected = accept_vendor_frame(outside, "2025-01-02", "2025-01-03")
    accepted = accept_vendor_frame(valid, "2025-01-02", "2025-01-03")
    assert rejected.accepted is False and rejected.reason == "outside_requested_window"
    assert accepted.accepted is True


@pytest.mark.asyncio
async def test_b05_sqlite_inclusive_end_date(test_db):
    test_db.add(StockTimeseries(
        ticker="B05.NS", date=datetime(2025, 1, 3), open=1, high=2, low=.5,
        close=1.5, adj_close=1.5, volume=10,
    ))
    await test_db.commit()
    frame = await DataService(test_db)._get_cached_data("B05.NS", "2025-01-01", "2025-01-03")
    assert frame is not None and len(frame) == 1


@pytest.mark.asyncio
async def test_b06_invalid_ohlcv_quarantined_but_valid_and_large_move_kept(test_db):
    valid = _lower(_raw(days=2, ticker="B06.NS"))
    valid.loc[1, ["open", "high", "low", "close", "adj_close"]] = [-1, 0, -2, -1, -1]
    await DataService(test_db)._store_timeseries_data("B06.NS", valid)
    rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
    assert len(rows) == 1 and rows[0].close > 0
    assert any("extreme price movements" in item for item in DataService(test_db)._validate_timeseries_data(valid))


class _QuoteTicker:
    def __init__(self, symbol):
        self.fast_info = SimpleNamespace(last_price=101.0, last_volume=10, market_cap=1000, year_high=110, year_low=90)
        self.info = {"sector": None, "industry": None}


@pytest.mark.asyncio
async def test_b07_b13_quote_normalization_schema_aliases_and_provenance(test_db):
    await set_primary_source(test_db, "yfinance")
    service = DataService(test_db)
    with patch("yfinance.Ticker", _QuoteTicker), patch("bfinance.Ticker", _QuoteTicker):
        quote = await service.fetch_quote("B07.NS")
    assert quote["sector"] == "Unknown" and quote["industry"] == "Unknown"
    assert quote["week_52_high"] == quote["52_week_high"]
    assert quote["source"] == "yfinance"


@pytest.mark.asyncio
async def test_b07_b13_non_indian_quote_skips_bfinance(test_db):
    await set_primary_source(test_db, "bfinance")
    service = DataService(test_db)
    with patch("yfinance.Ticker", _QuoteTicker), patch("bfinance.Ticker", _QuoteTicker):
        quote = await service.fetch_quote("AAPL")
    assert quote["source"] == "yfinance"
    assert quote["currency"] == "USD"


def test_b07_b13_quote_identity_and_currency_conflicts_are_rejected():
    with pytest.raises(ValueError):
        DataService._normalize_quote_payload(
            {"ticker": "MSFT", "currency": "USD", "current_price": 10},
            "AAPL",
        )
    with pytest.raises(ValueError):
        DataService._normalize_quote_payload(
            {"ticker": "AAPL", "currency": "INR", "current_price": 10},
            "AAPL",
        )
    with pytest.raises(ValueError):
        DataService._normalize_quote_payload(
            {"ticker": "TCS.NS", "is_indian": False, "currency": "USD", "current_price": 10},
            "TCS.NS",
        )


@pytest.mark.asyncio
async def test_b02_quote_purge_during_startup_does_not_repopulate_memo(test_db):
    service = DataService(test_db)
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_refresh():
        started.set()
        await release.wait()
        return await service.cache.get_runtime_config()

    with patch.object(service, "_refresh_runtime_config", new=delayed_refresh), patch(
        "yfinance.Ticker", _QuoteTicker
    ), patch("bfinance.Ticker", _QuoteTicker):
        task = asyncio.create_task(service.fetch_quote("B02QUOTE.NS"))
        await started.wait()
        await clear_market_data_cache(test_db)
        release.set()
        quote = await task

    assert quote is not None and quote["current_price"] == 101.0
    assert not DataService._quote_memo


@pytest.mark.asyncio
async def test_b13_mixed_returned_window_source_is_explicit(test_db):
    test_db.add_all([
        StockTimeseries(
            ticker="MIX.NS", date=datetime(2025, 1, 2), open=1, high=2, low=.5,
            close=1.5, adj_close=1.5, volume=10, source_used="bfinance",
        ),
        StockTimeseries(
            ticker="MIX.NS", date=datetime(2025, 1, 3), open=1, high=2, low=.5,
            close=1.6, adj_close=1.6, volume=10, source_used="yfinance",
        ),
    ])
    await test_db.commit()
    result = await DataService(test_db).fetch_historical_data(
        "MIX.NS", "2025-01-02", "2025-01-03", source_order=["bfinance"]
    )
    assert result is not None and result.attrs["source"] == "mixed"


@pytest.mark.asyncio
async def test_b06_alpha_fallback_does_not_overwrite_adjusted_row(test_db):
    test_db.add(StockTimeseries(
        ticker="ADJ.NS", date=datetime(2025, 1, 2), open=100, high=102, low=99,
        close=101, adj_close=50, volume=100, source_used="yfinance",
    ))
    await test_db.commit()
    frame = _lower(_raw(days=1, ticker="ADJ.NS"))
    frame.loc[0, "date"] = datetime(2025, 1, 2)
    await DataService(test_db)._store_timeseries_data("ADJ.NS", frame, source_used="alphavantage")
    row = (await test_db.execute(select(StockTimeseries).where(StockTimeseries.ticker == "ADJ.NS"))).scalar_one()
    assert row.adj_close == 50
    assert row.source_used == "yfinance"


@pytest.mark.asyncio
async def test_b08_av_does_not_substitute_exchange_identity():
    assert to_av_symbol("RELIANCE.NS") is None
    assert to_av_symbol("RELIANCE.BSE") is None
    assert to_av_symbol("AAPL") == "AAPL"
    service = AlphaVantageService()
    with patch.object(service, "_make_request", new=AsyncMock(return_value={"Global Quote": {"01. symbol": "OTHER", "05. price": "10"}})):
        with pytest.raises(AlphaVantageIdentityError):
            await service.fetch_global_quote("AAPL")


@pytest.mark.asyncio
async def test_b09_typed_provider_errors_and_redaction(caplog):
    service = AlphaVantageService()
    service.pool = KeyPool(["FAKE_SECRET"], 25, 5)
    class Unauthorized:
        status_code = 401
        def raise_for_status(self):
            raise requests.HTTPError("https://alphavantage.co/query?apikey=FAKE_SECRET")
        def json(self):
            return {}
    with patch("app.services.alpha_vantage_service.requests.get", return_value=Unauthorized()):
        with pytest.raises(AlphaVantageNotConfiguredError):
            await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})
    assert "FAKE_SECRET" not in caplog.text and "apikey=" not in caplog.text

    rate = AlphaVantageService()
    rate.pool = KeyPool(["FAKE_SECRET"], 25, 5)
    class Limited:
        status_code = 429
        def raise_for_status(self):
            raise requests.HTTPError("https://alphavantage.co/query?apikey=FAKE_SECRET")
        def json(self):
            return {}
    with patch("app.services.alpha_vantage_service.requests.get", return_value=Limited()):
        with pytest.raises(ProviderRateLimitError):
            await rate._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})


def _bhav(symbol, close=100.0):
    return {
        "symbol": symbol, "open": close - 1, "high": close + 1, "low": close - 2,
        "close": close, "prev_close": close, "avg_price": close, "ttl_trd_qnty": 100,
        "turnover_lacs": 10.0, "no_of_trades": 5,
    }


@pytest.mark.asyncio
async def test_b10_ingestion_rejects_dedupes_corrects_and_preserves(test_db):
    service = IndiaDataService(test_db)
    day = datetime(2025, 1, 2)
    invalid = {**_bhav("BAD"), "close": None}
    first = _bhav("GOOD", 100)
    correction = _bhav("GOOD", 110)
    assert await service.ingest_bhavcopy_records([invalid, first, correction], day) == 1
    assert await service.ingest_bhavcopy_records([_bhav("GOOD", 110)], day) == 0
    row = (await test_db.execute(select(NSEBhavcopy).where(NSEBhavcopy.symbol == "GOOD"))).scalar_one()
    assert row.close == 110
    assert (await test_db.execute(select(NSEBhavcopy).where(NSEBhavcopy.symbol == "BAD"))).scalar_one_or_none() is None
    assert await service.ingest_institutional_flow(day, "FII", 100, 40) is True
    assert await service.ingest_institutional_flow(day, "FII", 120, 50) is True
    flow = (await test_db.execute(select(NSEInstitutionalFlow))).scalar_one()
    assert flow.net_value_crores == 70


@pytest.mark.asyncio
async def test_b11_institutional_flow_lookback_counts_stored_sessions(test_db):
    service = IndiaDataService(test_db)
    await service.ingest_institutional_flow(datetime(2025, 1, 1), "FII", 10, 5)
    await service.ingest_institutional_flow(datetime(2025, 1, 2), "FII", 20, 5)
    await service.ingest_institutional_flow(datetime(2025, 1, 5), "FII", 30, 5)
    flows = await service.get_institutional_flows(lookback_days=2)
    assert [item["date"] for item in flows] == ["2025-01-02", "2025-01-05"]


@pytest.mark.asyncio
async def test_b11_missing_liquidity_is_null_and_valid_formula_measured(test_db):
    position = PortfolioPosition(ticker="B11.NS", quantity=10, buy_price=10, last_price=10, market_value=100, weight=1)
    missing = await IndiaDataService(test_db).calculate_portfolio_liquidity_limits([position], {})
    assert missing["positions"][0]["adv_30d_shares"] is None
    assert missing["positions"][0]["amihud_illiquidity"] is None
    assert missing["positions"][0]["days_to_liquidate_10pct_adv"] is None
    close = pd.Series([100.0, 101.0], index=pd.bdate_range("2025-01-02", periods=2))
    volume = pd.Series([1000.0, 1000.0], index=close.index)
    measured = await IndiaDataService(test_db).calculate_portfolio_liquidity_limits(
        [position], {"B11.NS": pd.DataFrame({"close": close, "volume": volume})}
    )
    row = measured["positions"][0]
    assert row["adv_30d_shares"] == 1000.0
    assert row["days_to_liquidate_10pct_adv"] > 0
    assert row["data_status"] in {"measured", "partial"}
    assert compute_days_to_liquidate(100, 1000, .1) == 1.0
    assert compute_amihud_illiquidity(pd.Series([.01]), pd.Series([1000.])) > 0


@pytest.mark.asyncio
async def test_b11_liquidity_uses_base_currency_values_and_fx(test_db):
    positions = [
        PortfolioPosition(ticker="AAPL", region="US", quantity=1, buy_price=90, last_price=100, market_value=100, weight=.5),
        PortfolioPosition(ticker="TCS.NS", region="IN", quantity=1, buy_price=80, last_price=80, market_value=80, weight=.5),
    ]
    index = pd.bdate_range("2025-01-02", periods=2)
    history = {
        "AAPL": pd.DataFrame({"close": [100.0, 100.0], "volume": [1000.0, 1000.0]}, index=index),
        "TCS.NS": pd.DataFrame({"close": [80.0, 80.0], "volume": [1000.0, 1000.0]}, index=index),
    }
    result = await IndiaDataService(test_db).calculate_portfolio_liquidity_limits(
        positions,
        history,
        converted_values={"AAPL": 8000.0, "TCS.NS": 80.0},
        fx_rates={"AAPL": 80.0, "TCS.NS": 1.0},
        base_currency="INR",
        currency_provenance={"aggregation": "per_position_conversion"},
    )
    assert result["portfolio_value"] == pytest.approx(8080.0)
    assert result["currency"] == result["base_currency"] == "INR"
    rows = {row["ticker"]: row for row in result["positions"]}
    assert rows["AAPL"]["position_value"] == pytest.approx(8000.0)
    assert rows["AAPL"]["position_value_native"] == pytest.approx(100.0)
    assert rows["AAPL"]["adv_30d_rupees"] == pytest.approx(8_000_000.0)


@pytest.mark.asyncio
async def test_b12_fx_fallback_is_marked_and_currency_contract_honest():
    service = CurrencyConversionService()
    with patch("yfinance.Ticker", side_effect=ConnectionError("down")):
        rate = await service.get_exchange_rate("USD", "INR")
    assert isinstance(rate, FXRate) and rate == 83.0
    info = service.get_exchange_rate_info()
    assert info["is_fallback"] is True and info["provenance"] == "fallback"
    assert info["age_seconds"] >= 0
    with patch("yfinance.Ticker", side_effect=ConnectionError("down")):
        with pytest.raises(CurrencyUnavailableError):
            await service.convert_amount(100, "USD", "INR")
    fallback = FXRate(83.0, provenance="fallback", source="fallback_constant")
    with patch.object(service, "get_exchange_rate", new=AsyncMock(return_value=fallback)):
        with pytest.raises(CurrencyUnavailableError):
            await service.convert_amount_with_provenance(100, "USD", "INR")
        explicit = await service.convert_amount_with_provenance(
            100, "USD", "INR", allow_fallback=True
        )
    assert explicit["amount"] == pytest.approx(8300.0)
    assert explicit["rate"]["is_fallback"] is True
    assert "EUR" not in info["supported_currencies"]
    with pytest.raises(ValueError):
        await service.get_exchange_rate("EUR", "INR")


def test_b12_unlabelled_numeric_fx_adapter_is_not_live():
    with pytest.raises(CurrencyUnavailableError):
        coerce_live_fx_rate(83.0)
    with pytest.raises(CurrencyUnavailableError):
        coerce_live_fx_rate({"rate": 83.0, "is_fallback": False})


@pytest.mark.asyncio
async def test_b13_batch_uses_canonical_keys(test_db):
    service = DataService(test_db)
    frame = _lower(_raw(ticker="RELIANCE.NS"))
    with patch.object(service, "fetch_historical_data", new=AsyncMock(return_value=frame)):
        result = await service.fetch_ohlcv_batch(["RELIANCE"], start_date="2025-01-02", end_date="2025-01-03")
    assert set(result["data"]) == {"RELIANCE.NS"}


@pytest.mark.asyncio
async def test_b15_precedence_and_statement_source(test_db):
    await set_primary_source(test_db, "yfinance")
    service = DataService(test_db)
    yf_frame = _raw(ticker="B15.NS")
    def yf_download(*args, **kwargs):
        return yf_frame
    def bf_download(*args, **kwargs):
        raise AssertionError("bfinance must not run before yfinance")
    with patch("yfinance.download", yf_download), patch("bfinance.download", bf_download):
        result = await service.fetch_historical_data("B15.NS", "2025-01-02", "2025-01-03", force_refresh=True, source_order=["yfinance", "bfinance"])
    assert result is not None and not result.empty
    assert result.attrs["source"] == "yfinance"

    with patch("yfinance.Ticker", return_value=Mock(info={"longName": "B15", "marketCap": 100.0, "returnOnEquity": .1})):
        fundamentals = await CompanyDataService().get_fundamentals("B15", source_order=["yfinance"])
    assert fundamentals["source"] == "yfinance"


@pytest.mark.parametrize("field", ["quantity", "buy_price"])
def test_b16_portfolio_request_fields_reject_positive_infinity(field):
    payload = {
        "ticker": "AAPL",
        "weight": 0.5,
        "quantity": 1.0,
        "buy_price": 100.0,
    }
    payload[field] = float("inf")

    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**payload)
    with pytest.raises(ValidationError):
        PortfolioPositionUpdate(**{field: float("inf")})
