import json
from datetime import date, datetime, timedelta
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

print("=== TODAY / generated_at day-of-week ===")
g = d['generated_at'][:10]
print("  export generated_at date = %s -> %s" % (g, date.fromisoformat(g).strftime('%A')))
print("  completed_at              = %s -> %s" % (d['completed_at'][:10], date.fromisoformat(d['completed_at'][:10]).strftime('%A')))
print("  portfolio as_of           = %s -> %s" % (S['portfolio']['as_of'][:10], date.fromisoformat(S['portfolio']['as_of'][:10]).strftime('%A')))

print()
print("=== per-position quote stamp: day-of-week + time ===")
seen = set()
for r in S['portfolio']['data']['positions']:
    u = r['updated_on']
    dd = u[:10]; hh = u[11:19]
    dow = date.fromisoformat(dd).strftime('%a')
    if (dd, hh) in seen: continue
    seen.add((dd, hh))
    print("   %s %s  %s" % (dd, hh, dow))

print()
print("=== NSE session sanity ===")
print("  2026-09-26 is a", date.fromisoformat('2026-09-26').strftime('%A'), "-> NSE/BSE equity market CLOSED")
print("  the only session in the delivered analytics window tail is", date.fromisoformat('2026-09-25').strftime('%A %Y-%m-%d'))
print("  realized_risk/forecast_risk/factor_exposure latest_observation_date = 2026-09-25 (Friday) <- consistent with Friday last close")
print("  portfolio as_of                                                 = 2026-09-26 (Saturday) 15:33:25Z")
print("  => as_of asserts a market-observation instant on a non-trading day;")
print("     the true last trade for every leg is the 2026-09-25 close.")

print()
print("=== added_on day-of-week (import stamps) ===")
for v in sorted({r['added_on'][:10] for r in S['portfolio']['data']['positions']}):
    print("   %s  %s" % (v, date.fromisoformat(v).strftime('%A')))

print()
print("=== spread of the 14 per-position quote stamps ===")
ups = sorted(r['updated_on'] for r in S['portfolio']['data']['positions'])
a = datetime.fromisoformat(ups[0]); b = datetime.fromisoformat(ups[-1])
print("   min=%s  max=%s  spread=%.3f s" % (ups[0], ups[-1], (b-a).total_seconds()))
print("   export generated_at=%s" % d['generated_at'])
print("   legs stamped BEFORE export generated_at: %d / 14" % sum(1 for u in ups if u < d['generated_at'][:26]))
print("   legs stamped AFTER  export generated_at: %d / 14" % sum(1 for u in ups if u > d['generated_at'][:26]))

print()
print("=== the export's own as_of warning, tested against the 14 legs ===")
w = S['portfolio']['warnings'][0]
print("   ", w)
print("   -> claims the value 'was refreshed during this export'. True for %d of 14 legs." % sum(1 for u in ups if u >= d['generated_at'][:26]))
