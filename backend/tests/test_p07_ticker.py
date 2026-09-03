"""P0-7 contract tests: ticker canonicalization never fabricates NSE listings.

Regression gate for BACKEND_REVIEW P0-7 (canonical_ticker forced .NS on
every bare symbol, so AAPL became AAPL.NS with currency INR/exchange NSE;
substring suffix test also matched FOO.NSX).
"""

from app.services.data_service import DataService, canonical_ticker


def test_us_tickers_pass_through():
    assert canonical_ticker("AAPL") == "AAPL"
    assert canonical_ticker("msft") == "MSFT"
    assert canonical_ticker("BRK.B") == "BRK.B"


def test_known_indian_bare_gets_ns():
    assert canonical_ticker("RELIANCE") == "RELIANCE.NS"
    assert canonical_ticker("infy") == "INFY.NS"
    assert canonical_ticker("HDFCBANK") == "HDFCBANK.NS"


def test_unknown_bare_passes_through():
    assert canonical_ticker("SOMEUNKNOWN") == "SOMEUNKNOWN"


def test_suffix_is_suffix_not_substring():
    assert canonical_ticker("TCS.NS") == "TCS.NS"
    assert canonical_ticker("500112.BO") == "500112.BO"
    assert canonical_ticker("FOO.NSX") == "FOO.NSX"
    assert canonical_ticker("3MINDIA.NS") == "3MINDIA.NS"
    assert canonical_ticker("MOTHERSON.NS") == "MOTHERSON.NS"
    assert canonical_ticker("BAJAJ-AUTO.NS") == "BAJAJ-AUTO.NS"


def test_yahoo_native_passthrough():
    assert canonical_ticker("^NSEI") == "^NSEI"
    assert canonical_ticker("USDINR=X") == "USDINR=X"


def test_is_indian_ticker():
    svc = DataService.__new__(DataService)
    svc.popular_indian_stocks = ["RELIANCE.NS"]
    assert svc._is_indian_ticker("RELIANCE.NS") is True
    assert svc._is_indian_ticker("TCS.BO") is True
    assert svc._is_indian_ticker("INFY") is True
    assert svc._is_indian_ticker("AAPL") is False
    assert svc._is_indian_ticker("FOO.NSX") is False


def test_normalize_helpers_share_canonical():
    from app.services.company_data_service import _normalize as c_norm
    from app.services.equity_research_service import _normalize as e_norm
    from app.services.ai_dossier_service import _normalize as a_norm

    for norm in (c_norm, e_norm, a_norm):
        assert norm("AAPL") == "AAPL"
        assert norm("RELIANCE") == "RELIANCE.NS"
