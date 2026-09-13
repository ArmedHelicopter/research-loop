import csv
import json
import math
from pathlib import Path

path = Path('/input/data.csv')
with path.open(newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

outcome = 'percentage_increase_in_utilitarianism'
numeric_predictors = [
    'argument_intensity', 'audience_interest_level',
    'average_debate_duration', 'number_of_sessions'
]

def num(row, col):
    try:
        value = row.get(col, '')
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None

def pearson(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 2:
        return None
    xa = [p[0] for p in pairs]
    ya = [p[1] for p in pairs]
    mx, my = sum(xa) / len(xa), sum(ya) / len(ya)
    den = math.sqrt(sum((a-mx)**2 for a in xa) * sum((b-my)**2 for b in ya))
    return round(sum((a-mx)*(b-my) for a, b in pairs) / den, 4) if den else None

def mean(values):
    return round(sum(values) / len(values), 4) if values else None

correlations = {}
for col in numeric_predictors:
    correlations[col] = pearson([num(r, col) for r in rows], [num(r, outcome) for r in rows])

def grouped(col):
    groups = {}
    for r in rows:
        key = r.get(col, '')
        value = num(r, outcome)
        if key and value is not None:
            groups.setdefault(key, []).append(value)
    return {k: {'n': len(v), 'mean_outcome': mean(v)} for k, v in sorted(groups.items())}

engagement_cols = ['argument_intensity', 'audience_interest_level',
                   'average_debate_duration', 'number_of_sessions']
medians = {}
for col in engagement_cols:
    vals = sorted(v for v in (num(r, col) for r in rows) if v is not None)
    medians[col] = vals[len(vals)//2] if vals else None

high_event, low_no_event = [], []
for r in rows:
    y = num(r, outcome)
    event = str(r.get('critical_event_occurred', '')).strip().lower() in ('1', 'true', 'yes', 'y')
    high = all(num(r, c) is not None and medians[c] is not None and num(r, c) >= medians[c] for c in engagement_cols)
    if y is not None and high and event:
        high_event.append(y)
    if y is not None and not high and not event:
        low_no_event.append(y)

result = {
    'n_rows': len(rows),
    'pearson_correlations_with_outcome': correlations,
    'mean_outcome_by_moderator_stance': grouped('moderator_ethical_stance'),
    'mean_outcome_by_critical_event': grouped('critical_event_occurred'),
    'high_engagement_with_event': {'n': len(high_event), 'mean_outcome': mean(high_event)},
    'low_engagement_without_event': {'n': len(low_no_event), 'mean_outcome': mean(low_no_event)},
    'engagement_medians': medians
}
print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))