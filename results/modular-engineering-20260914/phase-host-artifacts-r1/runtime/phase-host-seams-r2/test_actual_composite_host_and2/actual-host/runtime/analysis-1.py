import csv,json
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
useful=['increase', 'decrease', 'unchanged']
weight=0
phase=[{'mean': 1.3333333333333333}, {'range': 3.0}]
print(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'useful':useful,'adjusted':weight-sum(next(iter(v.values())) for v in phase)},sort_keys=True))