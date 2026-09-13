"""Replay-gated score issuance for the exact mechanism/exploration TRAIN family."""
from evaluation.modular.combination_scoring import _score_input_payload
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.mechanism_exploration_combination_driver import MechanismExplorationResult, verify_mechanism_exploration_cell
from research_loop.ontology import ContractError


def derive_mechanism_exploration_score_input(*, panel, result, **args):
    if type(result) is not MechanismExplorationResult:
        raise ContractError('mechanism exploration scorer requires its exact driver result')
    verified = verify_mechanism_exploration_cell(result, panel=panel, **args).data()
    if verified.get('engineering_verified') is not True or result.runtime.status != 'succeeded' or result.solver is None:
        raise ContractError('mechanism exploration scoring requires a replayed successful execution')
    return _score_input_payload(panel, result)


def issue_mechanism_exploration_score_input(*, authority, **args):
    if not isinstance(authority, LinkedExecutionAuthority):
        raise ContractError('mechanism exploration score issuer requires execution authority')
    return authority.issue(derive_mechanism_exploration_score_input(**args).data())
