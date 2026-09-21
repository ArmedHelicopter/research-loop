import json,pandas as pd
d=pd.read_csv('/input/data')
f={'key': 'count', 'label': 'rows with observed SES', 'value': 0, 'unit': 'rows', 'population': 'all CSV rows; fixture only', 'method': 'direct recomputation from CSV; fixture only', 'premise_claim_ids': []}
f['value']=int(d['SES'].notna().sum())
print(json.dumps({'facts':[f],'limitations':['Integration fixture, not scientific evidence']},allow_nan=False))