import json, unicodedata
from collections import Counter
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
raw = open(P, encoding='utf-8').read()
d = json.loads(raw)
S = d['sections']

print("=== U+FFFD REPLACEMENT CHARACTER sweep (encoding corruption in published strings) ===")
print("  raw file contains U+FFFD:", '\ufffd' in raw, " count:", raw.count('\ufffd'))
for k, s in S.items():
    for i, w in enumerate(s.get('warnings') or [], 1):
        if '\ufffd' in w:
            j = w.index('\ufffd')
            print("  sections.%s.warnings[%d]  char@%d  context=%r" % (k, i - 1, j, w[max(0, j-45):j+45]))
            print("      codepoint: %r  name: %s" % ('\ufffd', unicodedata.name('\ufffd', '?')))
# any other non-ascii
na = Counter(ch for ch in raw if ord(ch) > 127)
print("  non-ascii characters present:", {repr(k): v for k, v in na.items()})

print()
print("=== dashboard W7 vs realized_risk W1 : identical? ===")
a = S['dashboard']['warnings'][6]
b = S['realized_risk']['warnings'][0]
print("  identical:", a == b, " lens:", len(a), len(b))
if a != b:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print("   first divergence @%d: dashboard=%r realized=%r" % (i, a[max(0,i-30):i+30], b[max(0,i-30):i+30]))
            break
a8 = S['dashboard']['warnings'][7]
b1 = S['liquidity']['warnings'][0]
print("  dashboard W8 == liquidity W1 ?", a8 == b1)

print()
print("=== dashboard warning redundancy map ===")
allsections = {}
for k, s in S.items():
    for w in (s.get('warnings') or []):
        allsections.setdefault(w, []).append(k)
for i, w in enumerate(S['dashboard']['warnings'], 1):
    where = allsections.get(w, ['<dashboard-only>'])
    print("  W%d  appears in: %-40s | %s" % (i, ','.join(where), w[:95]))

print()
print("=== per-section duplicate warning text (dedup check) ===")
for k, s in S.items():
    ws = s.get('warnings') or []
    dup = [w for w, n in Counter(ws).items() if n > 1]
    if dup:
        print("  %-20s %d duplicated warning(s):" % (k, len(dup)))
        for w in dup: print("     x%d %s" % (Counter(ws)[w], w[:110]))

print()
print("=== sections where a canonical section's warning text was NOT deduped because it was restated ===")
print("  (dashboard inherits cached canonical results; identical text collected at 2 nesting levels)")
