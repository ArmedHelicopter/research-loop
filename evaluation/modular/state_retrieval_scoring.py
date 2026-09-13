"""Replay-gated score issuance for the exact state/retrieval TRAIN family."""
from evaluation.modular.combination_scoring import _score_input_payload
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.state_retrieval_combination_driver import StateRetrievalResult, verify_state_retrieval_cell
from research_loop.ontology import ContractError


def derive_state_retrieval_score_input(*, panel, result, **args):
    if type(result) is not StateRetrievalResult:
        raise ContractError('state retrieval scorer requires its exact driver result')
    verified = verify_state_retrieval_cell(result, panel=panel, **args).data()
    if verified.get('engineering_verified') is not True or result.runtime.status != 'succeeded' or result.solver is None:
        raise ContractError('state retrieval scoring requires a replayed successful execution')
    return _score_input_payload(panel, result)


def issue_state_retrieval_score_input(*, authority, **args):
    if not isinstance(authority, LinkedExecutionAuthority):
        raise ContractError('state retrieval score issuer requires execution authority')
    return authority.issue(derive_state_retrieval_score_input(**args).data())
