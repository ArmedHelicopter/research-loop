import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.special import expit
from statsmodels.stats.proportion import proportion_confint

warnings.filterwarnings('ignore', category=RuntimeWarning)

def clean_json(v):
    if isinstance(v, dict):
        return {str(k): clean_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [clean_json(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    return v

def main():
    base = Path('/input/data')
    path = base if base.is_file() else base / 'nls_ses_processed.csv'
    df = pd.read_csv(path)
    outcome = 'BA DEGREE COMPLETED'
    if outcome not in df.columns or 'SES' not in df.columns:
        raise ValueError('Required BA DEGREE COMPLETED or SES column missing; no outcome substitution allowed.')
    raw = df[outcome]
    labels = raw.dropna().astype(str).str.strip().str.lower()
    observed = sorted(labels.unique().tolist())
    mapping = {'true': 1, 'false': 0, '1': 1, '0': 0, '1.0': 1, '0.0': 0}
    unknown = [x for x in observed if x not in mapping]
    if unknown:
        raise ValueError('Unrecognized BA indicator labels: ' + repr(unknown)[:800])
    y = raw.astype('string').str.strip().str.lower().map(mapping)
    s = pd.to_numeric(df['SES'], errors='coerce')
    s = s.where(np.isfinite(s))
    keep = y.notna() & s.notna()
    d = pd.DataFrame({'ba': y[keep].astype(int), 'ses': s[keep].astype(float)})
    n = len(d)
    limits = [
        'Observational, unadjusted associations do not identify a causal effect of socioeconomic status.',
        'No survey weights, strata, or cluster identifiers are supplied; estimates are sample descriptions and intervals assume independent respondents.',
        'Processed-data selection and measurement limitations cannot be assessed from this CSV.',
        'SES quintiles are sample-relative; tied SES values stay together and group sizes may differ.',
        'Logistic estimates assume linear SES effects on log odds; quintile rates provide a less restrictive descriptive comparison.'
    ]
    out = {'question': 'How strongly does BA degree completion vary with socioeconomic status?',
           'outcome': outcome, 'observed_indicator_labels': observed,
           'indicator_mapping': {k: mapping[k] for k in observed},
           'counts': {'input_rows': len(df), 'analyzed_rows': n, 'excluded_rows': int((~keep).sum()),
                      'missing_outcome': int(y.isna().sum()), 'missing_or_invalid_ses': int(s.isna().sum())},
           'handling': 'Complete cases for BA and SES. Negative SES values are retained because the observed profile supports a signed continuous SES scale. No undocumented sentinel codes are inferred. Index and ID columns are not predictors.',
           'limitations': limits}
    if 'CASE ID' in df:
        out['counts']['duplicate_nonmissing_case_ids'] = int(df.loc[df['CASE ID'].notna(), 'CASE ID'].duplicated().sum())
        if out['counts']['duplicate_nonmissing_case_ids']:
            limits.append('Duplicate respondent IDs occur; rows are retained, so independence-based intervals require caution.')
    if n < 3:
        out['analysis_status'] = 'Insufficient complete cases.'
        return out
    sd = float(d.ses.std(ddof=1))
    out['overall'] = {'completed': int(d.ba.sum()), 'not_completed': int(n-d.ba.sum()),
                      'completion_rate': float(d.ba.mean()),
                      'completion_rate_ci95_wilson': proportion_confint(int(d.ba.sum()), n, method='wilson'),
                      'ses_mean': float(d.ses.mean()), 'ses_sd': sd,
                      'ses_quantiles': {str(q): float(d.ses.quantile(q)) for q in [0, .1, .25, .5, .75, .9, 1]}}
    if not np.isfinite(sd) or sd == 0:
        out['analysis_status'] = 'SES is constant; its association cannot be estimated.'
        return out
    groups, edges = pd.qcut(d.ses, 5, labels=False, retbins=True, duplicates='drop')
    rows = []
    for g, sub in d.groupby(groups, observed=True):
        k, ng = int(sub.ba.sum()), len(sub)
        rows.append({'group_low_to_high': int(g)+1, 'n': ng, 'completed': k,
                     'ses_min': float(sub.ses.min()), 'ses_max': float(sub.ses.max()),
                     'ses_mean': float(sub.ses.mean()), 'completion_rate': k/ng,
                     'completion_rate_ci95_wilson': proportion_confint(k, ng, method='wilson')})
    out['ses_quintiles'] = {'cut_edges': edges, 'groups': rows}
    if len(rows) >= 2:
        low, high = rows[0], rows[-1]
        p0, p1 = low['completion_rate'], high['completion_rate']
        l0, u0 = low['completion_rate_ci95_wilson']
        l1, u1 = high['completion_rate_ci95_wilson']
        diff = p1-p0
        ci = [diff-np.sqrt((p1-l1)**2+(u0-p0)**2), diff+np.sqrt((u1-p1)**2+(p0-l0)**2)]
        contrast = {'comparison': 'Highest versus lowest observed SES quantile group',
                    'completion_difference_percentage_points': 100*diff,
                    'difference_ci95_newcombe_percentage_points': [100*x for x in ci],
                    'completion_risk_ratio': p1/p0 if p0 > 0 else None}
        a, c = high['completed'], low['completed']
        if a > 0 and c > 0:
            se = np.sqrt(1/a-1/high['n']+1/c-1/low['n'])
            contrast['risk_ratio_ci95_log'] = np.exp(np.log(p1/p0)+np.array([-1, 1])*1.96*se)
        else:
            contrast['risk_ratio_ci95_log'] = None
            limits.append('A zero completion count prevents the usual log risk-ratio interval; no artificial count correction is used.')
        out['highest_lowest_contrast'] = contrast
    if d.ba.nunique() < 2:
        out['analysis_status'] = 'Outcome is constant; correlation and logistic association cannot be estimated.'
        return out
    out['point_biserial_correlation'] = float(d.ses.corr(d.ba))
    z = (d.ses-d.ses.mean())/sd
    X = np.column_stack([np.ones(n), z.to_numpy()])
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            fit = sm.GLM(d.ba.to_numpy(), X, family=sm.families.Binomial()).fit(cov_type='HC0', maxiter=100)
        model_warnings = list(dict.fromkeys(str(w.message)[:250] for w in caught))
        if not fit.converged or not np.all(np.isfinite(fit.params)) or any('separation' in w.lower() for w in model_warnings):
            raise ValueError('Logistic fit did not converge reliably or detected separation.')
        beta = np.asarray(fit.params)
        cov = np.asarray(fit.cov_params())
        se = np.sqrt(cov[1, 1])
        model = {'n': n, 'standardization': 'One sample SD of SES', 'covariance': 'HC0',
                 'odds_ratio_per_ses_sd': float(np.exp(beta[1])),
                 'odds_ratio_ci95': np.exp(beta[1]+np.array([-1, 1])*1.96*se),
                 'ses_slope_log_odds': float(beta[1]),
                 'note': 'Odds ratios describe odds, not probability ratios.', 'warnings': model_warnings[:5]}
        probs = []
        vecs = []
        for q in [.1, .5, .9]:
            value = float(d.ses.quantile(q))
            v = np.array([1., (value-d.ses.mean())/sd])
            eta = float(v @ beta)
            eta_se = np.sqrt(max(0., float(v @ cov @ v)))
            p = float(expit(eta))
            probs.append({'ses_percentile': int(q*100), 'ses': value, 'predicted_completion_probability': p,
                          'ci95': expit(eta+np.array([-1, 1])*1.96*eta_se)})
            vecs.append(v)
        p0, p1 = probs[0]['predicted_completion_probability'], probs[-1]['predicted_completion_probability']
        gradient = p1*(1-p1)*vecs[-1]-p0*(1-p0)*vecs[0]
        diff_se = np.sqrt(max(0., float(gradient @ cov @ gradient)))
        model['predictions'] = probs
        model['p90_minus_p10_percentage_points'] = 100*(p1-p0)
        model['p90_minus_p10_ci95_delta_percentage_points'] = 100*((p1-p0)+np.array([-1, 1])*1.96*diff_se)
        out['unadjusted_logistic_model'] = model
    except Exception as e:
        out['unadjusted_logistic_model'] = {'status': 'unavailable', 'reason': str(e)[:400]}
        limits.append('Logistic estimation failed; use the reported descriptive rates and contrasts.')
    out['interpretation'] = 'Assess association strength using the highest-lowest completion-rate difference, risk ratio, correlation, and logistic probability contrast, together with uncertainty. Positive contrasts indicate higher completion at higher SES; these are not causal effects.'
    return out

try:
    result = main()
except Exception as exc:
    result = {'status': 'error', 'reason': str(exc)[:1200], 'limitations': ['No association estimate is asserted after an input or analysis failure.']}
print(json.dumps(clean_json(result), separators=(',', ':'), allow_nan=False))