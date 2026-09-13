import csv
import glob
import math
import os


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

files = glob.glob('/input/*.csv')
if not files:
    print('No CSV files found in /input.')
    raise SystemExit

path = next((p for p in files if 'fish' in os.path.basename(p).lower()), files[0])
with open(path, newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

required = {'fish_caught', 'livebait', 'camper', 'persons', 'child', 'hours'}
missing = required - set(rows[0]) if rows else required
if missing:
    print('Missing columns: ' + ', '.join(sorted(missing)))
    raise SystemExit

data = []
for r in rows:
    vals = {k: to_float(r.get(k)) for k in required}
    if vals['fish_caught'] is not None and vals['hours'] and vals['hours'] > 0:
        vals['rate'] = vals['fish_caught'] / vals['hours']
        data.append(vals)

if not data:
    print('No usable rows with positive hours.')
    raise SystemExit

mean_rate = sum(d['rate'] for d in data) / len(data)
mean_fish = sum(d['fish_caught'] for d in data) / len(data)
mean_hours = sum(d['hours'] for d in data) / len(data)
print(f'Rows analyzed: {len(data)}')
print(f'Mean fish caught per trip: {mean_fish:.3f}')
print(f'Mean fishing hours per trip: {mean_hours:.3f}')
print(f'Mean fish caught per hour: {mean_rate:.3f}')

for label, value in [('livebait=0', 0), ('livebait=1', 1)]:
    g = [d['rate'] for d in data if d['livebait'] == value]
    if g:
        print(f'{label} n={len(g)}, mean fish/hour={sum(g)/len(g):.3f}')

# Descriptive adjusted OLS using normal equations for rate ~ intercept + livebait + camper + persons + child.
features = ['livebait', 'camper', 'persons', 'child']
usable = [d for d in data if all(d[k] is not None for k in features)]
if len(usable) >= len(features) + 2:
    X = [[1.0] + [d[k] for k in features] for d in usable]
    y = [d['rate'] for d in usable]
    p = len(X[0])
    A = [[sum(row[i] * row[j] for row in X) for j in range(p)] for i in range(p)]
    b = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(p)]
    for i in range(p):
        pivot = max(range(i, p), key=lambda k: abs(A[k][i]))
        if abs(A[pivot][i]) < 1e-10:
            break
        A[i], A[pivot] = A[pivot], A[i]
        b[i], b[pivot] = b[pivot], b[i]
        q = A[i][i]
        A[i] = [v / q for v in A[i]]
        b[i] /= q
        for k in range(p):
            if k != i:
                q = A[k][i]
                A[k] = [A[k][j] - q * A[i][j] for j in range(p)]
                b[k] -= q * b[i]
    else:
        print(f'Adjusted descriptive livebait coefficient: {b[1]:.3f} fish/hour')
        print('The adjusted association is observational and not a causal estimate.')