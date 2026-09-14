import csv,json
with open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'mean':sum(xs)/len(xs),'state':1.0,'candidate':2.0,'adjusted':sum(xs)/len(xs)+3.0}))