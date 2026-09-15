"""Regression for partial signed headless lineage closures at the outer gate."""
from types import SimpleNamespace
import uuid

from evaluation.modular.lineage_scorer_process import _LINEAGE_FINALIZE_REQUEST_SCHEMA
from research_loop.modular.lineage_combination_controller import _finalize_headless_lineage_gate
from research_loop.modular.contracts import FrozenRecord

from test_headless_lineage_closure import _score_one


class _WorkerAdapter:
    """Use the real worker RPC surface without starting a second process."""
    def __init__(self, *, worker, panel, service):
        self.worker = worker
        self.panel = panel
        self.config = service.config
        self.reference_binding = service.lineage_reference_binding
        self.evaluator_provider = service.evaluator_provider

    def usage(self):
        return self.worker.respond({'schema': 'lineage-scorer-usage-request-v1',
                                    'nonce': uuid.uuid4().hex})

    def finalize_lineage(self, *, nonce, receipt_digests):
        response = self.worker.respond({'schema': _LINEAGE_FINALIZE_REQUEST_SCHEMA, 'nonce': nonce,
            'receipt_digests': receipt_digests, 'evaluator_provider': self.evaluator_provider})
        return FrozenRecord.from_dict(response['closure'])


def test_partial_signed_native_closure_is_inconclusive_but_retains_known_main_evidence(tmp_path, monkeypatch):
    """One real synthetic native call cannot close the panel's remaining cells."""
    patch, panel, service, worker, _, scored = _score_one(tmp_path, monkeypatch)
    try:
        client = _WorkerAdapter(worker=worker, panel=panel, service=service)
        pool = SimpleNamespace(clients={panel.obligation_id: client},
            evaluator_usage_by_obligation={panel.obligation_id: service.lineage_reference_binding['evaluator_usage']},
            evaluator_providers_by_obligation={panel.obligation_id: service.evaluator_provider})
        row = {'cell': panel.cells[0].data(), 'status': 'succeeded', 'scorer_receipt': scored['receipt']}
        gate = _finalize_headless_lineage_gate(panels=(panel,), journal_cells=[row], scoring_service=pool,
            scorer_authority_keys={service._authority.authority_id: service._authority.key})
    finally:
        patch.undo()
    entry = gate['panels'][0]
    assert entry['authenticated_usage']['body']['tokens'] == 10
    assert entry['native_MAIN_known_tokens_lower_bound'] == 10
    assert entry['closure']['body']['scope']['unscored_cell_count'] == len(panel.cells) - 1
    assert gate['status'] == entry['status'] == 'inconclusive'
