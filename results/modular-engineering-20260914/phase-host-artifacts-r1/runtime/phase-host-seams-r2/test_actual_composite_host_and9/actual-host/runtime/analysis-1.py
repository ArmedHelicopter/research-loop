import csv,json
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
observations=[8, 1, 99, 8, 8]
proposed=[24.8, 24.8, 24.8]
weight=3
phase=[{'mean': 1.3333333333333333}, {'variance': 1.5555555555555556}]
print(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'observations':observations,'proposed':proposed,'adjusted':10*sum(observations)/len(observations)+sum(proposed)+weight-sum(next(iter(v.values())) for v in phase)},sort_keys=True))