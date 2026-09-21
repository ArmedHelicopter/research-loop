import json
from pathlib import Path
import numpy as np
import pandas as pd


def analyze():
    base = Path('/input/data')
    path = base if base.is_file() else base / 'nls_incarceration_processed.csv'
    df = pd.read_csv(path)
    years = [1985, 1990, 1996]
    wealth_cols = [f'composite_wealth_{y}' for y in years]
    required = ['sex', 'ever_jailed'] + wealth_cols
    absent = [c for c in required if c not in df.columns]
    if absent:
        raise ValueError('Missing required columns: ' + ', '.join(absent))

    def labels(series):
        counts = series.astype('string').fillna('<missing>').value_counts(dropna=False)
        return {str(k): int(v) for k, v in counts.items()}

    sex = df['sex'].astype('string').str.strip().str.lower()
    jail = pd.to_numeric(df['ever_jailed'], errors='coerce')
    invalid_jail = df['ever_jailed'].notna() & (jail.isna() | ~jail.isin([0, 1]))
    invalid_sex = sex.notna() & ~sex.isin(['female', 'male'])
    if invalid_jail.any():
        raise ValueError('ever_jailed contains unexpected labels; expected numeric 0 or 1.')
    if invalid_sex.any():
        raise ValueError('sex contains unexpected labels; expected female or male.')

    selected = jail.eq(1)
    eligible = selected & sex.isin(['female', 'male'])
    wealth = pd.DataFrame(index=df.index)
    cleaning = {}
    for col in wealth_cols:
        values = pd.to_numeric(df[col], errors='coerce')
        finite = values.notna() & np.isfinite(values)
        cleaning[col] = {
            'source_missing': int(df[col].isna().sum()),
            'nonnumeric_nonmissing': int((df[col].notna() & values.isna()).sum()),
            'nonfinite_numeric': int((values.notna() & ~np.isfinite(values)).sum()),
            'negative_values_retained': int((finite & values.lt(0)).sum()),
            'zero_values_retained': int((finite & values.eq(0)).sum())
        }
        wealth[col] = values.where(finite)

    def summarize(mask):
        rows = []
        for year, col in zip(years, wealth_cols):
            row = {'year': year, 'groups': {}}
            for group in ['female', 'male']:
                group_mask = mask & sex.eq(group).fillna(False)
                values = wealth.loc[group_mask, col].dropna()
                n = len(values)
                row['groups'][group] = {
                    'n': int(n),
                    'missing_or_invalid_wealth': int(group_mask.sum() - n),
                    'median': float(values.median()) if n else None,
                    'q25': float(values.quantile(0.25)) if n else None,
                    'q75': float(values.quantile(0.75)) if n else None
                }
            female = row['groups']['female']['median']
            male = row['groups']['male']['median']
            gap = male - female if female is not None and male is not None else None
            row['male_minus_female_median'] = gap
            row['absolute_median_gap'] = abs(gap) if gap is not None else None
            rows.append(row)
        valid = [r for r in rows if r['absolute_median_gap'] is not None]
        maximum = max((r['absolute_median_gap'] for r in valid), default=None)
        winners = [r['year'] for r in valid if r['absolute_median_gap'] == maximum]
        return {
            'by_year': rows,
            'all_years_comparable': len(valid) == len(years),
            'highest_disparity_years': winners if len(valid) == len(years) else [],
            'maximum_absolute_median_gap': maximum if len(valid) == len(years) else None
        }

    primary = summarize(eligible)
    complete_mask = eligible & wealth.notna().all(axis=1)
    complete = summarize(complete_mask)
    winners = primary['highest_disparity_years']
    if winners:
        answer = 'Highest observed absolute female–male median wealth gap: ' + ', '.join(map(str, winners)) + ('.' if len(winners) == 1 else ' (tie).')
    else:
        answer = 'Cannot rank all three years: at least one year lacks usable wealth for one sex group.'
    return {
        'status': 'ok',
        'question': 'In what year were gender disparities highest in median wealth among individuals who were ever incarcerated?',
        'definition': 'Absolute difference between male and female median composite wealth, among ever_jailed == 1, compared across 1985, 1990 and 1996.',
        'answer': answer,
        'sample_counts': {
            'total_rows': int(len(df)),
            'raw_sex_labels': labels(df['sex']),
            'raw_ever_jailed_labels': labels(df['ever_jailed']),
            'ever_jailed_1': int(selected.sum()),
            'missing_incarceration_indicator': int(jail.isna().sum()),
            'incarcerated_missing_sex': int((selected & sex.isna()).sum()),
            'eligible_female': int((eligible & sex.eq('female').fillna(False)).sum()),
            'eligible_male': int((eligible & sex.eq('male').fillna(False)).sum()),
            'complete_wealth_all_years': int(complete_mask.sum())
        },
        'cleaning': cleaning,
        'primary_available_case_analysis': primary,
        'sensitivity_same_complete_case_sample': complete,
        'limitations': [
            'Descriptive observational association, not evidence that incarceration or sex causes wealth differences.',
            'Incarceration means ever jailed during 1985–1994; it does not establish incarceration timing relative to each wealth measurement.',
            'Negative wealth and zeros are retained: debt can produce negative wealth, and no sentinel codes are documented. Undocumented sentinel contamination cannot be excluded.',
            'Comparisons use supplied wealth units; inflation adjustment and comparability of the composite across years are undocumented.',
            'Results are unweighted sample summaries; survey weights, sampling design and potential confounders are not supplied.',
            'The ranking describes observed median gaps without a significance test or population uncertainty estimate.',
            'Gender disparities are operationalized using the recorded binary sex labels; absolute gaps may rank years differently from relative disparities.'
        ]
    }


try:
    result = analyze()
except Exception as exc:
    result = {'status': 'error', 'error': str(exc), 'conclusion': 'No result established.'}
print(json.dumps(result, separators=(',', ':'), ensure_ascii=True, allow_nan=False))
