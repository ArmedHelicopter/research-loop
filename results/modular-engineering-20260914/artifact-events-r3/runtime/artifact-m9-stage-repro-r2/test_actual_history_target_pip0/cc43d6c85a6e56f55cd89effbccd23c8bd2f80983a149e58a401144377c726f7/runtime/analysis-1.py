import csv,json
with open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'statistic':sum(xs)/len(xs)}))