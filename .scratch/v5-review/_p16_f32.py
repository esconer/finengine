import json, struct
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']
ps = S['portfolio']['data']['positions']

print("=== float32 provenance of last_price (yfinance/pandas float32 channel) ===")
def f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]
n32 = 0
for r in sorted(ps, key=lambda r: r['ticker']):
    lp = r['last_price']
    is32 = (f32(lp) == lp)
    n32 += is32
    # nearest 0.05 tick
    tick = round(round(lp / 0.05) * 0.05, 2)
    print("  %-16s last_price=%-22r == float32? %-5s  nearest 0.05 tick=%-10r err=%+.3e" % (r['ticker'], lp, is32, tick, lp-tick))
print("  legs whose last_price is a float32 round-trip: %d / 14" % n32)
print()
print("  consequence on totals:")
print("   total_value        = %r" % S['portfolio']['data']['total_value'])
tv_tick = sum(round(round(f32(r['last_price'])/0.05)*0.05, 2) * r['quantity'] for r in ps)
print("   tick-rounded total = %r   (delta %+.6f)" % (tv_tick, S['portfolio']['data']['total_value'] - tv_tick))
print("   dashboard summary.portfolio_value = 43608.67  <-- the 2dp figure, in the SAME export")
print("   |43608.67 - 43608.66981063843| = %.6f" % abs(43608.67 - S['portfolio']['data']['total_value']))

print()
print("=== optimization: monetary fields with currency=null ===")
opt = S['optimization']['data']
print("  keys:", list(opt.keys()))
for k in ('current_value','target_value','initial_value','expected_return','portfolio_value','total_value','expected_shortfall','value_at_risk','cvar'):
    if k in opt: print("   %-20s %s" % (k, json.dumps(opt[k])[:120]))
print("  optimization status=%s as_of=%s currency=%s" % (S['optimization']['status'], S['optimization']['as_of'], S['optimization']['currency']))

print()
print("=== export bracket sanity ===")
from datetime import datetime
g = datetime.fromisoformat(d['generated_at'].replace('Z','+00:00'))
c = datetime.fromisoformat(d['completed_at'].replace('Z','+00:00'))
print("  generated_at=%s completed_at=%s  bracket=%.3f s  sane=%s" % (d['generated_at'], d['completed_at'], (c-g).total_seconds(), (c-g).total_seconds() > 0))
print("  export_id=%s  (uuid4 hex[:12] -> not reproducible, not a content hash)" % d['export_id'])
print("  scope == section keys, same order? ", d['scope'] == list(S.keys()))

print()
print("=== status vs warnings matrix ===")
print("%-20s %-11s %-8s %-9s %-9s %s" % ('section','status','#warn','coverage','data_st','verdict'))
for k, s in S.items():
    w = len(s.get('warnings') or [])
    cov = (s.get('coverage') or {}).get('status')
    ds = (s['data'] or {}).get('data_status') if isinstance(s.get('data'), dict) else None
    verdict = []
    if s['status'] == 'available' and w: verdict.append('AVAILABLE+WARN')
    if s['status'] == 'unavailable' and s['data'] not in (None, {}, []): verdict.append('UNAVAIL+DATA')
    if s['status'] == 'partial' and w == 0: verdict.append('PARTIAL+SILENT')
    if s['status'] == 'available' and s['as_of'] is None: verdict.append('AVAILABLE+NO_ASOF')
    if s['as_of'] is None and s['data'] not in (None,{},[]): verdict.append('DATA+NO_ASOF')
    if ds and ds != s['status']: verdict.append('data_status=%s!=section' % ds)
    print("%-20s %-11s %-8d %-9s %-9s %s" % (k, s['status'], w, cov, ds, ', '.join(verdict) or 'ok'))

print()
print("=== payload-level data_status disagreement with section status ===")
for k, s in S.items():
    ds = (s['data'] or {}).get('data_status') if isinstance(s.get('data'), dict) else None
    if ds and ds != s['status']:
        print("  %-20s section.status=%-10s payload.data_status=%-10s  data_status_meaning? " % (k, s['status'], ds))
        nw = (s['data'] or {}).get('warnings')
        if nw: print("      payload warnings present: %d" % len(nw))
