import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import json
from pathlib import Path
import numpy as np
import pandas as pd

# Frozen family 2 check: five empirical SES bins, without assuming
# linear log odds. No outcome-dependent choice of bins or replacement method.
LIMITATIONS = [
    'Family 2: sensitivity to SES operationalization/functional form. Five prespecified empirical SES bins qualify the primary linear-logit summary by describing the association across the SES distribution.',
    'Unadjusted observational descriptions are noncausal; demographic and academic confounding remain possible.',
    'No survey weights or sampling-design information are available; estimates describe analyzed respondents.',
    'Binning discards within-bin information and depends on empirical cutpoints. Ties remain together, so bin sizes can differ.',
    'The fifth bin uses SES strictly above the 80th-percentile threshold; the primary top-quintile definition includes equality. Boundary ties can therefore change the reported gap.',
    'Program-reported statistics are not independently validated scientific findings.'
]

def main():
    files = sorted(Path('/input/data').rglob('nls_ses_processed.csv'))
    if len(files) != 1:
        raise ValueError('Expected exactly one nls_ses_processed.csv under /input/data.')
    df = pd.read_csv(files[0])
    required = {'SES', 'BA DEGREE COMPLETED'}
    if not required.issubset(df.columns):
        raise ValueError('Required SES or BA completion column is absent.')
    ses = pd.to_numeric(df['SES'], errors='coerce')
    labels = df['BA DEGREE COMPLETED'].astype('string').str.strip().str.lower()
    outcome = labels.map({'true': 1, 'false': 0, '1': 1, '0': 0, '1.0': 1, '0.0': 0})
    unknown = df['BA DEGREE COMPLETED'].notna() & outcome.isna()
    if unknown.any():
        raise ValueError('Unexpected nonmissing BA labels; no alternative coding was prespecified.')
    keep = np.isfinite(ses.to_numpy(dtype=float)) & outcome.notna().to_numpy()
    x = ses.loc[keep].to_numpy(dtype=float)
    y = outcome.loc[keep].to_numpy(dtype=float)
    n = len(x)
    if n == 0:
        raise ValueError('No valid SES and BA observations.')
    cuts = np.quantile(x, [0.2, 0.4, 0.6, 0.8], method='linear')
    if not np.all(np.diff(cuts) > 0):
        raise ValueError('Distinct quintile cutpoints unavailable; the frozen five-bin check cannot be computed.')
    # Equality goes to the lower bin: Q1 <= q20; Q5 > q80.
    groups = np.searchsorted(cuts, x, side='left')
    pop = f'Respondents with finite numeric SES and valid observed BA completion; n={n}'
    facts = []
    def add(key, label, value, unit, population, method, premises=None):
        facts.append({'key': key, 'label': label, 'value': value,
                      'unit': unit, 'population': population, 'method': method,
                      'premise_claim_ids': [] if premises is None else premises})
    add('analysis_n', 'SES bin analysis sample', n, 'respondents', pop,
        f'Of {len(df)} CSV rows, retain {n}; exclude {len(df)-n} with nonfinite SES or missing BA. Retain negative SES; no undocumented sentinel rules.')
    rates = []
    counts = []
    for j in range(5):
        mask = groups == j
        nj = int(mask.sum())
        completed = int(y[mask].sum())
        rate = float(y[mask].mean()) if nj else None
        rates.append(rate)
        counts.append(nj)
        lower = '-infinity' if j == 0 else format(float(cuts[j-1]), '.12g')
        upper = '+infinity' if j == 4 else format(float(cuts[j]), '.12g')
        interval = f'{lower} < SES <= {upper}'
        add(f'q{j+1}_rate', f'BA completion in SES bin {j+1}',
            None if rate is None else round(100 * rate, 6), 'percent',
            f'{pop}; bin {j+1}: {interval}; subgroup n={nj}',
            f'100 times {completed}/{nj}; empirical 20th, 40th, 60th and 80th percentiles using linear interpolation; cutpoints computed at full precision; equality assigned to the lower bin. Empty-bin rate is null.')
    gap = None if rates[0] is None or rates[4] is None else round(100 * (rates[4]-rates[0]), 6)
    add('q5_q1_gap', 'Highest minus lowest SES bin BA completion', gap,
        'percentage points', f'{pop}; lowest n={counts[0]}; highest n={counts[4]}',
        'Recomputed 100 times (Q5 completion fraction minus Q1 completion fraction). Qualifies the cited primary top-minus-bottom quintile statistic using an exhaustive, mutually exclusive five-bin operationalization. Q1 retains SES <= q20; Q5 uses SES > q80 instead of the primary SES >= q80, so threshold ties may alter the contrast. The middle-bin rates describe shape without imposing linear log odds.',
        ['002a2d8b3122c915df6b5e16b64e8c493de661eecb56991d0ef4bf412d9e93a4'])
    return {'facts': facts, 'limitations': LIMITATIONS}

try:
    result = main()
except Exception as exc:
    result = {'facts': [], 'limitations': LIMITATIONS + [f'Frozen check could not be completed: {type(exc).__name__}: {str(exc)[:500]}']}
print(json.dumps(result, allow_nan=False, separators=(',', ':')))
