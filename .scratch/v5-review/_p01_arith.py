import json, math
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
ps = d['sections']['portfolio']['data']['positions']
tv = d['sections']['portfolio']['data']['total_value']

print("=== PER-POSITION ARITHMETIC ===")
hdr = f"{'ticker':<15}{'mktval':>16}{'q*p':>16}{'d_mv':>12}{'cost':>16}{'q*bp':>16}{'d_cost':>10}{'pnl':>16}{'d_pnl':>12}{'pnl%':>12}{'d_pct':>12}"
print(hdr)
maxdrift = {}
for r in ps:
    q, bp, lp = r['quantity'], r['buy_price'], r['last_price']
    mv, cost, pnl, pnlpct = r['market_value'], r['total_cost'], r['unrealized_gain_loss'], r['unrealized_gain_loss_pct']
    qp = q*lp; qbp = q*bp
    d_mv = mv - qp
    d_cost = cost - qbp
    d_pnl = pnl - (mv - cost)
    d_pct = pnlpct - ((mv-cost)/cost*100 if cost else float('nan'))
    d_pct2 = pnlpct - ((lp-bp)/bp*100)
    print(f"{r['ticker']:<15}{mv:>16.6f}{qp:>16.6f}{d_mv:>12.2e}{cost:>16.6f}{qbp:>16.6f}{d_cost:>10.2e}{pnl:>16.6f}{d_pnl:>12.2e}{pnlpct:>12.6f}{d_pct:>12.2e}")
    maxdrift[r['ticker']] = dict(d_mv=d_mv, d_cost=d_cost, d_pnl=d_pnl, d_pct=d_pct, d_pct2=d_pct2)

print()
print("=== pct definition check: (pct*cost) vs (q*(lp-bp)) ===")
for r in ps:
    cost=r['total_cost']; pct=r['unrealized_gain_loss_pct']
    print(f"{r['ticker']:<15} pct*cost={pct*cost:>16.6f}  q*(lp-bp)={r['quantity']*(r['last_price']-r['buy_price']):>16.6f}  ulgl={r['unrealized_gain_loss']:>16.6f}")

print()
print("=== WEIGHTS ===")
sw = sum(r['weight'] for r in ps)
smv = sum(r['market_value'] for r in ps)
print(f"sum weight = {sw!r}")
print(f"sum market_value = {smv!r}")
print(f"published total_value = {tv!r}")
print(f"total_value - sum(mv) = {tv - smv!r}")
print(f"total_weight field = {d['sections']['portfolio']['data']['total_weight']!r}")
print()
for r in ps:
    implied = r['market_value']/smv
    implied_tv = r['market_value']/tv
    print(f"{r['ticker']:<15} w={r['weight']!r}  mv/sum(mv)={implied!r} d={r['weight']-implied:+.3e}   mv/tv={implied_tv!r} d={r['weight']-implied_tv:+.3e}")
