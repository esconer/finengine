import json, math
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']
ps = S['portfolio']['data']['positions']
w = {r['ticker']: r['weight'] for r in ps}
mv = {r['ticker']: r['market_value'] for r in ps}
TV = S['portfolio']['data']['total_value']

print("=== SELECTIPO + unmeasured-caps liquidity legs ===")
for t in ('SELECTIPO.NS','JUNIORBEES.NS','NIFTYIETF.NS','MAFANG.NS','MIDCAPIETF.NS'):
    print(json.dumps(S['liquidity']['data']['by_position'][t], indent=1))

print()
print("=== CONCENTRATION RECOMPUTE from published portfolio weights ===")
c = S['concentration']['data']
ws = sorted(w.values(), reverse=True)
hhi = sum(x*x for x in ws)
print(f"published herfindahl_index   = {c['herfindahl_index']}")
print(f"recomputed sum(w^2)          = {hhi}   -> rounded4 = {round(hhi,4)}")
print(f"published effective_positions= {c['effective_positions']}  recomputed 1/HHI = {1/hhi}")
for n in (1,3,5,10):
    pub = c[f'top_{n}'] if f'top_{n}' in c else None
    rec = sum(ws[:n])
    print(f"top_{n:<2} published={pub!r:<22} recomputed={rec!r:<22} d={pub-rec:+.3e}")
print(f"largest_position published={c['largest_position']!r} recomputed={ws[0]!r} d={c['largest_position']-ws[0]:+.3e}")

# Gini
n=len(ws); s=sorted(ws)
gini = (2*sum((i+1)*x for i,x in enumerate(s))/(n*sum(s))) - (n+1)/n
print(f"gini published={c['gini_coefficient']} recomputed={gini:.6f} d={c['gini_coefficient']-gini:+.6f}")
# diversification ratio (DR = 1/sum(w^2) is effective positions; analytic DR variant)
print(f"diversification_ratio published={c['diversification_ratio']}  1/HHI={1/hhi:.6f}  (N/n)={1/hhi/n:.6f}  sqrt variant={math.sqrt(n)/math.sqrt(sum(x*x for x in s)):.6f}")
print(f"diversification_score published={c['diversification_score']}")
print(f"  (1-HHI)*100 = {(1-hhi)*100:.4f}   (1-sum(w^2))*100 = {(1-sum(x*x for x in s))*100:.4f}  (1-gini)*100 = {(1-gini)*100:.4f}")

print()
print("=== SECTOR RECONCILIATION: portfolio.sectors vs concentration.by_sector ===")
print("portfolio.sectors:")
for k,v in sorted(S['portfolio']['data']['sectors'].items(), key=lambda x:-x[1]):
    print(f"   {k:<26} {v!r}")
print("sum =", sum(S['portfolio']['data']['sectors'].values()))
print("concentration.by_sector:")
for k,v in sorted(c['by_sector'].items(), key=lambda x:-x[1]):
    print(f"   {k:<26} {v!r}")
print("sum =", sum(c['by_sector'].values()), " declared total =", c['by_sector_total'])
print()
print("by_sector 4dp rounding check vs portfolio.sectors (full precision):")
tot_resid=0
for k in c['by_sector']:
    full = S['portfolio']['data']['sectors'].get(k)
    pub  = c['by_sector'][k]
    r = round(full,4)
    tot_resid += pub-r
    flag = 'OK' if abs(pub-r)<1e-12 else 'MISMATCH'
    print(f"   {k:<26} full={full!r:<24} round4={r!r:<10} published={pub!r:<10} {flag}  delta={pub-r:+.2e}")
print(f"   residual sum = {tot_resid:+.3e}  published by_sector_rounding_residual = {c['by_sector_rounding_residual']}")

print()
print("=== by_weight cross-check: concentration.by_weight vs portfolio weights ===")
bad=0
for t,v in c['by_weight'].items():
    if abs(v-w[t])>0: print(f"   MISMATCH {t} conc={v!r} port={w[t]!r}"); bad+=1
print("   mismatches:",bad, "| n in by_weight:",len(c['by_weight']))
print("   sum(by_weight) =", sum(c['by_weight'].values()))
print("   tickers in portfolio not in by_weight:", set(w)-set(c['by_weight']))
print("   tickers in by_weight not in portfolio:", set(c['by_weight'])-set(w))
