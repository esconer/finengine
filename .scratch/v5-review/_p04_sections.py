import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
G = d['generated_at']
print(f"export generated_at = {G}\n")
print(f"{'section':<20}{'status':<12}{'as_of':<32}{'as_of>gen':<9}{'semantics':<46}{'ccy':<6}{'omitted':<9}{'warn':<6}{'data?':<6}")
print("-"*160)
for k, s in d['sections'].items():
    ao = s.get('as_of')
    fut = ''
    if ao:
        fut = 'FUTURE!' if ao > G else 'ok'
    dat = 'yes' if s.get('data') not in (None, {}, []) else 'EMPTY'
    om = s.get('omitted_fields')
    omn = len(om) if om is not None else 'None'
    print(f"{k:<20}{str(s.get('status')):<12}{str(ao):<32}{fut:<9}{str(s.get('as_of_semantics'))[:44]:<46}{str(s.get('currency')):<6}{str(omn):<9}{len(s.get('warnings') or []):<6}{dat:<6}")

print()
print("=== SECTION ORDER / generated_at per section ===")
for k, s in d['sections'].items():
    print(f"  {k:<20} gen={s.get('generated_at')}  ao={s.get('as_of')}")

print()
print("=== TOP-LEVEL warnings count:", len(d.get('warnings') or []), "===")
tot = sum(len(s.get('warnings') or []) for s in d['sections'].values())
print("=== SUM of section warnings:", tot, "===")
print()
print("=== coverage presence ===")
for k, s in d['sections'].items():
    cov = s.get('coverage')
    if cov is None:
        print(f"  {k:<20} coverage=None")
    else:
        keys = [x for x in ('requested_count','available_count','coverage_ratio','complete','status','missing_tickers','requested_tickers','available_tickers') if x in cov]
        print(f"  {k:<20} {({x: (cov[x] if x not in ('missing_tickers','requested_tickers','available_tickers') else (len(cov[x]) if isinstance(cov[x],list) else cov[x])) for x in keys})}")
