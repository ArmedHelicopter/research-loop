import csv,json
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
observations=[1]
proposed=[1.0, 1.0, 1.0]
weight=0
phase=[{'mean': 1.3333333333333333}, {'range': 3.0}]
print(json.dumps({'mean':sum(xs)/len(xs),'phase':phase,'observations':observations,'proposed':proposed,'adjusted':10*sum(observations)/len(observations)+sum(proposed)+weight-sum(next(iter(v.values())) for v in phase)},sort_keys=True))