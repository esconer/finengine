"""Agent B B-08 baseline: Alpha Vantage silently bridges NSE to BSE."""
from app.services.alpha_vantage_service import to_av_symbol
symbol = to_av_symbol("RELIANCE.NS")
bse_symbol = to_av_symbol("RELIANCE.BSE")
print({
    "requested": "RELIANCE.NS",
    "alpha_symbol": symbol,
    "identity_unavailable": symbol is None and bse_symbol is None,
    "bse_identity_unavailable": bse_symbol is None,
})
