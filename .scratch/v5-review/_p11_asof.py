import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']
G = d['generated_at']

print("=== RULE 6a: as_of > export generated_at ===")
for k, s in S.items():
    ao = s.get('as_of')
    if ao and ao > G:
        print("  VIOLATION %-14s as_of=%s  > generated_at=%s  (+%.3f ms)" % (k, ao, G, 0))
print("  (delta = %.1f ms)" % 0)
from datetime import datetime
def iso(x): return datetime.fromisoformat(x.replace('Z','+00:00'))
a = iso(S['portfolio']['as_of']); g = iso(G)
print("  portfolio as_of - export generated_at = %+.1f ms" % ((a-g).total_seconds()*1000))
print("  portfolio as_of - portfolio section generated_at = %+.1f ms" % ((a-iso(S['portfolio']['generated_at'])).total_seconds()*1000))
print("  as_of inside [generated_at, completed_at]? ", G <= S['portfolio']['as_of'] <= d['completed_at'])

print()
print("=== RULE 6b: section as_of vs min/max of its OWN dated inputs ===")
ps = S['portfolio']['data']['positions']
ups = sorted(r['updated_on'] for r in ps)
print("portfolio  as_of=%s" % S['portfolio']['as_of'])
print("  own inputs updated_on: min=%s  max=%s  (n=%d)" % (ups[0], ups[-1], len(ups)))
print("  as_of == max(updated_on)? %s   as_of == min(updated_on)? %s" % (S['portfolio']['as_of'].startswith(ups[-1]), S['portfolio']['as_of'].startswith(ups[0])))
print("  NEWER than %d of its own 14 price inputs" % sum(1 for u in ups if u < S['portfolio']['as_of'][:26]))

print()
print("pairs: as_of=%s  but own payload overlap_end=%s observation_date_a=%s" % (
    S['pairs']['as_of'], S['pairs']['data']['overlap_end'], S['pairs']['data']['observation_date_a']))
print("volatility_sizing: as_of=%s  but own payload sizing_price_as_of=%s" % (
    S['volatility_sizing']['as_of'], S['volatility_sizing']['data']['sizing_price_as_of']))
print("optimization: as_of=%s  own latest_observation=%s" % (S['optimization']['as_of'], S['optimization']['data']['latest_observation']))
print("india_flows: as_of=%s  component_as_of=%s" % (S['india_flows']['as_of'], json.dumps(S['india_flows']['data'].get('component_as_of'))))
print("  india_flows as_of_note =", S['india_flows']['data'].get('as_of_note'))
print("  canonical liquidity section as_of =", S['liquidity']['as_of'], " (india_flows claims its as_of came from the liquidity component)")
print("  liquidity data window: start=%s end=%s" % (S['liquidity']['data'].get('start'), S['liquidity']['data'].get('end')))
print("  liquidity_limits component as_of =", (S['india_flows']['data']['components']['liquidity_limits'].get('data') or {}).get('as_of'))

print()
print("=== RULE 6c: sections with data but as_of=None ===")
for k in ('concentration','liquidity','stress_testing'):
    s = S[k]
    has = s['data'] not in (None, {}, [])
    nnum = json.dumps(s['data']).count(':')
    print("  %-14s status=%-9s data_present=%s as_of=%s semantics=%s warnings=%d" % (
        k, s['status'], has, s['as_of'], s['as_of_semantics'], len(s.get('warnings') or [])))

print()
print("=== RULE 6d: dashboard composite min-rule verification ===")
ca = S['dashboard']['data']['component_as_of']
vals = {k: v['as_of'] for k, v in ca.items() if v['as_of']}
print("  component as_ofs:", json.dumps(vals, indent=None))
print("  min = %s ; published dashboard as_of = %s ; MATCH=%s" % (min(vals.values()), S['dashboard']['as_of'], min(vals.values()) == S['dashboard']['as_of']))

print()
print("=== RULE 9: snapshot spread across the 17 sections ===")
dates = sorted({(s['as_of'] or 'None')[:10] for s in S.values()})
print("  distinct as_of dates:", dates)
for k, s in S.items():
    print("   %-20s %s" % (k, (s['as_of'] or 'None')[:19]))
