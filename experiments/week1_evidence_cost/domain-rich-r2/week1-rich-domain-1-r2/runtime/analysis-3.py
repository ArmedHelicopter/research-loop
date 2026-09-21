import json
import numpy as np
import pandas as pd

# Frozen check: family (2), SES operationalization/functional form.
# Examine four empirical SES quartile groups without assuming linear log odds.
df = pd.read_csv('/input/data')
ses = pd.to_numeric(df['SES'], errors='coerce')
ba = df['BA DEGREE COMPLETED'].astype('string').str.strip().str.lower().map({'true': 1.0, 'false': 0.0, '1': 1.0, '0': 0.0, '1.0': 1.0, '0.0': 0.0})
keep = np.isfinite(ses.to_numpy(dtype=float)) & ba.notna().to_numpy()
x = ses.loc[keep].to_numpy(dtype=float)
y = ba.loc[keep].to_numpy(dtype=float)
n = len(y)
facts = []
limitations = [
    'Family (2): SES operationalization/functional form. Four prespecified empirical quartile groups reveal the descriptive completion-rate pattern without assuming SES is linear in log odds. This method is frozen before execution.',
    'These are unadjusted observational sample descriptions, not causal effects. Confounding and selection remain possible.',
    'No survey weights or sampling design are available. Quartile estimates can be imprecise when BA completions are sparse; no confidence intervals or significance tests are calculated.',
    'Quartile grouping discards within-group variation and cannot establish monotonicity within groups or validate the logistic functional form.',
    'Execution and output binding do not independently validate scientific correctness.',
    f'Input rows={len(df)}; included={n}; excluded={len(df)-n}. Finite negative SES values are retained; no undocumented sentinel codes are assumed.'
]

def add(key, label, value, unit, population, method, premises=None):
    facts.append(dict(key=key, label=label, value=value, unit=unit,
                      population=population, method=method,
                      premise_claim_ids=[] if premises is None else premises))

population = f'Respondents with finite numeric SES and recognized binary BA status; n={n}'
add('sample_n', 'Quartile analysis sample', n, 'respondents', population,
    'Retain finite numeric SES and BA labels True/False or 1/0, including equivalent numeric strings.')

if n == 0:
    limitations.append('No eligible observations; quartile rates and contrasts are undefined.')
else:
    cuts = np.quantile(x, [0.25, 0.50, 0.75], method='linear')
    # Boundary ties go entirely into the lower interval; no rank-based tie splitting.
    group = np.searchsorted(cuts, x, side='left')
    bounds = [
        f'SES <= {cuts[0]:.10g}',
        f'{cuts[0]:.10g} < SES <= {cuts[1]:.10g}',
        f'{cuts[1]:.10g} < SES <= {cuts[2]:.10g}',
        f'SES > {cuts[2]:.10g}'
    ]
    rates = []
    sizes = []
    for j in range(4):
        selected = group == j
        nj = int(selected.sum())
        sizes.append(nj)
        rate = float(y[selected].mean()) if nj else None
        rates.append(rate)
        successes = int(y[selected].sum())
        add(f'q{j+1}_rate', f'BA completion in SES quartile group {j+1}',
            None if rate is None else round(100 * rate, 6), 'percent',
            f'Eligible respondents with {bounds[j]}; n={nj}',
            f'100 times BA successes / group size; successes={successes}. '
            'Cutpoints are empirical 25th, 50th and 75th percentiles using linear interpolation; '
            'boundary ties are assigned to the lower interval. Empty groups return null.')
    gap = None if rates[0] is None or rates[3] is None else round(100 * (rates[3] - rates[0]), 6)
    add('quartile_gap', 'Upper minus lower SES quartile-group BA completion rate', gap,
        'percentage points',
        f'Eligible lower group n={sizes[0]} and upper group n={sizes[3]}',
        '100 times recomputed upper-group BA proportion minus lower-group proportion. '
        'This qualifies the prior tail-gap statistic by using mutually exclusive quartile intervals: '
        'the upper group uses SES > the 75th percentile, whereas the prior statistic used >=. '
        'It is a related descriptive contrast, not an exact replication or an adjusted effect.',
        ['727a1c9ebcedcae36301a68b10070fc0340214c19f81c160bc4f147e789ea8c5'])
    limitations.append('Boundary ties can produce unequal group sizes; coincident cutpoints can produce empty groups, reported as null. No alternative grouping is selected after observing results.')
    limitations.append('The cited dependency declares the interpretive relationship to the prior tail-gap claim; it does not assert verified logical entailment or independent support.')

print(json.dumps({'facts': facts, 'limitations': limitations}, allow_nan=False))