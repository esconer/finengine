import json, math
from collections import Counter
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
ps = d['sections']['portfolio']['data']['positions']

print("=== PRICE / PROVENANCE TABLE ===")
print(f"{'ticker':<15}{'qty':>7}{'buy_price':>14}{'last_price':>22}{'mv':>22}{'added_on':>22}{'updated_on':>28}{'nat':>5}{'fx':>6}")
for r in ps:
    print(f"{r['ticker']:<15}{r['quantity']:>7}{r['buy_price']:>14.4f}{r['last_price']:>22.10f}{r['market_value']:>22.8f}{str(r['added_on']):>22}{str(r['updated_on']):>28}{r['native_currency']:>5}{r['fx_rate']:>6}")

print()
print("=== updated_on distribution (price timestamp) ===")
for v,c in Counter(r['updated_on'] for r in ps).most_common():
    print(f"  {c:>3}x  {v}")
print()
print("=== added_on distribution ===")
for v,c in Counter(r['added_on'] for r in ps).most_common():
    print(f"  {c:>3}x  {v}")
print()
print("=== native vs value currency / fx identity ===")
for r in ps:
    if r['native_currency']!=r['value_currency'] or r['fx_rate']!=1 or r['fx_provenance'].get('provenance')!='identity':
        print("  NONIDENTITY:", r['ticker'], r['native_currency'], r['value_currency'], r['fx_rate'], r['fx_provenance'])
print("  (none printed above => all identity/INR)")
print()
print("=== base vs native field equality ===")
pairs=[('market_value','market_value_base'),('buy_price','buy_price_base'),('last_price','last_price_base'),
       ('current_value','current_value_base'),('total_cost','total_cost_base'),
       ('unrealized_gain_loss','unrealized_gain_loss_base'),('unrealized_gain_loss_pct','unrealized_gain_loss_pct_base')]
bad=0
for r in ps:
    for a,b in pairs:
        if r[a]!=r[b]:
            print(f"  MISMATCH {r['ticker']} {a}={r[a]!r} {b}={r[b]!r} ratio={r[b]/r[a] if r[a] else None}")
            bad+=1
print(f"  base-vs-native mismatches: {bad}")
print()
print("=== current_value vs market_value ===")
for r in ps:
    if r['current_value']!=r['market_value']:
        print("  DIFF", r['ticker'], r['current_value'], r['market_value'])
print("  all equal" )
print()
print("=== rounding check: any 2dp-rounded value? ===")
for r in ps:
    for f in ('market_value','total_cost','unrealized_gain_loss','last_price','buy_price'):
        v=r[f]
        if abs(v-round(v,2))>1e-12:
            pass
        else:
            pass
raw=sum(1 for r in ps for f in ('market_value',) if abs(r[f]-round(r[f],2))>1e-9)
print(f"  positions with full-precision (non-2dp) market_value: {raw}/14")
print()
print("=== SELECTIPO deep dive ===")
for r in ps:
    if 'SELECTIPO' in r['ticker'] or 'JUNIOR' in r['ticker'] or 'NIFTY' in r['ticker']:
        print(json.dumps(r,indent=1))
