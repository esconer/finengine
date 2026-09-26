import json
from collections import Counter
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

print("=== pairs: overlap_end distribution across 91 rows (as_of claims 2026-09-25) ===")
pe = Counter(p['overlap_end'] for p in S['pairs']['data']['pairs'])
for k in sorted(pe): print("   %s : %d pairs" % (k, pe[k]))
print("   min overlap_end =", min(pe), " max =", max(pe), " as_of =", S['pairs']['as_of'])
print("   rows OLDER than the section as_of:", sum(c for k, c in pe.items() if k < S['pairs']['as_of']))

print()
print("=== liquidity: implied observation counts behind avg_volume (n = round to plausible int) ===")
bp = S['liquidity']['data']['by_position']
print("%-16s %22s %10s %10s %14s %10s %10s" % ('ticker','avg_volume','n?','spread','market_cap','prov','is_est'))
for t in sorted(bp):
    v = bp[t]['avg_volume']
    ns = [n for n in range(1, 40) if abs(v * n - round(v * n)) < 1e-6 * max(1, abs(v * n)) and n <= 30]
    print("%-16s %22.10f %10s %10s %14.0f %10s %10s" % (t, v, ns[:5], bp[t]['spread'], bp[t]['market_cap'], bp[t]['market_cap_provenance'], bp[t]['is_estimate']))
print()
print("liquidity data_range:", json.dumps(S['liquidity']['data'].get('data_range')))
ow = S['liquidity']['data'].get('observation_window')
print("observation_window.start/end:", ow.get('start'), ow.get('end'))
print("per_ticker non-null windows:", {k: v for k, v in (ow.get('per_ticker') or {}).items() if v.get('start') or v.get('end')})
print("liquidity data keys:", list(S['liquidity']['data'].keys()))
print("liquidity as_of:", S['liquidity']['as_of'], " status:", S['liquidity']['status'], " currency:", S['liquidity']['currency'])

print()
print("=== dashboard summary vs portfolio total_value ===")
comp = S['dashboard']['data']['components']
sm = comp.get('summary')
sdata = sm.get('data') if isinstance(sm, dict) else None
if isinstance(sdata, dict):
    print("summary keys:", list(sdata.keys()))
    for k in ('total_value','total_cost','total_pnl','day_change','currency','as_of','latest_observation_date'):
        if k in sdata: print("   %s = %s" % (k, json.dumps(sdata[k])[:120]))
    print("   summary.total_value == portfolio.total_value ?", sdata.get('total_value') == S['portfolio']['data']['total_value'])
dp = comp.get('portfolio', {}).get('data')
print("dashboard.components.portfolio total_value:", dp.get('total_value'), " == portfolio section? ", dp.get('total_value') == S['portfolio']['data']['total_value'])
print("dashboard.components.portfolio positions identical to portfolio section positions?", dp.get('positions') == S['portfolio']['data']['positions'])
print("dashboard.components.portfolio as_of:", comp.get('portfolio',{}).get('data',{}).get('as_of'))

print()
print("=== performance_history: last delivered portfolio value vs LIVE total_value ===")
ph = comp['performance_history']
rows = ph.get('data') or []
print("  n rows:", len(rows), " first date:", rows[0].get('date'), " last date:", rows[-1].get('date'))
print("  last row keys:", list(rows[-1].keys()))
print("  last row:", json.dumps(rows[-1])[:500])
live = S['portfolio']['data']['total_value']
for r_ in rows[-3:]:
    pv = r_.get('portfolio_value')
    print("   date=%s portfolio_value=%s  vs LIVE %s -> gap %.2f%%" % (r_.get('date'), pv, live, (pv-live)/live*100 if pv else float('nan')))
print("  history_coverage:", json.dumps(ph.get('history_coverage'))[:700])
print("  withheld_portfolio_observations:", json.dumps(rows[-1].get('withheld_portfolio_observations'))[:400])
