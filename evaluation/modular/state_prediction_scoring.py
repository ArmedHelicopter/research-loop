"""Replay-gated score issuance for the three state/prediction TRAIN pairs."""
from evaluation.modular.combination_scoring import _score_input_payload
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.state_prediction_combination_driver import (
    StatePredictionCombinationResult, verify_state_prediction_combination_cell,
)
from research_loop.ontology import ContractError


def derive_state_prediction_score_input(*, panel, result, task, scenario, package, material,
        source_verifier, public_inputs, broker):
    """Issue no candidate until replay has reconstructed source and module state."""
    if not isinstance(result, StatePredictionCombinationResult):
        raise ContractError("state prediction scorer requires its exact driver result")
    verified = verify_state_prediction_combination_cell(result, panel=panel, task=task, scenario=scenario,
        package=package, material=material, source_verifier=source_verifier, public_inputs=public_inputs, broker=broker).data()
    if verified.get('engineering_verified') is not True or result.runtime.status != 'succeeded' or result.solver is None:
        raise ContractError("state prediction score requires a replayed successful execution")
    # Shared serializer hashes literal solver program, executed CSV receipt, and final candidate.
    return _score_input_payload(panel, result)


def issue_state_prediction_score_input(*, authority, **kwargs):
    if not isinstance(authority, LinkedExecutionAuthority):
        raise ContractError("state prediction score issuer requires execution authority")
    return authority.issue(derive_state_prediction_score_input(**kwargs).data())
