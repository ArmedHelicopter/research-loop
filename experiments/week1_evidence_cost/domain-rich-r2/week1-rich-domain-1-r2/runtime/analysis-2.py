import json
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

facts = []
limitations = [
    'Observational, unadjusted associations do not establish causality; confounding and selection may explain part of the relationship.',
    'No survey weights or sampling-design information are supplied; estimates describe the available sample. Confidence intervals assume independent observations.',
    'The profile is an execution receipt, not scientific validation. Negative SES values are retained because the reported SES scale includes legitimate negative values; no undocumented sentinel codes are assumed.'
]

def number(x, digits=6):
    try:
        x = float(x)
        return round(x, digits) if np.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None

def add(key, label, value, unit, population, method):
    facts.append(dict(key=key, label=label, value=value, unit=unit,
                      population=population, method=method, premise_claim_ids=[]))

def run():
    df = pd.read_csv('/input/data')
    required = ['SES', 'BA DEGREE COMPLETED']
    missing = [c for c in required if c not in df.columns]
    if missing:
        limitations.append('Required columns absent: ' + ', '.join(missing) + '. No substitute outcome was used.')
        return
    raw = df['BA DEGREE COMPLETED']
    tokens = raw.astype('string').str.strip().str.lower()
    mapping = {'true': 1.0, 'false': 0.0, '1': 1.0, '0': 0.0,
               '1.0': 1.0, '0.0': 0.0}
    unknown = raw.notna() & ~tokens.isin(list(mapping))
    if unknown.any():
        labels = sorted(tokens[unknown].dropna().unique().tolist())
        limitations.append('Unrecognized BA indicator labels: ' + repr(labels)[:350] + '. Analysis stopped rather than recoding an uncertain outcome.')
        return
    y_all = tokens.map(mapping).astype(float)
    x_all = pd.to_numeric(df['SES'], errors='coerce')
    valid_x = np.isfinite(x_all.to_numpy(dtype=float))
    keep = valid_x & y_all.notna().to_numpy()
    x = x_all[keep].to_numpy(dtype=float)
    y = y_all[keep].to_numpy(dtype=float)
    n = len(y)
    population = 'Respondents with finite SES and recognized nonmissing BA status; n=' + str(n)
    add('sample_n', 'Complete-case analysis sample', n, 'respondents', population,
        'Retain finite numeric SES and BA labels True/False or 1/0; input rows=' + str(len(df)))
    limitations.append('Input rows=' + str(len(df)) + '; included=' + str(n) + '; excluded=' + str(len(df)-n) + '; invalid or missing SES=' + str((~valid_x).sum()) + '; missing BA=' + str(y_all.isna().sum()) + '. Exclusion categories can overlap.')
    limitations.append('Observed nonmissing BA labels: ' + repr(sorted(tokens.dropna().unique().tolist())) + '; True/1 denotes completed BA.')
    if 'CASE ID' in df.columns and df.loc[keep, 'CASE ID'].duplicated().any():
        limitations.append('Repeated CASE ID values occur in the analysis sample; rows are retained, and independence-based intervals may be inappropriate.')
    if n == 0:
        limitations.append('No usable observations; association statistics are undefined.')
        return
    add('ba_rate', 'BA degree completion rate', number(100*y.mean()), 'percent', population,
        '100 times mean of the binary BA indicator')
    q25, q75 = np.quantile(x, [0.25, 0.75])
    low = x <= q25
    high = x >= q75
    disjoint = q25 < q75
    if disjoint:
        pl, ph = y[low].mean(), y[high].mean()
        nl, nh = int(low.sum()), int(high.sum())
        add('low_rate', 'BA completion at or below SES 25th percentile', number(100*pl), 'percent',
            'Complete-case respondents with SES <= ' + str(number(q25)) + '; n=' + str(nl),
            'Empirical SES 25th percentile; boundary ties included; mean BA indicator times 100')
        add('high_rate', 'BA completion at or above SES 75th percentile', number(100*ph), 'percent',
            'Complete-case respondents with SES >= ' + str(number(q75)) + '; n=' + str(nh),
            'Empirical SES 75th percentile; boundary ties included; mean BA indicator times 100')
        add('rate_gap', 'High-SES minus low-SES BA completion rate', number(100*(ph-pl)), 'percentage points',
            'Complete-case lower SES group n=' + str(nl) + ' and upper SES group n=' + str(nh),
            '100 times upper-group completion proportion minus lower-group proportion')
        limitations.append('SES tail groups include percentile-boundary ties and may contain more than 25% of the sample.')
    else:
        limitations.append('SES 25th and 75th percentiles coincide; overlapping tail-group contrasts are omitted.')
    sd = np.std(x, ddof=1) if n > 1 else np.nan
    variable_x = np.isfinite(sd) and sd > 0
    variable_y = np.unique(y).size == 2
    r = np.corrcoef(x, y)[0, 1] if variable_x and variable_y else None
    add('ses_ba_r', 'SES and BA completion point-biserial correlation', number(r), 'correlation coefficient', population,
        'Pearson correlation between continuous SES and BA indicator coded 0/1')
    odds_ratio = None
    interval = None
    if variable_x and variable_y:
        try:
            z = (x-x.mean())/sd
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                fit = sm.GLM(y, sm.add_constant(z), family=sm.families.Binomial()).fit(maxiter=100, cov_type='HC0')
            if not fit.converged:
                raise ValueError('model did not converge')
            if any('separation' in str(w.message).lower() for w in caught):
                raise ValueError('possible separation')
            beta, se = float(fit.params[1]), float(fit.bse[1])
            if not np.isfinite(beta) or not np.isfinite(se) or se < 0:
                raise ValueError('nonfinite coefficient or standard error')
            with np.errstate(over='ignore', invalid='ignore'):
                estimates = np.exp([beta, beta-norm.ppf(.975)*se, beta+norm.ppf(.975)*se])
            if not np.isfinite(estimates).all():
                raise ValueError('odds ratio or interval overflow')
            odds_ratio = number(estimates[0])
            interval = '[' + str(number(estimates[1])) + ', ' + str(number(estimates[2])) + ']'
        except Exception as exc:
            limitations.append('Logistic association unavailable: ' + type(exc).__name__ + ': ' + str(exc)[:180])
    else:
        limitations.append('SES or BA has insufficient variation; correlation and logistic association are undefined.')
    method = 'Unadjusted binomial logistic GLM with intercept and SES standardized by sample SD=' + str(number(sd))
    add('ses_or', 'BA completion odds ratio per one sample SD higher SES', odds_ratio, 'odds ratio', population, method)
    add('ses_or_ci', '95% confidence interval for SES odds ratio', interval, 'odds ratio interval', population,
        method + '; exponentiated coefficient +/- 1.959964 times HC0 robust standard error')
    limitations.append('The logistic model assumes a linear relationship between SES and log odds. Odds ratios are not probability ratios; the tail-group rate difference provides a direct descriptive probability contrast.')

try:
    run()
except Exception as exc:
    limitations.append('Analysis could not fully complete: ' + type(exc).__name__ + ': ' + str(exc)[:250])
print(json.dumps({'facts': facts, 'limitations': limitations}, allow_nan=False, separators=(',', ':')))
