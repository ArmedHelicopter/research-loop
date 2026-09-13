import csv
import glob
import math
import os


def to_float(value):
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def main():
    paths = sorted(glob.glob('/input/*.csv'))
    if not paths:
        print('No CSV file found in /input.')
        return
    path = paths[0]
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    required = ['fish_caught', 'hours']
    if not rows or any(c not in rows[0] for c in required):
        print('Required columns fish_caught and hours are unavailable.')
        return

    valid = []
    for row in rows:
        fish, hours = to_float(row.get('fish_caught')), to_float(row.get('hours'))
        if fish is not None and hours is not None and hours > 0:
            item = dict(row)
            item['_fish'], item['_hours'] = fish, hours
            valid.append(item)
    if not valid:
        print('No rows with positive hours and numeric fish_caught.')
        return

    total_rate = sum(r['_fish'] for r in valid) / sum(r['_hours'] for r in valid)
    mean_rate = sum(r['_fish'] / r['_hours'] for r in valid) / len(valid)
    print(f'Rows used: {len(valid)}; exposure-weighted fish/hour: {total_rate:.4f}; mean trip fish/hour: {mean_rate:.4f}.')

    if 'livebait' in valid[0]:
        groups = {}
        for r in valid:
            key = str(r.get('livebait', '')).strip().lower()
            groups.setdefault(key, [0.0, 0.0, 0])
            groups[key][0] += r['_fish']
            groups[key][1] += r['_hours']
            groups[key][2] += 1
        parts = []
        for key, (fish, hours, n) in sorted(groups.items()):
            if hours > 0:
                parts.append(f'{key or "missing"}: {fish / hours:.4f} ({n})')
        if parts:
            print('Livebait groups, fish/hour (n): ' + '; '.join(parts) + '.')

    predictors = ['livebait', 'camper', 'persons', 'child', 'hours']
    numeric = []
    for r in valid:
        y = r['_fish'] / r['_hours']
        x = [1.0]
        ok = True
        for col in predictors:
            value = to_float(r.get(col))
            if value is None:
                ok = False
                break
            x.append(value)
        if ok:
            numeric.append((x, y))
    if len(numeric) >= len(predictors) + 2:
        k = len(predictors) + 1
        a = [[0.0] * k for _ in range(k)]
        b = [0.0] * k
        for x, y in numeric:
            for i in range(k):
                b[i] += x[i] * y
                for j in range(k):
                    a[i][j] += x[i] * x[j]
        for i in range(k):
            pivot = max(range(i, k), key=lambda q: abs(a[q][i]))
            if abs(a[pivot][i]) < 1e-12:
                print('Adjusted model unavailable because predictors are collinear.')
                return
            a[i], a[pivot] = a[pivot], a[i]
            b[i], b[pivot] = b[pivot], b[i]
            div = a[i][i]
            a[i] = [v / div for v in a[i]]
            b[i] /= div
            for q in range(k):
                if q != i:
                    factor = a[q][i]
                    a[q] = [a[q][j] - factor * a[i][j] for j in range(k)]
                    b[q] -= factor * b[i]
        print('Adjusted OLS coefficients for fish/hour: ' + ', '.join(f'{name}={coef:.4f}' for name, coef in zip(['intercept'] + predictors, b)) + f' (n={len(numeric)}).')
    else:
        print('Adjusted model unavailable because insufficient complete numeric rows.')


if __name__ == '__main__':
    main()
