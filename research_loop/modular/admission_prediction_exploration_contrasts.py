"""Verified descriptive main, pair and triple terms for the required 16-cell slice."""
from itertools import combinations, product
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.ontology import ContractError

FACTORS=('M1','M4','M7')

def component_policy():
    coefficients={}
    for order in (1,2,3):
        for indices in combinations(range(3),order):
            coefficients['+'.join(FACTORS[i] for i in indices)]={''.join(map(str,bits)):
                (-1 if sum(bits[i] for i in indices)%2 != order%2 else 1)/(2**(3-order))
                for bits in product((0,1),repeat=3)}
    return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-components-v1','factors':list(FACTORS),
        'coefficients':coefficients,'group_weighting':'task_replicate_mean_then_equal_group_mean',
        'ci':{'level':0.95,'minimum_independent_groups':2,'method':'unavailable_in_one_group_per_benchmark_slice'},
        'missing_policy':'incomplete_reject','qualification_parity':'all_matched_arms_required'})


def estimate_components(panel,*,runtime,scorer_receipts,verifier):
    runtime=tuple(runtime);scores=tuple(scorer_receipts)
    if panel.acceptance_criteria.data().get('factorial_components')!=component_policy().data():
        raise ContractError('seven component policy must be frozen before execution')
    highest=estimate_grouped_contrast(panel,runtime=runtime,scorer_receipts=scores,verifier=verifier)
    if highest.data()['status']!='estimated':
        return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-estimate-v1','status':'not_identifiable',
            'components':{},'highest_order':highest.data(),'scientific_status':'not_measured'})
    values={s.cell_key:s.receipt.data()['body']['metric']['value'] for s in scores}
    benchmarks={}
    for benchmark in ('blade','discoverybench'):
        cells=[c for c in panel.cells if c.identity.benchmark==benchmark]
        if len(cells)!=8 or len({(c.identity.group_id,c.identity.task_id,c.replicate) for c in cells})!=1:
            raise ContractError('exact one frozen independent TRAIN task group per benchmark required')
        benchmarks[benchmark]={c.arm_id:values[c.key] for c in cells}
    components={name:{'status':'estimated','benchmark_estimates':{
        benchmark:{'mean':sum(weights[arm]*value for arm,value in arms.items()),'independent_groups':1,
            'confidence_interval':{'status':'not_estimable','reason':'insufficient_independent_groups','level':0.95,'lower':None,'upper':None}}
        for benchmark,arms in benchmarks.items()}} for name,weights in component_policy().data()['coefficients'].items()}
    return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-estimate-v1','status':'estimated',
        'highest_order':highest.data(),'components':components,'policy':component_policy().data(),
        'scientific_status':'descriptive_estimation_only_not_acceptance'})
