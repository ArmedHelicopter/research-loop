"""C4 score authority requires the complete original history/target replay."""
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.combination_scoring import _score_input_payload
from research_loop.modular.full_loo_controller import verify_full_loo_cell
from research_loop.ontology import ContractError


def issue_full_loo_score_input(*, authority, result, barrier, panel, ledger):
    if not isinstance(authority, LinkedExecutionAuthority):raise ContractError('C4 execution authority required')
    verify_full_loo_cell(result,barrier=barrier,panel=panel,ledger=ledger)
    return authority.issue(_score_input_payload(panel,result).data())
