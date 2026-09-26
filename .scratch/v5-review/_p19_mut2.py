import json, subprocess, sys, copy
from pathlib import Path
TMP = Path(r'C:\Users\Sayanti\AppData\Local\Temp\opencode\di_mut2'); TMP.mkdir(parents=True, exist_ok=True)
base = json.loads(Path(r'C:\es\others things\finengine-portfolio-ai-context v5.json').read_text(encoding='utf-8'))

def run(name, payload):
    p = TMP / (name.split()[0] + '.json')
    p.write_text(json.dumps(payload), encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'app.debugging.context_audit', 'check', '--export', str(p), '--json'],
                       capture_output=True, text=True, cwd=r'C:\es\coding\finengine\backend')
    try: out = json.loads(r.stdout)
    except Exception: return None, (r.stdout or '')[-300:] + (r.stderr or '')[-300:]
    return out, None

def test(name, mut):
    m = copy.deepcopy(base); mut(m)
    out, err = run(name, m)
    if out is None: print('%-58s ERROR %s' % (name, err)); return
    f = out.get('findings') or []
    print('%-58s %s' % (name, ('CAUGHT by %s' % sorted({x.get("rule_id") for x in f})) if f else '*** NOT CAUGHT (green) ***'))
    for x in f[:3]: print('     %s %s :: %s' % (x.get('rule_id'), x.get('section'), str(x.get('message'))[:140]))

# W1: per-row weight wrong but weights still sum to 1 (shift 5pp CIPLA -> NTPC)
def w1(m):
    ps = m['sections']['portfolio']['data']['positions']
    d = {p['ticker']: p for p in ps}
    d['CIPLA.NS']['weight'] += 0.05
    d['NTPC.NS']['weight'] -= 0.05
    for p in ps:  # keep total_weight == 1
        pass
test('W1 CIPLA weight +5pp, NTPC -5pp (sum still 1)', w1)

# W2: total_cost broken on one row (cost no longer q*buy_price)
def w2(m):
    for p in m['sections']['portfolio']['data']['positions']:
        if p['ticker'] == 'ELECTCAST.NS':
            p['total_cost'] = 999.0
            p['total_cost_base'] = 999.0
test('W2 ELECTCAST total_cost -> 999 (q*buy_price = 2083.60)', w2)

# W3: unrealized_gain_loss broken on one row
def w3(m):
    for p in m['sections']['portfolio']['data']['positions']:
        if p['ticker'] == 'MOTHERSON.NS':
            p['unrealized_gain_loss'] = 0.0
            p['unrealized_gain_loss_base'] = 0.0
test('W3 MOTHERSON unrealized_gain_loss -> 0 (true = 2812.68)', w3)

# W4: unrealized_gain_loss_pct broken on one row
def w4(m):
    for p in m['sections']['portfolio']['data']['positions']:
        if p['ticker'] == 'JKIL.NS':
            p['unrealized_gain_loss_pct'] = 99.0
            p['unrealized_gain_loss_pct_base'] = 99.0
test('W4 JKIL unrealized_gain_loss_pct -> 99.0 (true = -30.445)', w4)

# W5: base != native on one row (silent FX mislabel)
def w5(m):
    for p in m['sections']['portfolio']['data']['positions']:
        if p['ticker'] == 'CIPLA.NS':
            p['market_value_base'] = p['market_value'] * 83.0   # as if an FX rate was applied
            p['value_currency'] = 'USD'
test('W5 CIPLA market_value_base *= 83 but native left alone', w5)

# W6: sectors no longer sum to 1 (portfolio-level)
def w6(m):
    s = m['sections']['portfolio']['data']['sectors']
    s['Healthcare'] = 0.5
test('W6 portfolio.sectors.Healthcare -> 0.5', w6)

# W7: two positions given the same ticker (duplicate)
def w7(m):
    ps = m['sections']['portfolio']['data']['positions']
    ps[1]['ticker'] = ps[0]['ticker']
test('W7 ELECTCAST ticker -> CIPLA.NS (duplicate position)', w7)

# W8: portfolio omits a holding entirely (13 rows) with coverage still claiming 14
def w8(m):
    m['sections']['portfolio']['data']['positions'].pop()
    m['sections']['portfolio']['data']['total_positions'] = 14
test('W8 drop a position row, keep total_positions=14 and coverage 14/14', w8)

# W9: all fx_rate forced to 1 while native_currency claims USD
def w9(m):
    for p in m['sections']['portfolio']['data']['positions']:
        p['native_currency'] = 'USD'
        p['fx_rate'] = 1
test('W9 all 14 native_currency -> USD with fx_rate 1 (unstated rate)', w9)
