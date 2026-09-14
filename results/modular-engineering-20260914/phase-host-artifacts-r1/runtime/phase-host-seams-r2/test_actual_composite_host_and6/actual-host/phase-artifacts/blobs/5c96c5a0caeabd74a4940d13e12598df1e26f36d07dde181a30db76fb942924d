import csv,json,time
time.sleep(0.3)
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'variance':sum((x-sum(xs)/len(xs))**2 for x in xs)/len(xs)}))