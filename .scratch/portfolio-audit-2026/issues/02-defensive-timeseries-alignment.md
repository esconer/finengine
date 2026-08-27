# Issue 02: Defensive Timeseries Index Alignment in Quant Services

Status: closed

## Description
When calculating rolling correlations or tail risk matrices across newly added assets with unequal timeseries history (e.g. 250 daily bars for a cached ticker vs 904 bars for a fresh fetch), service methods must defensively align series on date index with forward-fill and dropna to prevent empty return matrices.

## Proposed Fix
Ensure `TailRiskService`, `VolatilityService`, and `CorrelationService` sanitize and align non-uniform input series prior to statistical operations, falling back gracefully if overlapping data points are insufficient.
