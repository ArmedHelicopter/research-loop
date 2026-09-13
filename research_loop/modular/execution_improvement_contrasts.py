"""Descriptive factorial effects after exact independent score verification."""
from collections import defaultdict
from itertools import combinations
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def estimate_execution_contrast(panel,*,runtime,scorer_receipts,verifier):
    runtime=tuple(runtime);scorer_receipts=tuple(scorer_receipts)
    base=estimate_grouped_contrast(panel,runtime=runtime,scorer_receipts=scorer_receipts,verifier=verifier)
    if base.data()['status']!='estimated':return base
    factors=panel.design.data()['factors'];n=len(factors)
    scores={r.cell_key:r.receipt.data() for r in scorer_receipts}
    tasks=defaultdict(dict)
    for c in panel.cells:
        body=scores[c.key];body=body['body'] if 'body' in body else body
        tasks[(c.identity.benchmark,c.identity.group_id,c.identity.task_id,c.replicate)][c.arm_id]=body['metric']['value']
    terms={}
    for size in range(1,n+1):
        for indices in combinations(range(n),size):
            coefficients={row['id']:((-1)**sum(row['id'][i]=='0' for i in indices))/(2**(n-1))
                for row in panel.design.data()['cells']}
            groups=defaultdict(list)
            for (benchmark,group,task,replicate),values in tasks.items():
                if set(values)!=set(coefficients):raise ContractError('complete factorial denominator required')
                groups[(benchmark,group)].append(sum(coefficients[arm]*value for arm,value in values.items()))
            benchmarks=defaultdict(list)
            for (benchmark,group),values in groups.items():benchmarks[benchmark].append(sum(values)/len(values))
            terms['+'.join(factors[i] for i in indices)]={'coefficients':coefficients,
                'benchmark_estimates':{benchmark:{'independent_groups':len(values),'mean':sum(values)/len(values),
                    'confidence_interval':None,'uncertainty_status':'descriptive_no_frozen_inference'} for benchmark,values in benchmarks.items()}}
    return FrozenRecord.from_dict({**base.data(),'schema':'execution-improvement-factorial-estimate-v1',
        'normalized_descriptive_terms':terms,'normalization':'sum_signed_cell_means_divided_by_2_power_n_minus_1',
        'conditional_background':['M2'],'candidate_allocation':'shared_within_design_at_fixed_M9_level',
        'confidence_interval':None})
