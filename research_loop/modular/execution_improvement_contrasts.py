"""Descriptive factorial effects after exact independent score verification."""
from collections import defaultdict
from itertools import combinations, product
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def component_policy():
    from research_loop.modular.execution_improvement_panel import DESIGNS
    designs={}
    for name,factors in DESIGNS.items():
        n=len(factors);coefficients={}
        for size in range(1,n+1):
            for indices in combinations(range(n),size):
                coefficients['+'.join(factors[i] for i in indices)]={''.join(map(str,bits)):
                    (-1)**sum(bits[i]==0 for i in indices)/(2**(n-size)) for bits in product((0,1),repeat=n)}
        designs[name]={'factors':list(factors),'coefficients':coefficients}
    return FrozenRecord.from_dict({'schema':'execution-improvement-components-v1','designs':designs,
        'normalization':'average_over_noncomponent_factors_difference_in_differences',
        'group_weighting':'task_replicate_mean_then_equal_group_mean','missing_policy':'incomplete_reject',
        'confidence_interval':{'level':.95,'minimum_independent_groups':2,'method':'unavailable_in_one_group_per_benchmark_slice'}})


def estimate_execution_contrast(panel,*,runtime,scorer_receipts,verifier):
    policy=component_policy()
    if panel.acceptance_criteria.data().get('factorial_components')!=policy.data():
        raise ContractError('component coefficients must be frozen before execution')
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
            coefficients=policy.data()['designs'][panel.obligation_id]['coefficients']['+'.join(factors[i] for i in indices)]
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
        'normalized_descriptive_terms':terms,'normalization':policy.data()['normalization'],'component_policy':policy.data(),
        'conditional_background':['M2'],'candidate_allocation':'shared_within_design_at_fixed_M9_level',
        'confidence_interval':None})
