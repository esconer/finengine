"""Mutation-test the repo's own guardrails against the v5 export.

For each mutation we assert whether the 47-rule audit SHOULD fire.  A mutation
that is objectively wrong but leaves the audit green is a guardrail gap.
"""
import json, subprocess, sys, copy
from pathlib import Path

SRC = Path(r'C:\es\others things\finengine-portfolio-ai-context v5.json')
TMP = Path(r'C:\Users\Sayanti\AppData\Local\Temp\opencode\di_mut')
TMP.mkdir(parents=True, exist_ok=True)
base = json.loads(SRC.read_text(encoding='utf-8'))

MUTATIONS = {}

# M1: portfolio as_of pushed 5 months into the future (fabricated time travel)
m = copy.deepcopy(base)
m['sections']['portfolio']['as_of'] = '2027-03-01T00:00:00Z'
m['sections']['portfolio']['data']['as_of'] = '2027-03-01T00:00:00Z'
MUTATIONS['M1 portfolio as_of = 2027-03-01 (5 months FUTURE)'] = m

# M2: portfolio as_of = 5 years past (ancient, obviously wrong)
m = copy.deepcopy(base)
m['sections']['portfolio']['as_of'] = '2015-01-01T00:00:00Z'
m['sections']['portfolio']['data']['as_of'] = '2015-01-01T00:00:00Z'
MUTATIONS['M2 portfolio as_of = 2015-01-01 (10 years STALE)'] = m

# M3: pairs as_of NEWER than 81 of its own 91 pair rows (overlap_end 2026-09-22..25)
m = copy.deepcopy(base)
m['sections']['pairs']['as_of'] = '2026-10-15'
MUTATIONS['M3 pairs as_of = 2026-10-15 (newer than all 91 overlap_end)'] = m

# M4: volatility_sizing as_of 3 days newer than its own sizing price
m = copy.deepcopy(base)
m['sections']['volatility_sizing']['as_of'] = '2026-10-05'
MUTATIONS['M4 volatility_sizing as_of = 2026-10-05 (sizing price is 2026-09-22)'] = m

# M5: break per-position arithmetic: MOTHERSON market_value inflated 10%
m = copy.deepcopy(base)
for p in m['sections']['portfolio']['data']['positions']:
    if p['ticker'] == 'MOTHERSON.NS':
        p['market_value'] *= 1.10
        p['current_value'] = p['market_value']
MUTATIONS['M5 MOTHERSON market_value +10% (weight/cost/pnl left alone)'] = m

# M6: break total_value only
m = copy.deepcopy(base)
m['sections']['portfolio']['data']['total_value'] = 99999.0
MUTATIONS['M6 portfolio total_value = 99999 (rows untouched)'] = m

# M7: break a weight
m = copy.deepcopy(base)
m['sections']['portfolio']['data']['positions'][0]['weight'] = 0.5
MUTATIONS['M7 CIPLA weight forced to 0.5'] = m

# M8: SELECTIPO market cap back to a fabricated measured 1e12 (hide the floor)
m = copy.deepcopy(base)
leg = m['sections']['liquidity']['data']['by_position']['SELECTIPO.NS']
leg['market_cap'] = 1e12
leg['market_cap_provenance'] = 'measured'
leg['market_cap_source'] = 'quote'
leg['is_estimate'] = False
MUTATIONS['M8 SELECTIPO floor market cap relabelled measured/quote'] = m

# M9: concentration gets data, no as_of, no warning -- already true; strip the
#     HHI so it is a fabricated value with no date to check it against
m = copy.deepcopy(base)
m['sections']['concentration']['data']['herfindahl_index'] = 0.9999
MUTATIONS['M9 concentration HHI overwritten to 0.9999 (no as_of, no warning)'] = m

# M10: dashboard summary portfolio_value silently diverges from portfolio total
m = copy.deepcopy(base)
m['sections']['dashboard']['data']['components']['summary']['data']['portfolio_value'] = 50000.0
MUTATIONS['M10 dashboard summary.portfolio_value = 50000 (portfolio says 43608.67)'] = m

def run(name, payload):
    p = TMP / (name.split()[0] + '.json')
    p.write_text(json.dumps(payload), encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'app.debugging.context_audit', 'check',
                        '--export', str(p), '--json'],
                       capture_output=True, text=True, cwd=r'C:\es\coding\finengine\backend')
    try:
        out = json.loads(r.stdout)
    except Exception:
        return None, (r.stdout or '')[-400:] + (r.stderr or '')[-400:]
    return out, None

print("=" * 100)
print("MUTATION GUARDRAIL TEST  (green = the 47-rule audit did NOT catch an objectively wrong export)")
print("=" * 100)
for name, payload in MUTATIONS.items():
    out, err = run(name, payload)
    if out is None:
        print("\n%-62s  ERROR %s" % (name, err))
        continue
    f = out.get('findings') or []
    rules = out.get('errors') or []
    ids = sorted({x.get('rule_id') or x.get('rule') for x in f})
    verdict = 'CAUGHT by %s' % ids if f else '*** NOT CAUGHT (green) ***'
    print("\n%-62s  %s" % (name, verdict))
    for x in f[:4]:
        print("      %s %s :: %s" % (x.get('rule_id'), x.get('section'), str(x.get('message'))[:150]))
