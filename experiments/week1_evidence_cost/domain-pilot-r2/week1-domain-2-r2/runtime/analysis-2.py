import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm


def clean(obj):
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return round(float(obj), 6) if np.isfinite(obj) else None
    return obj


def describe(s):
    s = s.dropna()
    if s.empty:
        return {'n': 0}
    return {'n': len(s), 'first_year': int(s.index.min()),
            'last_year': int(s.index.max()), 'mean': s.mean(),
            'sd': s.std(), 'min': s.min(), 'max': s.max(),
            'first': s.iloc[0], 'last': s.iloc[-1]}


def fit(frame, trend=False):
    complete = frame.dropna().sort_index()
    if complete.empty:
        return {'status': 'no complete observations', 'n': 0}
    # HAC requires ordered, equally spaced observations: use a contiguous run.
    blocks = (complete.index.to_series().diff().ne(1)).cumsum()
    runs = [part for _, part in complete.groupby(blocks)]
    d = max(runs, key=len)
    report = {'n_complete': len(complete), 'n': len(d),
              'first_year': int(d.index.min()), 'last_year': int(d.index.max())}
    if len(d) < 10 or d['x'].std() <= 1e-12:
        return dict(report, status='insufficient observations or exposure variation')
    X = pd.DataFrame({'const': 1.0, 'x': d['x']}, index=d.index)
    if trend:
        X['year'] = d.index.to_numpy() - np.mean(d.index.to_numpy())
    if np.linalg.matrix_rank(X.to_numpy()) != X.shape[1]:
        return dict(report, status='rank deficient')
    lag = min(3, len(d) // 4)
    model = sm.OLS(d['y'], X).fit(cov_type='HAC', cov_kwds={'maxlags': lag}, use_t=True)
    ci = model.conf_int().loc['x']
    return dict(report, status='estimated', slope=model.params['x'],
                ci95=[ci.iloc[0], ci.iloc[1]], p_value=model.pvalues['x'],
                r_squared=model.rsquared, hac_lags=lag)


def main():
    base = Path('/input/data')
    if base.is_file():
        path = base
    else:
        path = base / 'worldbank_education_gdp.csv'
        if not path.is_file():
            files = sorted(base.glob('*.csv'))
            if len(files) != 1:
                raise ValueError('Expected the named CSV or exactly one CSV in /input/data')
            path = files[0]
    df = pd.read_csv(path, dtype=str, keep_default_na=True,
                     na_values=['..', '...', 'NA', 'N/A', 'null', 'None', '', '-', '—'])
    df.columns = df.columns.str.strip()
    keys = ['Country Group', 'Country Code', 'Series Name', 'Series Code']
    if not set(keys).issubset(df.columns):
        raise ValueError('Required identifier columns are missing')
    years = {}
    for c in df.columns:
        m = re.fullmatch(r'(\d{4})\s*\[YR(\d{4})\]', c)
        if m and m.group(1) == m.group(2):
            years[c] = int(m.group(1))
    if not years or len(set(years.values())) != len(years):
        raise ValueError('Missing or duplicate annual columns')
    for k in keys:
        df[k] = df[k].str.strip()
    blank_rows = df[keys].isna().all(axis=1)
    dropped = int(blank_rows.sum())
    df = df.loc[~blank_rows].copy()
    if df[keys].isna().any().any():
        raise ValueError('Partially missing series identifiers')
    if df.duplicated(['Country Group', 'Series Code']).any():
        raise ValueError('Duplicate group/indicator rows; aggregation would be ambiguous')
    inventory = df[['Series Code', 'Series Name']].drop_duplicates()
    labels = {}
    for code, rows in inventory.groupby('Series Code'):
        if len(rows) != 1:
            raise ValueError('Conflicting labels for an indicator code')
        labels[code] = rows.iloc[0]['Series Name']
    def verified(code, phrase):
        return code in labels and phrase in labels[code].lower()
    gdp = verified('NY.GDP.PCAP.KD', 'gdp per capita') and 'constant' in labels['NY.GDP.PCAP.KD'].lower()
    gni = verified('NY.GNP.PCAP.KD', 'gni per capita') and 'constant' in labels['NY.GNP.PCAP.KD'].lower()
    edu = verified('NY.ADJ.AEDU.GN.ZS', 'education expenditure') and 'gni' in labels['NY.ADJ.AEDU.GN.ZS'].lower()
    outcome = 'NY.GDP.PCAP.KD' if gdp else ('NY.GNP.PCAP.KD' if gni else None)
    limitations = [
        'Observational aggregate time series cannot establish causal impacts; reverse causality and omitted factors remain.',
        'Sub-Saharan Africa is a geographic aggregate; lower middle income is an income classification. Groups may overlap and are not independent country samples.',
        'Education expenditure as a share of GNI is not education expenditure as a share of total government expenditure or an absolute spending amount. Its denominator can induce association.',
        'Trends, structural changes, measurement error and changing group composition can affect associations. Differencing and HAC uncertainty do not establish causality.',
        'Models are exploratory and unadjusted for enrollment, labor participation and exports; reported intervals are pointwise, without multiplicity adjustment.',
        'Missing values are not interpolated. Each model uses its longest contiguous complete annual run; short runs have limited power.'
    ]
    if not gdp:
        limitations.insert(0, 'The expected GDP outcome is absent or not verified. Any GNI analysis is explicitly secondary and does not answer the GDP question.')
    report = {'status': 'planned analysis executed', 'rows': len(df),
              'blank_rows_dropped': dropped, 'years': [min(years.values()), max(years.values())],
              'indicator_labels': labels, 'gdp_outcome_verified': gdp,
              'outcome_code': outcome, 'exposure_code': 'NY.ADJ.AEDU.GN.ZS' if edu else None,
              'analysis_scope': 'GDP association with an alternative spending measure' if gdp else 'Secondary GNI association only; GDP question unresolved',
              'limitations': limitations, 'groups': []}
    if outcome is None or not edu:
        report['status'] = 'required analysis indicators unavailable or labels inconsistent'
        report['answer'] = 'No regional GDP impact can be determined.'
        return report
    long = df.melt(id_vars=keys, value_vars=list(years), var_name='year_column', value_name='raw')
    long['year'] = long['year_column'].map(years)
    raw = long['raw'].str.strip()
    values = pd.to_numeric(raw, errors='coerce')
    report['unrecognized_nonnumeric_cells'] = int((raw.notna() & values.isna()).sum())
    report['nonfinite_numeric_cells'] = int((values.notna() & ~np.isfinite(values)).sum())
    long['value'] = values.where(np.isfinite(values))
    report['handling'] = 'Known blank/sentinel tokens, unparseable values and infinities become missing. Negative export growth is retained; nonpositive income and negative education shares are excluded only from selected analysis series.'
    index = pd.Index(range(min(years.values()), max(years.values()) + 1), name='year')
    for group, sub in long.groupby('Country Group', sort=True):
        wide = sub.pivot(index='year', columns='Series Code', values='value').reindex(index)
        y = wide[outcome].copy() if outcome in wide else pd.Series(np.nan, index=index)
        x = wide['NY.ADJ.AEDU.GN.ZS'].copy() if 'NY.ADJ.AEDU.GN.ZS' in wide else pd.Series(np.nan, index=index)
        invalid_y, invalid_x = int((y <= 0).sum()), int((x < 0).sum())
        y = y.where(y > 0)
        x = x.where(x >= 0)
        paired = pd.DataFrame({'x': x, 'y': y}).dropna()
        level = pd.DataFrame({'x': x, 'y': 100 * np.log(y)})
        # Full annual indexing prevents differences from bridging missing years.
        change = pd.DataFrame({'x': x.diff(), 'y': 100 * np.log(y).diff()})
        lagged = pd.DataFrame({'x': x.diff().shift(1), 'y': 100 * np.log(y).diff()})
        correlations = {'pearson': None, 'spearman': None}
        if len(paired) >= 3 and paired['x'].nunique() > 1 and paired['y'].nunique() > 1:
            correlations = {'pearson': paired['x'].corr(paired['y']),
                            'spearman': paired['x'].corr(paired['y'], method='spearman')}
        primary = fit(change)
        sensitivity = fit(lagged)
        positive = change.dropna()
        inc = positive.loc[positive['x'] > 0, 'y']
        other = positive.loc[positive['x'] <= 0, 'y']
        finding = 'not estimable'
        if primary.get('status') == 'estimated':
            lo, hi = primary['ci95']
            finding = ('positive association with pointwise interval above zero' if lo > 0 else
                       'negative association with pointwise interval below zero' if hi < 0 else
                       'interval includes zero; direction uncertain')
        report['groups'].append({
            'group': group, 'country_codes': sorted(sub['Country Code'].unique().tolist()),
            'education_share': describe(x), 'income_per_capita': describe(y),
            'missing_education_years': int(x.isna().sum()), 'missing_income_years': int(y.isna().sum()),
            'excluded_negative_education': invalid_x, 'excluded_nonpositive_income': invalid_y,
            'paired_level_n': len(paired), 'level_correlations_descriptive': correlations,
            'primary_contemporaneous_changes': primary,
            'prior_year_education_change_sensitivity': sensitivity,
            'linear_time_trend_level_sensitivity': fit(level, trend=True),
            'years_with_education_share_increase': len(inc),
            'mean_income_log_growth_when_share_increased': inc.mean(),
            'years_without_share_increase': len(other),
            'mean_income_log_growth_without_share_increase': other.mean(),
            'growth_mean_difference': inc.mean() - other.mean(),
            'primary_association_assessment': finding})
    report['effect_units'] = 'Change-model slope: income growth in 100*log points per 1 percentage-point increase in education/GNI share. Trend-level slope: 100*log income points per 1 percentage-point higher share, conditional on linear year trend.'
    report['answer'] = ('Group-specific GDP associations are reported; causal positive impacts are not identified.' if gdp else
                        'Cannot identify regions with a positive GDP impact: verified data provide GNI rather than GDP. Group-specific secondary GNI associations are reported separately.')
    return report


try:
    result = clean(main())
except Exception as exc:
    result = {'status': 'analysis failed', 'error': str(exc)[:500],
              'answer': 'No regional impact conclusion established.'}
output = json.dumps(result, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
if len(output) >= 9000:
    result.pop('indicator_labels', None)
    for group in result.get('groups', []):
        group.pop('linear_time_trend_level_sensitivity', None)
    result['output_note'] = 'Indicator inventory and trend sensitivity omitted to respect output limit.'
    output = json.dumps(result, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
if len(output) >= 9000:
    output = json.dumps({'status': 'output limit exceeded', 'answer': result.get('answer'),
                         'limitations': result.get('limitations', [])}, separators=(',', ':'))
print(output)
