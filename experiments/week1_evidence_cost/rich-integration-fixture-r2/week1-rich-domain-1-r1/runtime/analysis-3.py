import json,pandas as pd
d=pd.read_csv('/input/data')
f={'key': 'fraction', 'label': 'observed SES proportion', 'value': 0, 'unit': 'proportion', 'population': 'all CSV rows; fixture only', 'method': 'direct recomputation from CSV; fixture only', 'premise_claim_ids': ['4e021e1096729ca605bfb1e6ea7b3c30c4544308c1f258ede84652dcc559954a']}
f['value']=int(d['SES'].notna().sum()) / len(d)
print(json.dumps({'facts':[f],'limitations':['Integration fixture, not scientific evidence']},allow_nan=False))