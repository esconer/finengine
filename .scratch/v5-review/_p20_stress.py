import json, re
d = json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json', encoding='utf-8'))
S = d['sections']
KEYPAT = re.compile(r'"([a-z_]*(?:window|observations|start|end|date|as_of)[a-z_]*)"')

for k in ('concentration', 'stress_testing'):
    t = json.dumps(S[k]['data'])
    print('==', k, 'as_of=', S[k]['as_of'], 'status=', S[k]['status'], 'warnings=', len(S[k]['warnings']))
    print('   date-like substrings:', re.findall(r'20\d\d-\d\d-\d\d', t)[:5] or 'NONE')
    print('   window/obs/date keys:', sorted(set(KEYPAT.findall(t)))[:24])
print()

st = S['stress_testing']['data']['scenarios']['Market Crash']
va = st['shock_inputs']['volatility_adjustment']
print('stress vol factor sample CIPLA:', json.dumps(va['by_ticker']['CIPLA.NS']))
print('vol_adjustment keys:', list(va.keys()))
print('window/date keys in vol_adjustment:', [k for k in va if 'window' in k or 'date' in k or 'start' in k] or 'NONE')
print()

print('=== stress max_drawdown == portfolio_impact * 1.15 ===')
for n, sc in S['stress_testing']['data']['scenarios'].items():
    print('  %-26s pi=%-9s pi*1.15=%.6f  published=%-9s d=%+.2e' % (n, sc['portfolio_impact'], sc['portfolio_impact']*1.15, sc['max_drawdown'], sc['max_drawdown']-sc['portfolio_impact']*1.15))
print()
print('=== stress portfolio_impact == sum(weight * position_impact) using VERIFIED portfolio weights ===')
w = {p['ticker']: p['weight'] for p in S['portfolio']['data']['positions']}
for n, sc in S['stress_testing']['data']['scenarios'].items():
    rec = sum(w[t] * v for t, v in sc['position_impacts'].items())
    print('  %-26s recomputed=%.6f published=%-9s d=%+.2e legs=%d' % (n, rec, sc['portfolio_impact'], sc['portfolio_impact']-rec, len(sc['position_impacts'])))
print()
print('=== dashboard summary concentration_score vs concentration.herfindahl_index ===')
sm = S['dashboard']['data']['components']['summary']['data']
print('  summary.concentration_score =', sm['concentration_score'], ' concentration.herfindahl_index =', S['concentration']['data']['herfindahl_index'],
      ' HHI*100 =', S['concentration']['data']['herfindahl_index']*100)
print('  summary.risk_score =', sm['risk_score'], ' (scale? see payload)')
print('  summary.sharpe_ratio =', sm['sharpe_ratio'])
print('  summary.realized_volatility =', sm['realized_volatility'], ' forecast_volatility =', sm['forecast_volatility'])
print('  summary.max_drawdown =', sm['max_drawdown'])
print('  -> 0-100 scores (8.62, 13.7) and 0-1 fractions (0.0982, -0.0213) share one flat block, no unit keys')
