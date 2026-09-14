import csv,time
time.sleep(0.15)
with open('/input/public_csv',newline='') as f:
 rows=list(csv.DictReader(f))
print(sum(float(r['x']) for r in rows)+2)