import csv
with open('/input/data') as f: print(sum(int(r['x']) for r in csv.DictReader(f)))
