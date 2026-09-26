import json
from fractions import Fraction
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

print("=== dashboard summary: portfolio_value / last_updated ===")
sm = S['dashboard']['data']['components']['summary']['data']
for k in ('portfolio_value','portfolio_value_currency','last_updated','latest_observation_date','total_positions',
          'liquidity_score','concentration_score','risk_score','max_drawdown','sharpe_ratio','realized_volatility',
          'forecast_volatility','portfolio_return_observations','history_coverage','data_status'):
    print("  %-32s %s" % (k, json.dumps(sm.get(k))[:200]))
live = S['portfolio']['data']['total_value']
print("\n  LIVE portfolio.total_value           = %r" % live)
print("  dashboard summary.portfolio_value    = %r" % sm.get('portfolio_value'))
print("  identical? %s   delta = %+.6f  (%.4f%%)" % (sm.get('portfolio_value') == live, (sm.get('portfolio_value') or 0) - live, ((sm.get('portfolio_value') or 0)-live)/live*100))
print("  summary.last_updated vs portfolio.as_of: %s vs %s" % (sm.get('last_updated'), S['portfolio']['as_of']))
print("  summary.component data as_of:", S['dashboard']['data']['component_as_of']['summary'])

print()
print("=== dashboard summary fields that are None / withheld ===")
for k, v in sm.items():
    if v is None:
        print("  NULL:", k)

print()
print("=== performance_history: recompute daily returns ===")
rows = S['dashboard']['data']['components']['performance_history']['data']
prev = None
bad = 0
for r in rows:
    pv = r['portfolio_value']; ret = r['return']
    if prev is not None and prev > 0:
        exp = (pv/prev - 1)
        if abs(exp - ret) > 5e-7:
            bad += 1
            print("   date=%s published return=%r recomputed=%.8f  d=%+.2e" % (r['date'], ret, exp, ret-exp))
    prev = pv
print("  rows=%d  return-vs-recomputed mismatches=%d" % (len(rows), bad))
print("  first row return=%r (warm_up=%s) -> no prior pv in delivered window" % (rows[0]['return'], rows[0].get('warm_up')))
print("  series_end_reason (last row):", json.dumps(rows[-1].get('series_end_reason')))
print("  withheld_portfolio_observation_count (last row):", rows[-1].get('withheld_portfolio_observation_count'))

print()
print("=== liquidity: exact implied observation counts (Fraction.limit_denominator) ===")
bp = S['liquidity']['data']['by_position']
print("  volume_stats:", json.dumps(S['liquidity']['data'].get('volume_stats'))[:400])
print("  requested_days:", S['liquidity']['data'].get('requested_days'), " latest_observation_date:", S['liquidity']['data'].get('latest_observation_date'))
print("  %-16s %20s %-24s %s" % ('ticker','avg_volume','exact n candidates','implied total volume'))
for t in sorted(bp):
    v = bp[t]['avg_volume']
    cands = []
    for n in range(1, 31):
        if abs(v*n - round(v*n)) < 1e-6:
            cands.append(n)
    # smallest n whose product is plausibly a share count
    n = cands[0] if cands else None
    print("  %-16s %20.6f %-24s %s" % (t, v, cands[:6], (round(v*n) if n else None)))

print()
print("=== liquidity: non_measured market caps disclosure ===")
liq = S['liquidity']['data']
for k in ('estimated_market_cap_count','measured_market_cap_count','market_cap_count','non_measured_market_caps',
          'non_measured_by_provenance','fallback_market_cap_count','estimated_market_cap_basis','currency_basis','monetary_unit','volume_unit','turnover_unit','data_status'):
    print("  %-32s %s" % (k, json.dumps(liq.get(k))[:260]))
print("  liquidity.warnings (payload-level):")
for w in (liq.get('warnings') or []): print("     -", str(w)[:200])
