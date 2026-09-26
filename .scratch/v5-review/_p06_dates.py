import json, re
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
DATE = re.compile(r'20\d\d-\d\d-\d\d')

def harvest(obj, path=''):
    out = {}
    if isinstance(obj, dict):
        for k,v in obj.items():
            out.update(harvest(v, f'{path}.{k}'))
    elif isinstance(obj, list):
        for i,v in enumerate(obj[:400]):
            out.update(harvest(v, f'{path}[{i}]'))
    else:
        if isinstance(obj,str) and DATE.fullmatch(obj.strip()[:10]) and len(obj.strip())==10:
            out.setdefault(path.rsplit('.',1)[-1] if '[' not in path.split('.')[-1] else path, set()).add(obj)
    return out

for k,s in d['sections'].items():
    h = harvest(s.get('data'))
    print(f"--- {k}: as_of={s.get('as_of')} semantics={s.get('as_of_semantics')}")
    if not h:
        print("    (no bare YYYY-MM-DD leaves in data)")
    for kk, vv in sorted(h.items()):
        vals = sorted(vv)
        print(f"    {kk:<42} n={len(vals):<3} min={vals[0]} max={vals[-1]}")
    # also count date-prefixed strings
    txt = json.dumps(s.get('data'))
    alld = sorted(set(DATE.findall(txt)))
    print(f"    all date-strings seen: {alld}")
