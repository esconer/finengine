# 29 — NSE Promoter Pledge & Bulk Deal Feed Scraper

Status: needs-info
Type: feature
Blocked by: 16

## What
Build ingestion connectors for NSE quarterly shareholding pattern XML/JSON feeds and daily bulk/block deal archives:
- Track changes in promoter shareholding and promoter shares pledged (% delta quarter-over-quarter).
- Filter bulk and block deals ($>0.5\%$ of equity) to holdings and watchlist tickers.
- Surface warning badges for $>5\%$ promoter pledge increases on the India Flows page.

## Why
Promoter pledging is a critical governance and leverage risk indicator in Indian equities.

## Proof of done
- [ ] Ticker with increased promoter pledge displays a warning alert on the dashboard.
