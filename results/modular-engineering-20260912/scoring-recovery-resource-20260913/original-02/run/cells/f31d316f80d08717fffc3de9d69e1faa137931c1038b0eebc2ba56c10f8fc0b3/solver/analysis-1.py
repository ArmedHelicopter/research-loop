import csv, math, os

PATH = '/input/public_csv'
TARGET = 'percentage_increase_in_utilitarianism'
NUMERIC = ['argument_intensity', 'audience_interest_level', 'average_debate_duration', 'number_of_sessions']

def num(x):
    try:
        return float(str(x).strip().replace('%', ''))
    except (TypeError, ValueError):
        return None

def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    ax = sum(x for x, _ in pairs) / len(pairs)
    ay = sum(y for _, y in pairs) / len(pairs)
    dx = [x - ax for x, _ in pairs]
    dy = [y - ay for _, y in pairs]
    den = math.sqrt(sum(v*v for v in dx) * sum(v*v for v in dy))
    return None if den == 0 else sum(x*y for x, y in zip(dx, dy)) / den

def mean(vals):
    vals = [v for v in vals if v is not None]
    return None if not vals else sum(vals) / len(vals)

def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'

def main():
    with open(PATH, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    ethics = [r for r in rows if 'ethic' in ((r.get('philosophical_topic') or '') + ' ' + (r.get('topic_of_debate') or '')).lower()]
    data = ethics or rows
    y = [num(r.get(TARGET)) for r in data]
    print(f'rows={len(data)} ethics_filtered={bool(ethics)} target_mean={fmt(mean(y))}')
    for col in NUMERIC:
        print(f'corr_{col}={fmt(corr([num(r.get(col)) for r in data], y))}')
    stances = sorted({(r.get('moderator_ethical_stance') or 'missing').strip().lower() for r in data})
    for s in stances:
        vals = [num(r.get(TARGET)) for r in data if (r.get('moderator_ethical_stance') or 'missing').strip().lower() == s]
        print(f'stance[{s}]_n={len(vals)}_mean={fmt(mean(vals))}')
    events = sorted({(r.get('critical_event_occurred') or 'missing').strip().lower() for r in data})
    for e in events:
        vals = [num(r.get(TARGET)) for r in data if (r.get('critical_event_occurred') or 'missing').strip().lower() == e]
        print(f'event[{e}]_n={len(vals)}_mean={fmt(mean(vals))}')

if __name__ == '__main__':
    main()