import csv,json,statistics,time
start=time.time_ns()
time.sleep(0.3)
with open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]
print(json.dumps({'statistic':max(xs)-min(xs),'start_ns':start,'end_ns':time.time_ns()}))