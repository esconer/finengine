import json, re
from collections import Counter
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

print("=== RULE 4: currency labelling per section ===")
print("%-20s %-8s %-14s %-40s" % ('section','currency','data has money?','declared units inside data'))
MONEY = ('value','cost','pnl','notional','turnover','cap','exposure','return','alpha','beta','currency','₹')
for k, s in S.items():
    dat = s['data']
    txt = json.dumps(dat)
    has = any(m in txt.lower() for m in ('_value','total_cost','notional','turnover','market_cap','_exposure','currency'))
    units = sorted({m for m in ('monetary_unit','currency','base_currency','value_currency','returns_currency','currency_basis','portfolio_value_currency','turnover_unit','volume_unit') if ('"%s"' % m) in txt})
    print("%-20s %-8s %-14s %s" % (k, str(s['currency']), has, ','.join(units)))

print()
print("=== sections with currency=None that publish monetary magnitudes ===")
for k, s in S.items():
    if s['currency'] is None:
        print("  %-20s status=%-9s" % (k, s['status']))

print()
print("=== RULE 10: duplicate / fabrication sweep ===")
ps = S['portfolio']['data']['positions']
print("  portfolio tickers:", len(ps), "unique:", len({r['ticker'] for r in ps}), " ids:", sorted(r['id'] for r in ps), "ids unique:", len({r['id'] for r in ps}) == len(ps))
print("  custom_name == ticker stem for all?", all(r['custom_name'] == r['ticker'].split('.')[0] for r in ps))
print("  all region 'IN'?", {r['region'] for r in ps})
print("  all .NS suffix?", {r['ticker'].split('.')[-1] for r in ps})
# cross-section roster
def roster(s):
    c = s.get('coverage') or {}
    return tuple(c.get('covered_tickers') or [])
base = roster(S['portfolio'])
print("  portfolio covered roster n=%d" % len(base))
for k, s in S.items():
    r = roster(s)
    if r != base:
        print("   ROSTER DIFF %-20s n=%d missing=%s extra=%s" % (k, len(r), set(base)-set(r), set(r)-set(base)))
print("  all 17 rosters identical to portfolio's? ", all(roster(s) == base for s in S.values()))
# sector/industry taxonomy
print("  distinct sectors:", sorted({r['sector'] for r in ps}))
print("  distinct industries:", sorted({r['industry'] for r in ps}))
print("  sector<->industry 1:1?", len({(r['sector'],r['industry']) for r in ps}) == len({r['sector'] for r in ps}))

print()
print("=== round-number sweep on prices (should not be suspiciously round) ===")
for r in sorted(ps, key=lambda r: r['ticker']):
    lp = r['last_price']
    s = repr(round(lp, 4))
    print("   %-16s last_price=%-22r buy_price=%-10r 2dp?=%s  is_int=%s" % (r['ticker'], lp, r['buy_price'], lp == round(lp,2), float(lp).is_integer()))

print()
print("=== does any section publish a per-ticker price series ending 2026-09-25? ===")
for k in ('realized_risk','tear_sheet','factor_exposure'):
    dat = S[k]['data']
    hits = re.findall(r'"(?:last_price|price|close|latest_price)"\s*:\s*([0-9.]+)', json.dumps(dat))
    print("  %-16s numeric price-like values found: %d  sample=%s" % (k, len(hits), hits[:5]))

print()
print("=== india_flows as_of_note (full) ===")
print(" ", S['india_flows']['data'].get('as_of_note'))
print("  india_flows component_as_of:", json.dumps(S['india_flows']['data'].get('component_as_of')))
print("  india_flows coverage_notes:", json.dumps(S['india_flows']['data'].get('coverage_notes'))[:400])
