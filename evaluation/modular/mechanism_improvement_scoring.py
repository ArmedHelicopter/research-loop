"""Only replayed history-build-barrier-target chains can issue score inputs."""
from evaluation.modular.combination_scoring import _score_input_payload
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.mechanism_improvement_combination_driver import MechanismImprovementResult, verify_mechanism_improvement_cell
from research_loop.ontology import ContractError


def derive_mechanism_improvement_score_input(*,panel,result,**args):
    if type(result) is not MechanismImprovementResult: raise ContractError('exact state improvement result required')
    verified=verify_mechanism_improvement_cell(result,panel=panel,**args)
    if verified.data()['engineering_verified'] is not True or result.runtime.status!='succeeded':
        raise ContractError('state improvement requires a replayed successful target')
    return _score_input_payload(panel,result)


def issue_mechanism_improvement_score_input(*,authority,**args):
    if not isinstance(authority,LinkedExecutionAuthority): raise ContractError('execution authority required')
    return authority.issue(derive_mechanism_improvement_score_input(**args).data())
