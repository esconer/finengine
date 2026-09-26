import json, math
d = json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json', encoding='utf-8'))
S = d['sections']; ps = S['portfolio']['data']['positions']
w = {r['ticker']: r['weight'] for r in ps}
c = S['concentration']['data']
ws = sorted(w.values(), reverse=True); hhi = sum(x*x for x in ws)
for n in (3,5,10):
    pub = c['top_%d' % n]; rec = sum(ws[:n])
    print('top_%-2d published=%-22r recomputed=%-22r d=%+.3e' % (n, pub, rec, pub-rec))
lp = c['largest_position']
print('largest  published=%-22r recomputed=%-22r d=%+.3e' % (lp, ws[0], lp-ws[0]))
n = len(ws); s = sorted(ws)
gini = (2*sum((i+1)*x for i,x in enumerate(s))/(n*sum(s))) - (n+1)/n
print('gini pub=%s rec=%.6f d=%+.6f' % (c['gini_coefficient'], gini, c['gini_coefficient']-gini))
print('div_ratio pub=%s  1/HHI=%.6f  N/n=%.6f  sqrt=%.6f' % (c['diversification_ratio'], 1/hhi, 1/hhi/n, math.sqrt(n)/math.sqrt(sum(x*x for x in s))))
print('div_score pub=%s  (1-HHI)*100=%.4f  (1-gini)*100=%.4f' % (c['diversification_score'], (1-hhi)*100, (1-gini)*100))
print()
print('SECTORS portfolio sum =', sum(S['portfolio']['data']['sectors'].values()))
tot = 0
for k in sorted(c['by_sector'], key=lambda k: -c['by_sector'][k]):
    full = S['portfolio']['data']['sectors'].get(k); pub = c['by_sector'][k]
    r = round(full, 4); tot += pub - r
    print('  %-24s full=%-24r round4=%-10r pub=%-10r %s d=%+.2e' % (k, full, r, pub, 'OK' if abs(pub-r) < 1e-12 else 'MISMATCH', pub-r))
print('  residual=%+.3e published_residual=%s decimals=%s total=%s' % (tot, c['by_sector_rounding_residual'], c['by_sector_rounding_decimals'], c['by_sector_total']))
print()
bad = [(t, v, w.get(t)) for t, v in c['by_weight'].items() if v != w.get(t)]
print('by_weight mismatches:', bad)
print('n by_weight:', len(c['by_weight']), 'sum:', sum(c['by_weight'].values()))
print('missing from by_weight:', set(w)-set(c['by_weight']), ' extra:', set(c['by_weight'])-set(w))
print()
print('concentration methodology:', c.get('methodology'))
print('stress methodology sample:', S['stress_testing']['data']['scenarios']['Market Crash'].get('methodology'))
print()
print('stress_testing: does any scenario use portfolio weights? sector keys present?')
mc = S['stress_testing']['data']['scenarios']['Market Crash']
print(json.dumps({k: v for k, v in mc.items() if k != 'methodology'}, indent=1)[:2500])
