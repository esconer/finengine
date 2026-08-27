# Issue 05: Standardize Currency to INR and Fix Market Cap on Liquidity Page

Status: closed
Type: bug
Priority: P2
Blocked by: —

## Problem Description
On Page 7 (/dashboard/liquidity):
1. Currency is formatted in '$' instead of '₹' ($11.1M, $22.7M).
2. Market Cap displays '$0' for Indian equities INFY.NS and HDFCBANK.NS.

## Fix
In frontend/src/app/dashboard/liquidity/page.tsx:
1. Standardize formatCurrency to use '₹' symbol.
2. Ensure Market Cap is fetched or fallback computed from stock price * shares outstanding or valid Screener.in fundamentals.
