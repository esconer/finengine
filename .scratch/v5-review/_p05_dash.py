import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
db = d['sections']['dashboard']
print("DASHBOARD DATA KEYS:", list(db['data'].keys()))
for k,v in db['data'].items():
    s = json.dumps(v)
    print(f"  {k}: len={len(s)}")
print()
print("component_as_of:")
print(json.dumps(db['data'].get('component_as_of'), indent=1))
print()
print("performance / history block:")
for k in db['data']:
    if 'perf' in k or 'hist' in k or 'component' in k:
        print(f"== {k} ==")
        print(json.dumps(db['data'][k], indent=1)[:3500])
