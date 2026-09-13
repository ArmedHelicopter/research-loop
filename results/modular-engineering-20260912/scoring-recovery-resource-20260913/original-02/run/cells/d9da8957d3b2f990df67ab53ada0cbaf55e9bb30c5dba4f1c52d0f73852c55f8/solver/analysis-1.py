import csv
import math
from pathlib import Path

path = Path('/input/public_csv')
rows = []
try:
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {}
            for key in ('fish_caught', 'livebait', 'camper', 'persons', 'child', 'hours'):
                try:
                    row[key] = float(raw.get(key, '').strip())
                except (AttributeError, TypeError, ValueError):
                    row[key] = math.nan
            rows.append(row)
except OSError as exc:
    print(f'Unable to read dataset: {exc}')
    raise SystemExit(1)

valid = [r for r in rows if math.isfinite(r['fish_caught']) and math.isfinite(r['hours']) and r['hours'] > 0]
rates = [r['fish_caught'] / r['hours'] for r in valid]
print(f'Valid trips: {len(valid)} of {len(rows)}; mean fish caught per hour: {sum(rates)/len(rates):.3f}' if rates else 'No valid trips with positive hours.')

for name in ('livebait', 'camper'):
    groups = {}
    for r in valid:
        if math.isfinite(r[name]):
            groups.setdefault(r[name], []).append(r['fish_caught'] / r['hours'])
    if groups:
        summary = ', '.join(f'{k:g}={sum(v)/len(v):.3f} (n={len(v)})' for k, v in sorted(groups.items()))
        print(f'{name} group mean rates: {summary}')

def correlation(name):
    pairs = [(r[name], r['fish_caught'] / r['hours']) for r in valid if math.isfinite(r[name])]
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (denx * deny) if denx and deny else None

for name in ('persons', 'child'):
    corr = correlation(name)
    if corr is not None:
        print(f'{name} versus hourly rate Pearson r: {corr:.3f}')