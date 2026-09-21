"""Offline independent recomputation of frozen TRAIN outputs; never runs archived code.

CSV parsing, quantiles, counts, correlations: Python standard library.
Regression: direct score equations / normal equations and sandwich covariance.
NumPy supplies linear algebra only; SciPy supplies Student-t CDF/quantile only.
No pandas, statsmodels, project modules, subprocesses, model clients or network.
"""
import argparse
import bisect
import collections
import csv
import hashlib
import io
import json
import math
import platform
import re
import statistics as st
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import t

CHECKS = []
READS = {}
ATOL = 5.1e-7  # Archived rich/WB outputs round to six decimal places.


def read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    READS[str(path)] = hashlib.sha256(raw).hexdigest()
    return raw


def load(path):
    return json.loads(read(path))


def check(label, actual, expected):
    if isinstance(expected, bool) or expected is None:
        ok = actual == expected
    elif isinstance(expected, (float, int)) and isinstance(actual, (float, int)):
        # Counts must agree exactly. Float tolerance is fixed before recomputation.
        ok = actual == expected if isinstance(expected, int) else math.isclose(actual, expected, rel_tol=1e-10, abs_tol=ATOL)
    else:
        ok = actual == expected
    CHECKS.append(dict(path=label, recomputed=actual, archived=expected, passed=bool(ok)))


def compare(label, actual, expected):
    """Compare every leaf explicitly present in recomputed subset; never copy expected values."""
    if isinstance(actual, dict):
        for key, value in actual.items():
            if key not in expected:
                check(label + '/' + key, 'missing archived key', 'present')
            else:
                compare(label + '/' + key, value, expected[key])
    elif isinstance(actual, list):
        check(label + '/length', len(actual), len(expected))
        for i, (value, saved) in enumerate(zip(actual, expected)):
            compare(label + '/' + str(i), value, saved)
    else:
        check(label, actual, expected)


def quantile(values, p):
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    left = math.floor(position)
    right = math.ceil(position)
    return ordered[left] + (position - left) * (ordered[right] - ordered[left])


def corr(a, b):
    am, bm = st.mean(a), st.mean(b)
    return math.fsum((x-am)*(y-bm) for x, y in zip(a, b)) / math.sqrt(
        math.fsum((x-am)**2 for x in a) * math.fsum((y-bm)**2 for y in b))


def ranks(values):
    ordered = sorted(values)
    return [(bisect.bisect_left(ordered, x) + bisect.bisect_right(ordered, x) + 1)/2 for x in values]


def wilson(k, n):
    z = st.NormalDist().inv_cdf(.975)
    p, d = k/n, 1 + z*z/n
    center = (p + z*z/(2*n))/d
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return [center-half, center+half]


def logistic(x, y):
    mean, sd = st.mean(x), st.stdev(x)
    design = np.array([[1., (v-mean)/sd] for v in x])
    outcomes = np.array(y)
    beta = np.array([math.log(st.mean(y)/(1-st.mean(y))), 0.])
    for iteration in range(50):
        p = 1/(1+np.exp(-(design @ beta)))
        information = design.T @ ((p*(1-p))[:, None] * design)
        score = design.T @ (outcomes-p)
        step = np.linalg.solve(information, score)
        beta += step
        if max(abs(step)) < 1e-12:
            break
    else:
        raise RuntimeError('Independent logistic solver did not converge')
    p = 1/(1+np.exp(-(design @ beta)))
    bread = np.linalg.inv(design.T @ ((p*(1-p))[:, None] * design))
    scores = design * (outcomes-p)[:, None]
    covariance = bread @ (scores.T @ scores) @ bread
    score_norm = float(max(abs(design.T @ (outcomes-p))))
    if score_norm > 1e-8:
        raise RuntimeError('Logistic score equations not satisfied')
    return beta, covariance, dict(iterations=iteration+1, score_max_abs=score_norm, mean=mean, sd=sd)


def outputs(base, run):
    folder = base / run
    request = load(folder/'final/request.json')
    response = load(folder/'final/response.json')
    for path in sorted((folder/'runtime').glob('analysis-*.py')):
        read(path)  # Hash for provenance only; never execute or import.
    feedback = request['execution_feedback']
    for item in feedback:
        if item['status'] != 'succeeded':
            raise ValueError('Selected completed flow contains failed execution')
    return [json.loads(item['stdout']) for item in feedback], response


def audit_ses(rows, base):
    labels = dict(collections.Counter(r['BA DEGREE COMPLETED'] for r in rows))
    if set(labels) != {'True', 'False'}:
        raise ValueError('Observed BA vocabulary differs from frozen data assumption')
    if any(not r['SES'] or not math.isfinite(float(r['SES'])) for r in rows):
        raise ValueError('SES incomplete; explicitly revise review rather than silently drop rows')
    x = [float(r['SES']) for r in rows]
    y = [int(r['BA DEGREE COMPLETED'] == 'True') for r in rows]
    n, k = len(y), sum(y)
    missing_cells = {c: sum(not r[c].strip() for r in rows) for c in rows[0]}
    duplicate_ids = n - len(set(r['CASE ID'] for r in rows))
    beta, cov, solver = logistic(x, y)
    se, odds = math.sqrt(cov[1, 1]), math.exp(beta[1])
    cuts = [quantile(x, p) for p in (.25, .5, .75)]
    low = [yi for xi, yi in zip(x, y) if xi <= cuts[0]]
    high = [yi for xi, yi in zip(x, y) if xi >= cuts[2]]
    groups = [[yi for xi, yi in zip(x, y) if bisect.bisect_left(cuts, xi) == g] for g in range(4)]
    primary = dict(sample_n=n, ba_rate=100*k/n, low_rate=100*st.mean(low), high_rate=100*st.mean(high),
                   rate_gap=100*(st.mean(high)-st.mean(low)), ses_ba_r=corr(x, y), ses_or=odds,
                   ses_or_ci=[math.exp(beta[1]-st.NormalDist().inv_cdf(.975)*se), math.exp(beta[1]+st.NormalDist().inv_cdf(.975)*se)])
    qualification = dict(sample_n=n, **{f'q{i+1}_rate': 100*st.mean(g) for i, g in enumerate(groups)},
                         quartile_gap=100*(st.mean(groups[3])-st.mean(groups[0])))
    rich, final = outputs(base, 'domain-rich-r2/week1-rich-domain-1-r2')
    for phase, actual, saved in [('primary', primary, rich[1]), ('qualification', qualification, rich[2])]:
        expected = {f['key']: f['value'] for f in saved['facts']}
        check('ses_rich/'+phase+'/fact_keys', sorted(actual), sorted(expected))
        if phase == 'primary':
            expected['ses_or_ci'] = json.loads(expected['ses_or_ci'])
        compare('ses_rich/'+phase, actual, expected)
    for i, (computed, fact) in enumerate(zip(groups, rich[2]['facts'][1:5])):
        check(f'ses_rich/q{i+1}/population_n', len(computed), int(re.search(r'n=(\d+)', fact['population']).group(1)))
        check(f'ses_rich/q{i+1}/successes', sum(computed), int(re.search(r'successes=(\d+)', fact['method']).group(1)))
    for name, vals in [('low_rate', low), ('high_rate', high)]:
        fact = next(f for f in rich[1]['facts'] if f['key'] == name)
        check('ses_rich/'+name+'/population_n', len(vals), int(re.search(r'n=(\d+)', fact['population']).group(1)))
    compare('ses_rich/profile', {'rows': n}, rich[0])
    for col, missing in missing_cells.items():
        check('ses_rich/profile/'+col+'/missing', missing, rich[0]['columns'][col or 'Unnamed: 0']['missing'])
    # Reconstruct the short SES workflow separately: quintiles, Wilson/Newcombe, model predictions.
    short, _ = outputs(base, 'domain-pilot-r3/week1-domain-1-r3')
    quintile_edges = [quantile(x, p/5) for p in range(6)]
    quintiles = []
    for g in range(5):
        pairs = [(a, b) for a, b in zip(x, y) if bisect.bisect_left(quintile_edges[1:-1], a) == g]
        xs, ys = zip(*pairs)
        quintiles.append(dict(group_low_to_high=g+1, n=len(ys), completed=sum(ys), ses_min=min(xs), ses_max=max(xs),
                              ses_mean=st.mean(xs), completion_rate=st.mean(ys), completion_rate_ci95_wilson=wilson(sum(ys), len(ys))))
    lo, hi = quintiles[0], quintiles[-1]
    pl, ph = lo['completion_rate'], hi['completion_rate']
    ll, ul = lo['completion_rate_ci95_wilson']
    lh, uh = hi['completion_rate_ci95_wilson']
    diff, rr = ph-pl, ph/pl
    rrse = math.sqrt(1/hi['completed']-1/hi['n']+1/lo['completed']-1/lo['n'])
    contrast = dict(completion_difference_percentage_points=100*diff,
                    difference_ci95_newcombe_percentage_points=[100*(diff-math.sqrt((ph-lh)**2+(ul-pl)**2)), 100*(diff+math.sqrt((uh-ph)**2+(pl-ll)**2))],
                    completion_risk_ratio=rr, risk_ratio_ci95_log=[rr*math.exp(-1.96*rrse), rr*math.exp(1.96*rrse)])
    predictions, vectors = [], []
    for percentile in (10, 50, 90):
        value = quantile(x, percentile/100)
        vector = np.array([1., (value-st.mean(x))/st.stdev(x)])
        eta, eta_se = float(vector@beta), math.sqrt(float(vector@cov@vector))
        sigmoid = lambda a: 1/(1+math.exp(-a))
        predictions.append(dict(ses_percentile=percentile, ses=value, predicted_completion_probability=sigmoid(eta),
                                ci95=[sigmoid(eta-1.96*eta_se), sigmoid(eta+1.96*eta_se)]))
        vectors.append(vector)
    p0, p1 = [predictions[i]['predicted_completion_probability'] for i in (0, 2)]
    gradient = p1*(1-p1)*vectors[2]-p0*(1-p0)*vectors[0]
    diffse = math.sqrt(float(gradient@cov@gradient))
    reconstructed = dict(counts=dict(input_rows=n, analyzed_rows=n, excluded_rows=0, missing_outcome=0,
                                     missing_or_invalid_ses=0, duplicate_nonmissing_case_ids=duplicate_ids),
        overall=dict(completed=k, not_completed=n-k, completion_rate=k/n, completion_rate_ci95_wilson=wilson(k,n),
                     ses_mean=st.mean(x), ses_sd=st.stdev(x), ses_quantiles={str(p):quantile(x,p) for p in [0,.1,.25,.5,.75,.9,1]}),
        ses_quintiles=dict(cut_edges=quintile_edges, groups=quintiles), highest_lowest_contrast=contrast,
        point_biserial_correlation=corr(x,y), unadjusted_logistic_model=dict(n=n, odds_ratio_per_ses_sd=odds,
            odds_ratio_ci95=[math.exp(beta[1]-1.96*se),math.exp(beta[1]+1.96*se)], ses_slope_log_odds=float(beta[1]),
            predictions=predictions, p90_minus_p10_percentage_points=100*(p1-p0),
            p90_minus_p10_ci95_delta_percentage_points=[100*(p1-p0-1.96*diffse),100*(p1-p0+1.96*diffse)]))
    compare('ses_short', reconstructed, short[1])
    boundary = [yi for xi,yi in zip(x,y) if xi == cuts[2]]
    return dict(labels=labels, missing_cells=missing_cells, duplicate_ids=duplicate_ids, primary=primary,
        quartile_cutpoints=cuts, quartile_groups=[dict(n=len(g), completed=sum(g), percent=100*st.mean(g)) for g in groups],
        q75_boundary=dict(n=len(boundary), completed=sum(boundary)), qualification=qualification,
        short=reconstructed, solver=solver,
        scope='Supplied processed CSV and public metadata only; original NLS construction, weights and sentinel provenance not established.')


def audit_incarceration(rows, base):
    if set(r['sex'] for r in rows) != {'female','male'} or set(r['ever_jailed'] for r in rows) != {'0','1'}:
        raise ValueError('Unexpected observed incarceration labels')
    years = [1985,1990,1996]
    cols = [f'composite_wealth_{yr}' for yr in years]
    # Frozen CSV is complete: fail if this premise changes, rather than add an unreviewed cleaning policy.
    if any(not r[c] or not math.isfinite(float(r[c])) for r in rows for c in cols):
        raise ValueError('Missing/nonfinite wealth requires explicit review')
    selected = [r for r in rows if r['ever_jailed']=='1']
    counts = dict(total_rows=len(rows), raw_sex_labels=dict(collections.Counter(r['sex'] for r in rows)),
                  raw_ever_jailed_labels=dict(collections.Counter(r['ever_jailed'] for r in rows)), ever_jailed_1=len(selected),
                  missing_incarceration_indicator=0, incarcerated_missing_sex=0,
                  eligible_female=sum(r['sex']=='female' for r in selected), eligible_male=sum(r['sex']=='male' for r in selected),
                  complete_wealth_all_years=len(selected))
    cleaning = {c:dict(source_missing=0,nonnumeric_nonmissing=0,nonfinite_numeric=0,
                      negative_values_retained=sum(float(r[c])<0 for r in rows),zero_values_retained=sum(float(r[c])==0 for r in rows)) for c in cols}
    summaries=[]
    for year,col in zip(years,cols):
        groups={}
        for sex in ('female','male'):
            vals=[float(r[col]) for r in selected if r['sex']==sex]
            groups[sex]=dict(n=len(vals),missing_or_invalid_wealth=0,median=st.median(vals),q25=quantile(vals,.25),q75=quantile(vals,.75))
        gap=groups['male']['median']-groups['female']['median']
        summaries.append(dict(year=year,groups=groups,male_minus_female_median=gap,absolute_median_gap=abs(gap)))
    maxgap=max(s['absolute_median_gap'] for s in summaries)
    result=dict(by_year=summaries,all_years_comparable=True,highest_disparity_years=[s['year'] for s in summaries if s['absolute_median_gap']==maxgap],maximum_absolute_median_gap=maxgap)
    expected,_=outputs(base,'domain-pilot-r2/week1-domain-3-r2')
    reconstructed=dict(sample_counts=counts,cleaning=cleaning,primary_available_case_analysis=result,sensitivity_same_complete_case_sample=result)
    compare('incarceration',reconstructed,expected[1])
    return reconstructed


def ols_hac(records, trend=False):
    if not records:
        return dict(status='no complete observations',n=0)
    blocks=[]
    for record in sorted(records):
        if not blocks or record[0] != blocks[-1][-1][0]+1:
            blocks.append([])
        blocks[-1].append(record)
    run=max(blocks,key=len)
    years,x,y=zip(*run)
    n=len(run)
    result=dict(n_complete=len(records),n=n,first_year=years[0],last_year=years[-1])
    if n<10 or st.stdev(x)<=1e-12:
        return dict(result,status='insufficient observations or exposure variation')
    X=np.array([[1.,xi,yr-st.mean(years)] if trend else [1.,xi] for yr,xi,_ in run])
    y=np.array(y)
    bread=np.linalg.inv(X.T@X)
    beta=np.linalg.solve(X.T@X,X.T@y)
    residual=y-X@beta
    scores=X*residual[:,None]
    meat=scores.T@scores
    lag=min(3,n//4)
    for shift in range(1,lag+1):
        cross=scores[shift:].T@scores[:-shift]
        meat+=(1-shift/(lag+1))*(cross+cross.T)
    cov=bread@meat@bread  # No finite-sample correction, matching declared HAC default.
    se=math.sqrt(cov[1,1]); df=n-X.shape[1]
    critical=float(t.ppf(.975,df))
    if float(max(abs(X.T@residual)))>1e-6:
        raise RuntimeError('OLS normal equations not satisfied')
    return dict(result,status='estimated',slope=float(beta[1]),ci95=[float(beta[1]-critical*se),float(beta[1]+critical*se)],
                p_value=float(2*t.sf(abs(beta[1]/se),df)),r_squared=float(1-(residual@residual)/sum((y-st.mean(y))**2)),hac_lags=lag)


def audit_worldbank(rows,base):
    expected,_=outputs(base,'domain-pilot-r2/week1-domain-2-r2')
    saved=expected[1]
    years={int(re.match(r'(\d{4})',c)[1]):c for c in rows[0] if re.fullmatch(r'(\d{4}) \[YR\1\]',c)}
    labels={r['Series Code']:r['Series Name'] for r in rows}
    if len({(r['Country Group'],r['Series Code']) for r in rows})!=len(rows):
        raise ValueError('Duplicate World Bank series')
    compare('worldbank',dict(rows=len(rows),blank_rows_dropped=0,years=[min(years),max(years)],
                             indicator_labels=labels,gdp_outcome_verified='NY.GDP.PCAP.KD' in labels),saved)
    groups=[]
    def series(group,code):
        row=next(r for r in rows if r['Country Group']==group and r['Series Code']==code)
        return {yr:float(row[col]) for yr,col in years.items() if row[col].strip()}
    def describe(s):
        vals=list(s.values()); yrs=sorted(s)
        return dict(n=len(vals),first_year=yrs[0],last_year=yrs[-1],mean=st.mean(vals),sd=st.stdev(vals),min=min(vals),max=max(vals),first=s[yrs[0]],last=s[yrs[-1]])
    for name in sorted({r['Country Group'] for r in rows}):
        x=series(name,'NY.ADJ.AEDU.GN.ZS'); y=series(name,'NY.GNP.PCAP.KD')
        if any(v<0 for v in x.values()) or any(v<=0 for v in y.values()):
            raise ValueError('Unexpected nonpositive income/negative education')
        paired=sorted(x.keys()&y.keys())
        dx={yr:x[yr]-x[yr-1] for yr in x if yr-1 in x}
        dy={yr:100*math.log(y[yr]/y[yr-1]) for yr in y if yr-1 in y}
        changes=[(yr,dx[yr],dy[yr]) for yr in sorted(dx.keys()&dy.keys())]
        lagged=[(yr,dx[yr-1],dy[yr]) for yr in sorted(dy) if yr-1 in dx]
        inc=[v for _,change,v in changes if change>0]; other=[v for _,change,v in changes if change<=0]
        g=dict(group=name,country_codes=sorted({r['Country Code'] for r in rows if r['Country Group']==name}),
               education_share=describe(x),income_per_capita=describe(y),missing_education_years=len(years)-len(x),missing_income_years=len(years)-len(y),
               excluded_negative_education=0,excluded_nonpositive_income=0,paired_level_n=len(paired),
               level_correlations_descriptive=dict(pearson=corr([x[yr] for yr in paired],[y[yr] for yr in paired]),spearman=corr(ranks([x[yr] for yr in paired]),ranks([y[yr] for yr in paired]))),
               primary_contemporaneous_changes=ols_hac(changes),prior_year_education_change_sensitivity=ols_hac(lagged),
               linear_time_trend_level_sensitivity=ols_hac([(yr,x[yr],100*math.log(y[yr])) for yr in paired],True),
               years_with_education_share_increase=len(inc),mean_income_log_growth_when_share_increased=st.mean(inc) if inc else None,
               years_without_share_increase=len(other),mean_income_log_growth_without_share_increase=st.mean(other) if other else None,
               growth_mean_difference=st.mean(inc)-st.mean(other) if inc and other else None)
        groups.append(g)
    compare('worldbank/groups',groups,saved['groups'])
    return dict(groups=groups,indicator_labels=labels,question_answerable_as_causal_GDP=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True,help='Frozen week1 worktree')
    parser.add_argument('--output',type=Path,required=True,help='New JSON path; exclusive creation')
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Never overwrite an audit receipt')
    base=args.source/'experiments/week1_evidence_cost'
    index=load(base/'qualification/r4/public-index.json')
    datasets={}
    for item in index:
        if item['identity']['domain']!='train':
            raise ValueError('Only preassigned TRAIN exports allowed')
        for key in ('csv','public'):
            raw=read(item[key+'_path'])
            if hashlib.sha256(raw).hexdigest()!=item[key+'_sha256']:
                raise ValueError('Frozen input hash mismatch')
        datasets[item['identity']['task_id'].split(':')[-1]]=list(csv.DictReader(io.StringIO(read(item['csv_path']).decode('utf-8-sig'))))
    results=dict(ses=audit_ses(datasets['nls_ses'],base),incarceration=audit_incarceration(datasets['nls_incarceration'],base),
                 worldbank=audit_worldbank(datasets['worldbank_education_gdp'],base))
    andgap=load(base/'S-native-r1/and-capability-gap.json')
    check('native_AND/representation_available',andgap['representation_available'],False)
    check('native_AND/withdrawal_retains_alternative',andgap['after_withdrawing_a']['status'],'supported')
    for filename in ('MENTOR-DECISION.md','STATUS.md','FINAL-SYNTHESIS.json','FINAL-VERIFICATION.json','check_version_cache.py'):
        read(base/filename)
    changed=[p for p,h in READS.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
    if changed:
        raise RuntimeError('Inputs changed during audit: '+repr(changed))
    failures=[c for c in CHECKS if not c['passed']]
    result=dict(schema='independent-existing-train-recomputation-v1',source_commit='052b874b',
                runtime=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__),
                scope=dict(independent_tasks=3,completed_workflows_recomputed=4,rich_facts=14,new_model_calls=0,
                           core_modified=False,formal_VAL_labels_read=False,independent_human_review=False,
                           independence='Separate implementation by reviewing agent; no archived analysis executed, imported or reused.'),
                tolerance=dict(float_absolute=ATOL,float_relative=1e-10,integers='exact'),results=results,
                checks=CHECKS,check_count=len(CHECKS),failures=failures,all_selected_checks_passed=not failures,
                input_sha256=READS,input_bytes_unchanged=True,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                limitations=['Recomputation validates stated arithmetic on supplied processed data, not causal identification or original cohort preprocessing.',
                             'Final prose and measurement definitions are reviewed separately in REVIEW.md; comparisons here are not independent scientific tasks.',
                             'Previous failed rich run is retained; this audit does not rehabilitate it or score official benchmark answers.',
                             'Native AND check reads the preserved counterexample; it is not a new core test run.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as out:
        json.dump(result,out,ensure_ascii=False,indent=2,allow_nan=False)
        out.write('\n')
    print(json.dumps(dict(check_count=len(CHECKS),failure_count=len(failures),failures=failures,output=str(args.output)),ensure_ascii=False))
    return 1 if failures else 0


if __name__=='__main__':
    sys.exit(main())
