# 31 — Options Greeks & Implied Volatility Surface Tracking

Status: needs-info
Type: feature
Blocked by: —

## What
If options hedging is introduced:
- Ingest NIFTY and stock options chain data (strikes, expiries, premiums).
- Compute Delta, Gamma, Vega, Theta, and Rho exposures across portfolio positions using `financepy` or Black-Scholes.
- Plot implied volatility (IV) smile / surface to identify cheap hedge strikes.

## Why
Answers "how much does a 5% market crash hurt my portfolio with options hedges in place".

## Proof of done
- [ ] Options position inputs output net portfolio delta and vega.
