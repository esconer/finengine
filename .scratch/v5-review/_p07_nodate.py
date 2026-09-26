import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
S = d['sections']

def peek(k, path='', depth=0, maxd=3):
    o = S[k]['data']
    def rec(o, path, depth):
        if depth > maxd: return
        if isinstance(o, dict):
            for kk, vv in o.items():
                if isinstance(vv,(dict,list)):
                    n = len(vv)
                    rec(vv, f'{path}.{kk}', depth+1)
                else:
                    print(f'  {path}.{kk} = {json.dumps(vv)[:120]}')
        elif isinstance(o, list):
            print(f'  {path}[] n={len(o)}')
            if o: rec(o[0], path+'[0]', depth+1)
    print('#'*30, k, 'as_of=',S[k]['as_of'])
    rec(o,'',0)

for k in ('concentration','stress_testing','liquidity'):
    peek(k, maxd=2)
    print()

print('#'*30,'liquidity by_position (SELECTIPO/ETF band check)')
liq = S['liquidity']['data']
bp = liq.get('by_position') or liq
if isinstance(bp, list):
    for r in bp:
        if isinstance(r,dict) and r.get('ticker') in ('SELECTIPO.NS','JUNIORBEES.NS','NIFTYIETF.NS','MAFANG.NS','MIDCAPIETF.NS','CIPLA.NS','MOTHERSON.NS'):
            print(json.dumps(r, indent=1))
print()
print('liquidity top-level non-by_position keys:')
for kk,vv in liq.items():
    if kk!='by_position':
        print(' ',kk,'=',json.dumps(vv)[:400])
