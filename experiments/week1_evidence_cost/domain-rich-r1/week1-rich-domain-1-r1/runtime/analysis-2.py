import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings('ignore', category=RuntimeWarning)
facts = []
limitations = [
    'Observational, unadjusted associations do not establish causality; confounding and selection may explain part of the association.',
    'No survey weights or sampling-design variables are supplied. Estimates describe the analyzed respondents; confidence intervals assume independent observations.',
    'SES units are not documented. Negative SES values are retained because the supplied profile includes legitimate negative values; no undocumented sentinel codes are assumed.',
    'The logistic model assumes a linear relationship between SES and log odds. Odds ratios are not risk ratios.'
]

def finite(x, digits=6):
    try:
        x = float(x)
        return round(x, digits) if np.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None

def add(key, label, value, unit, population, method):
    facts.append(dict(key=key, label=label, value=value, unit=unit,
                      population=population, method=method, premise_claim_ids=[]))

def analyze():
    base = Path('/input/data')
    path = base / 'nls_ses_processed.csv' if base.is_dir() else base
    df = pd.read_csv(path)
    required = ['SES', 'BA DEGREE COMPLETED']
    missing = [c for c in required if c not in df.columns]
    if missing:
        limitations.append('Analysis stopped: required columns absent: ' + ', '.join(missing))
        return
    raw = df['BA DEGREE COMPLETED']
    labels = raw.astype('string').str.strip().str.lower()
    mapping = {'true': 1, 'false': 0, '1': 1, '0': 0, '1.0': 1, '0.0': 0}
    unknown = raw.notna() & ~labels.isin(mapping)
    if unknown.any():
        examples = sorted(set(labels[unknown].astype(str)))[:8]
        limitations.append('Analysis stopped: unexpected BA indicator labels: ' + repr(examples)[:400] + '. No replacement outcome was used.')
        add('input_n', 'Input rows', int(len(df)), 'respondents',
            'All input rows; n=' + str(len(df)), 'CSV row count before outcome validation')
        return
    y = labels.map(mapping).astype(float)
    x = pd.to_numeric(df['SES'], errors='coerce').astype(float)
    good_x = np.isfinite(x)
    good_y = y.notna()
    keep = good_x & good_y
    n = int(keep.sum())
    pop = 'Respondents with finite numeric SES and valid observed BA completion; n=' + str(n)
    add('analysis_n', 'Complete-case analysis sample', n, 'respondents', pop,
        'Of ' + str(len(df)) + ' input rows, exclude ' + str(int((~keep).sum())) +
        '; invalid/missing SES=' + str(int((~good_x).sum())) +
        '; missing outcome=' + str(int((~good_y).sum())) + '; exclusion counts may overlap')
    observed = sorted(set(labels[raw.notna()].astype(str)))
    limitations.append('Observed BA labels: ' + repr(observed) + '; true/1 mapped to completion and false/0 to noncompletion.')
    if 'CASE ID' in df.columns and df.loc[keep, 'CASE ID'].duplicated().any():
        limitations.append('Repeated CASE ID values occur in the analysis sample; rows are retained and independence-based intervals may be unreliable.')
    if n == 0:
        limitations.append('No valid complete cases; associations are undefined.')
        return
    x = x[keep].to_numpy()
    y = y[keep].to_numpy()
    add('ba_rate', 'BA degree completion prevalence', finite(100 * y.mean()), 'percent', pop,
        '100 times completed BA count / n; completed=' + str(int(y.sum())))
    variable_x = n > 1 and np.std(x, ddof=1) > 0
    variable_y = len(np.unique(y)) == 2
    r = np.corrcoef(x, y)[0, 1] if variable_x and variable_y else None
    add('ses_ba_r', 'SES and BA completion correlation', finite(r), 'correlation', pop,
        'Pearson point-biserial correlation of continuous SES and binary BA completion')
    q20, q80 = np.quantile(x, [0.2, 0.8])
    low = x <= q20
    high = x >= q80
    disjoint = not np.any(low & high)
    nl, nh = int(low.sum()), int(high.sum())
    pl, ph = float(y[low].mean()), float(y[high].mean())
    add('low_ses_ba', 'BA completion in bottom SES quintile', finite(100 * pl), 'percent',
        pop + '; SES <= sample 20th percentile; subgroup n=' + str(nl),
        'Empirical completion fraction; SES threshold=' + str(finite(q20)) + '; boundary ties retained')
    add('high_ses_ba', 'BA completion in top SES quintile', finite(100 * ph), 'percent',
        pop + '; SES >= sample 80th percentile; subgroup n=' + str(nh),
        'Empirical completion fraction; SES threshold=' + str(finite(q80)) + '; boundary ties retained')
    add('ses_rate_gap', 'Top minus bottom SES quintile BA completion', finite(100 * (ph - pl)) if disjoint else None,
        'percentage points', pop + '; bottom n=' + str(nl) + '; top n=' + str(nh),
        '100 times (top-quintile completion fraction minus bottom-quintile completion fraction)')
    limitations.append('Quintiles use empirical SES thresholds and retain ties, so subgroup sizes may exceed 20% of the sample.')
    if not disjoint:
        limitations.append('SES quintile groups overlap because thresholds coincide; their contrast is reported as null.')
    odds_ratio, interval = None, None
    if variable_x and variable_y:
        z = (x - x.mean()) / np.std(x, ddof=1)
        try:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter('always')
                fit = sm.GLM(y, sm.add_constant(z), family=sm.families.Binomial()).fit(maxiter=100, cov_type='HC0')
            separation = any('separation' in str(w.message).lower() for w in captured)
            if not fit.converged or separation:
                limitations.append('Logistic model did not converge reliably or encountered separation; model estimates are null.')
            else:
                beta = float(fit.params[1])
                bounds = np.asarray(fit.conf_int())[1]
                odds_ratio = finite(np.exp(beta))
                ci = [finite(np.exp(v)) for v in bounds]
                if all(v is not None for v in ci):
                    interval = '[' + str(ci[0]) + ', ' + str(ci[1]) + ']'
                if odds_ratio is None or interval is None:
                    limitations.append('Nonfinite logistic estimates or interval bounds are represented by null.')
        except Exception as exc:
            limitations.append('Logistic estimation unavailable: ' + type(exc).__name__)
    else:
        limitations.append('Insufficient variation in SES or BA completion; correlation and logistic association may be undefined.')
    add('ses_or', 'BA completion odds ratio per one sample SD higher SES', odds_ratio, 'odds ratio', pop,
        'Unadjusted binomial-logit GLM with intercept; exp(SES coefficient), SES standardized using sample SD')
    add('ses_or_ci', '95% confidence interval for SES odds ratio', interval, 'odds ratio interval', pop,
        'Exponentiated coefficient Wald interval using HC0 robust covariance; independent-respondent assumption')

try:
    analyze()
except Exception as exc:
    limitations.append('Analysis could not be completed: ' + type(exc).__name__ + ': ' + str(exc)[:250])
print(json.dumps({'facts': facts, 'limitations': limitations}, allow_nan=False, separators=(',', ':')))
