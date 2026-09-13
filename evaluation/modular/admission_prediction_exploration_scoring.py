"""Replay-gated score issuance for the exact admission/prediction/exploration TRAIN triple."""
from evaluation.modular.combination_scoring import _score_input_payload
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.admission_prediction_exploration_driver import AdmissionPredictionExplorationResult, verify_admission_prediction_exploration_cell
from research_loop.ontology import ContractError


def derive_admission_prediction_exploration_score_input(*, panel, result, **args):
    if type(result) is not AdmissionPredictionExplorationResult:
        raise ContractError('admission prediction exploration scorer requires its exact driver result')
    verified = verify_admission_prediction_exploration_cell(result, panel=panel, **args).data()
    if verified.get('engineering_verified') is not True or result.runtime.status != 'succeeded' or result.solver is None:
        raise ContractError('admission prediction exploration scoring requires a replayed successful execution')
    return _score_input_payload(panel, result)


def issue_admission_prediction_exploration_score_input(*, authority, **args):
    if not isinstance(authority, LinkedExecutionAuthority):
        raise ContractError('admission prediction exploration score issuer requires execution authority')
    return authority.issue(derive_admission_prediction_exploration_score_input(**args).data())
