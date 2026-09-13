import csv
import math
from pathlib import Path

path = Path('/input/data.csv')
if not path.exists():
    print('No /input/data.csv found.')
    raise SystemExit

with path.open(newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))


def norm(v):
    return str(v).strip().lower()


def num(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None

ethics = []
for r in rows:
    topic = ' '.join(norm(r.get(k, '')) for k in ('topic_of_debate', 'philosophical_topic'))
    if 'ethic' in topic:
        ethics.append(r)

if not ethics:
    ethics = rows

outcome = 'percentage_increase_in_utilitarianism'
features = [
    'argument_intensity', 'audience_interest_level',
    'average_debate_duration', 'number_of_sessions'
]

def mean(values):
    return sum(values) / len(values) if values else None

def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    ax = mean([p[0] for p in pairs])
    ay = mean([p[1] for p in pairs])
    nume = sum((x-ax)*(y-ay) for x, y in pairs)
    den = math.sqrt(sum((x-ax)**2 for x, y in pairs) * sum((y-ay)**2 for x, y in pairs))
    return nume / den if den else None

def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'

ys = [num(r, outcome) for r in ethics]
print(f'ethics_rows={len(ethics)} outcome_mean={fmt(mean([x for x in ys if x is not None]))}')

for feature in features:
    print(f'corr_{feature}_vs_outcome={fmt(pearson([num(r, feature) for r in ethics], ys))}')

for r in ethics:
    event = norm(r.get('critical_event_occurred', ''))
    if event in ('1', 'true', 'yes', 'y'):
        r['_event'] = 'yes'
    elif event in ('0', 'false', 'no', 'n'):
        r['_event'] = 'no'
    else:
        r['_event'] = event or 'unknown'

for event in sorted(set(r['_event'] for r in ethics)):
    vals = [num(r, outcome) for r in ethics if r['_event'] == event]
    vals = [v for v in vals if v is not None]
    print(f'critical_event={event} n={len(vals)} outcome_mean={fmt(mean(vals))}')

stances = sorted(set(norm(r.get('moderator_ethical_stance', '')) or 'unknown' for r in ethics))
for stance in stances:
    vals = [num(r, outcome) for r in ethics if norm(r.get('moderator_ethical_stance', '')) == stance]
    vals = [v for v in vals if v is not None]
    print(f'stance={stance} n={len(vals)} outcome_mean={fmt(mean(vals))}')

for stance in stances:
    for event in ('no', 'yes'):
        vals = [num(r, outcome) for r in ethics if norm(r.get('moderator_ethical_stance', '')) == stance and r['_event'] == event]
        vals = [v for v in vals if v is not None]
        if vals:
            print(f'stance={stance} critical_event={event} n={len(vals)} outcome_mean={fmt(mean(vals))}')