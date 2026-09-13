import csv
with open('/input/public_csv', newline='') as f:
 rows=list(csv.DictReader(f))
print(sum(float(r['x']) for r in rows)/len(rows))
print('Which public mechanism explains x? State fa78afdef22e4ae1b1985be5e44b3d85410ae5ef68784338abc322396339dacc')