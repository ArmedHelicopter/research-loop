import csv, math
from collections import defaultdict

path = '/input/public_csv'
num_cols = ['percentage_increase_in_utilitarianism', 'argument_intensity', 'audience_interest_level', 'average_debate_duration', 'number_of_sessions']
cat_cols = ['moderator_ethical_stance', 'critical_event_occurred']
rows = []
with open(path, newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

def val(r, c):
    try:
        x = float(r[c])
        return x if math.isfinite(x) else None
    except (KeyError, TypeError, ValueError):
        return None

def mean(xs):
    return sum(xs) / len(xs) if xs else None

def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    mx, my = mean([p[0] for p in pairs]), mean([p[1] for p in pairs])
    sx = math.sqrt(sum((x-mx)**2 for x, y in pairs))
    sy = math.sqrt(sum((y-my)**2 for x, y in pairs))
    return sum((x-mx)*(y-my) for x, y in pairs)/(sx*sy) if sx and sy else None

def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'

y = [val(r, num_cols[0]) for r in rows]
print(f'n={len(rows)}; outcome_mean={fmt(mean([x for x in y if x is not None]))}; outcome_missing={sum(x is None for x in y)}')
for c in num_cols[1:]:
    print(f'corr(outcome,{c})={fmt(corr(y, [val(r,c) for r in rows]))}')

def grouped(label, keyfunc):
    groups = defaultdict(list)
    for r in rows:
        k, z = keyfunc(r), val(r, num_cols[0])
        if z is not None and k not in (None, ''):
            groups[str(k)].append(z)
    print(label + ': ' + '; '.join(f'{k}:n={len(v)},mean={fmt(mean(v))}' for k, v in sorted(groups.items())))

grouped('by_critical_event', lambda r: r.get('critical_event_occurred'))
grouped('by_moderator_stance', lambda r: r.get('moderator_ethical_stance'))

stances = sorted({r.get('moderator_ethical_stance') for r in rows if r.get('moderator_ethical_stance')})
for s in stances:
    groups = defaultdict(list)
    for r in rows:
        if r.get('moderator_ethical_stance') == s and val(r, num_cols[0]) is not None:
            groups[str(r.get('critical_event_occurred'))].append(val(r, num_cols[0]))
    if len(groups) >= 2:
        keys = sorted(groups)
        print(f'stance={s}; event_difference({keys[-1]}-{keys[0]})={fmt(mean(groups[keys[-1]])-mean(groups[keys[0]]))}')

for c in ['argument_intensity', 'audience_interest_level', 'average_debate_duration', 'number_of_sessions']:
    xs = [val(r,c) for r in rows if val(r,c) is not None]
    if not xs: continue
    med = sorted(xs)[(len(xs)-1)//2]
    groups = defaultdict(list)
    for r in rows:
        x, z = val(r,c), val(r,num_cols[0])
        if x is not None and z is not None:
            groups[('high' if x >= med else 'low', str(r.get('critical_event_occurred')))].append(z)
    diffs = []
    for level in ['low','high']:
        g = groups.get((level,'1'), [])
        h = groups.get((level,'0'), [])
        if g and h: diffs.append(f'{level}_event_minus_no_event={fmt(mean(g)-mean(h))}')
    print(f'{c}_median={fmt(med)}; ' + '; '.join(diffs))