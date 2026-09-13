import csv
import glob
import os


def num(row, name):
    try:
        return float(row[name])
    except (KeyError, TypeError, ValueError):
        return None

files = sorted(glob.glob('/input/*.csv'))
if not files:
    print('No CSV input found.')
    raise SystemExit

path = next((p for p in files if os.path.basename(p).lower() == 'fish.csv'), files[0])
with open(path, newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

valid = []
for r in rows:
    fish = num(r, 'fish_caught')
    hours = num(r, 'hours')
    bait = num(r, 'livebait')
    if fish is not None and hours is not None and hours > 0:
        valid.append((fish, hours, bait))

if not valid:
    print('No valid rows with fish_caught and positive hours.')
    raise SystemExit

rates = [fish / hours for fish, hours, _ in valid]
weighted = sum(fish for fish, _, _ in valid) / sum(hours for _, hours, _ in valid)
print(f'Valid trips: {len(valid)}; total fish: {sum(f for f, _, _ in valid):.0f}; total hours: {sum(h for _, h, _ in valid):.2f}.')
print(f'Overall catch rate: {weighted:.3f} fish/hour (effort-weighted); mean trip rate: {sum(rates)/len(rates):.3f}.')

groups = {}
for fish, hours, bait in valid:
    if bait is not None:
        key = 'livebait=1' if bait != 0 else 'livebait=0'
        groups.setdefault(key, [0, 0.0, 0.0])
        groups[key][0] += 1
        groups[key][1] += fish
        groups[key][2] += hours
for key in ('livebait=0', 'livebait=1'):
    if key in groups:
        n, fish, hours = groups[key]
        print(f'{key}: n={n}, catch rate={fish/hours:.3f} fish/hour.')
if 'livebait=0' in groups and 'livebait=1' in groups:
    r0 = groups['livebait=0'][1] / groups['livebait=0'][2]
    r1 = groups['livebait=1'][1] / groups['livebait=1'][2]
    print(f'Livebait rate difference (1 minus 0): {r1-r0:.3f} fish/hour; descriptive association only.')