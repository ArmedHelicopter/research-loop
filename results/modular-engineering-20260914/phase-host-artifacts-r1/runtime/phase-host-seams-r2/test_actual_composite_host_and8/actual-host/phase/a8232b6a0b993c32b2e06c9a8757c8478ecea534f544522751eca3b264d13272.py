import csv,json,time
time.sleep(0.3)
with open('/input/public_csv',newline='') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'mean':sum(xs)/len(xs)}))