import json, re
t = open(r'C:\es\others things\finengine-portfolio-ai-context v5.json', encoding='utf-8').read()
for k in ('day_change', 'previous_close', 'prev_close', 'total_cost', 'total_pnl', 'total_unrealized',
          'is_estimate', 'price_source', 'stale', 'total_value'):
    print('%-20s occurrences = %d' % (repr(k), t.count('"%s"' % k)))
print()
print('keys named day* :', sorted(set(re.findall(r'"(day[a-z_]*)"', t))))
print('keys named *change*:', sorted(set(re.findall(r'"([a-z_]*change[a-z_]*)"', t))))
print('keys named *stale*:', sorted(set(re.findall(r'"([a-z_]*stale[a-z_]*)"', t))))
print('keys named is_*:', sorted(set(re.findall(r'"(is_[a-z_]*)"', t))))
print('keys named *provenance*:', sorted(set(re.findall(r'"([a-z_]*provenance[a-z_]*)"', t))))
print('keys named *cost*:', sorted(set(re.findall(r'"([a-z_]*cost[a-z_]*)"', t))))
print('keys named total_*:', sorted(set(re.findall(r'"(total_[a-z_]*)"', t))))
print('keys named *pnl*:', sorted(set(re.findall(r'"([a-z_]*pnl[a-z_]*)"', t))))
