import csv,json
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'range':max(xs)-min(xs)}))