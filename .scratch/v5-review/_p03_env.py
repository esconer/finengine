import json
P = r'C:\es\others things\finengine-portfolio-ai-context v5.json'
d = json.load(open(P, encoding='utf-8'))
for k in ('schema_version','export_id','generated_at','completed_at','snapshot_consistency','base_currency','currency_policy','detail','scope','environment','warnings'):
    print("==",k,"==")
    print(json.dumps(d.get(k),indent=1))
    print()
