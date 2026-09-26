import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

def declared(k):
    return S[k].get('omitted_fields')

print("=== omitted_fields vs compaction rules (detail='summary') ===")
print("declared non-empty:", {k: declared(k) for k in S if declared(k)})

# dashboard performance_history
perf = S['dashboard']['data']['components']['performance_history']
n = len(perf.get('data') or [])
print("\ndashboard.performance_history rows = %d (trim threshold >90) -> trim? %s ; declared=%s" % (n, n > 90, declared('dashboard')))
hc = perf.get('history_coverage') or {}
print("  history_coverage.observation_count =", hc.get('observation_count'), " first_observation =", hc.get('first_observation'),
      " series_trimmed_in_summary =", hc.get('series_trimmed_in_summary'))

# tear_sheet
ts = S['tear_sheet']['data']
mr = ts.get('monthly_returns'); uw = ts.get('underwater')
print("\ntear_sheet.monthly_returns n=%s (threshold >24) declared=%s" % (len(mr) if isinstance(mr,dict) else mr, declared('tear_sheet')))
print("tear_sheet.underwater n=%s (threshold >90) declared=%s" % (len(uw) if isinstance(uw,list) else uw, declared('tear_sheet')))

# monte_carlo
mc = S['monte_carlo']['data']
print("\nmonte_carlo.fan n=%s (threshold >12) declared=%s" % (len(mc.get('fan') or []) if isinstance(mc.get('fan'),list) else mc.get('fan'), declared('monte_carlo')))
print("monte_carlo keys:", list(mc.keys()))

# pairs
pr = S['pairs']['data'].get('pairs') or []
lens = {}
for p_ in pr:
    if isinstance(p_, dict):
        ss = p_.get('spread_series')
        if isinstance(ss, list): lens[len(ss)] = lens.get(len(ss),0)+1
print("\npairs n=%d  spread_series length histogram=%s  declared=%s" % (len(pr), lens, declared('pairs')))
print("pairs keys:", list(S['pairs']['data'].keys()))

# risk_studio
rs = S['risk_studio']['data']
cs = (rs.get('components') or {}).get('correlation_stability') or {}
cdata = cs.get('data') or {}
ser = cdata.get('series')
print("\nrisk_studio.correlation_stability.data.series type=%s n=%s declared=%s" % (type(ser).__name__, len(ser) if hasattr(ser,'__len__') else ser, declared('risk_studio')))
for kk in ('series_trimmed_in_summary','series_observations','series_retained'):
    print("   %s = %s" % (kk, cdata.get(kk)))
print("   correlation_stability status:", cs.get('status'))

# india_flows
inf = S['india_flows']['data']
comp = inf.get('components') or {}
fl = (comp.get('institutional_flows') or {}).get('data')
print("\nindia_flows.institutional_flows.data type=%s keys=%s declared=%s" % (type(fl).__name__, list(fl.keys()) if isinstance(fl,dict) else fl, declared('india_flows')))
print("india_flows top keys:", list(inf.keys()))
print("india_flows component statuses:", {k: v.get('status') for k,v in comp.items()})

print("\n=== VERIFY the ONE declared omission actually exists in the payload ===")
path = 'components.correlation_stability.data.series'
node = rs
for seg in path.split('.'):
    node = node.get(seg) if isinstance(node, dict) else None
print("resolved path present in shipped data? ", node is not None, " len=", len(node) if hasattr(node,'__len__') else node)
print("-> omitted_fields claims OMITTED but the field is PRESENT (trimmed, not removed)")
