# Issue 01: Fix Backend Portfolio NameError total_weight (HTTP 500)

Status: closed
Type: bug
Priority: P0
Blocked by: —

## Problem Description
GET /api/v1/portfolio?currency=INR crashes with HTTP 500:
NameError: name 'total_weight' is not defined at backend/app/api/portfolio.py:130.
This blocks Page 1 (/dashboard) and Page 17 (/portfolio/manage).

## Fix
In backend/app/api/portfolio.py in get_portfolio, define:
total_weight = sum(p.weight for p in position_responses)
before building the PortfolioResponse.
