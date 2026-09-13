import csv, os, math
from collections import defaultdict

PATH = '/input/public_csv'
OUTCOME = 'percentage_increase_in_utilitarianism'
NUMERIC = ['argument_intensity', 'audience_interest_level', 'average_debate_duration', 'number_of_sessions', OUTCOME]
CATS = ['moderator_ethical_stance', 'critical_event_occurred']

def num(x):
    try:
        return float(str(x).strip().replace('%',''))
    except Exception:
        return None

def clean(x):
    return str(x).strip().lower()

def pearson(xs, ys):
    pairs = [(x,y) for x,y in zip(xs,ys) if x is not None and y is not None]
    if len(pairs) < 3: return None
    ax = sum(x for x,y in pairs)/len(pairs); ay = sum(y for x,y in pairs)/len(pairs)
    vx = sum((x-ax)**2 for x,y in pairs); vy = sum((y-ay)**2 for x,y in pairs)
    return None if vx == 0 or vy == 0 else sum((x-ax)*(y-ay) for x,y in pairs)/math.sqrt(vx*vy)

def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'

with open(PATH, newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

eth = [r for r in rows if 'ethic' in clean(r.get('philosophical_topic','')) or 'ethic' in clean(r.get('topic_of_debate',''))]
if eth: rows = eth
print(f'ethics_rows={len(rows)} total_rows={len(eth) if eth else len(rows)}')

for c in NUMERIC:
    vals = [num(r.get(c,'')) for r in rows]
    vals = [v for v in vals if v is not None]
    if vals: print(f'{c}: n={len(vals)} mean={sum(vals)/len(vals):.3f} min={min(vals):.3f} max={max(vals):.3f}')

for c in NUMERIC[:-1]:
    print(f'corr(outcome,{c})={fmt(pearson([num(r.get(OUTCOME,'')) for r in rows],[num(r.get(c,'')) for r in rows]))}')

for c in CATS:
    groups = defaultdict(list)
    for r in rows:
        y = num(r.get(OUTCOME,'')); key = clean(r.get(c,''))
        if y is not None and key: groups[key].append(y)
    vals = '; '.join(f'{k}:n={len(v)},mean={sum(v)/len(v):.3f}' for k,v in sorted(groups.items()))
    print(f'outcome_by_{c}: {vals or "NA"}')

# Optional adjusted OLS using numpy when available; one-hot encode categorical variables.
try:
    import numpy as np
    design=[]; target=[]
    stances = sorted({clean(r.get('moderator_ethical_stance','')) for r in rows if clean(r.get('moderator_ethical_stance',''))})
    events = sorted({clean(r.get('critical_event_occurred','')) for r in rows if clean(r.get('critical_event_occurred',''))})
    for r in rows:
        y=num(r.get(OUTCOME,'')); base=[num(r.get(c,'')) for c in NUMERIC[:-1]]
        if y is None or any(v is None for v in base): continue
        s=clean(r.get('moderator_ethical_stance','')); e=clean(r.get('critical_event_occurred',''))
        design.append([1.0]+base+[1.0 if s==z else 0.0 for z in stances[1:]]+[1.0 if e==z else 0.0 for z in events[1:]])
        target.append(y)
    if len(design) > len(design[0]) if design else False:
        b=np.linalg.lstsq(np.asarray(design),np.asarray(target),rcond=None)[0]
        pred=np.asarray(design)@b; r2=1-np.sum((np.asarray(target)-pred)**2)/np.sum((np.asarray(target)-np.mean(target))**2) if len(set(target))>1 else float('nan')
        names=['intercept']+NUMERIC[:-1]+[f'stance={z}' for z in stances[1:]]+[f'event={z}' for z in events[1:]]
        print('adjusted_ols_r2='+fmt(float(r2)))
        print('adjusted_ols_coefficients='+'; '.join(f'{n}:{v:.3f}' for n,v in zip(names,b)))
    else: print('adjusted_ols=insufficient_complete_rows')
except Exception as e:
    print('adjusted_ols=unavailable')