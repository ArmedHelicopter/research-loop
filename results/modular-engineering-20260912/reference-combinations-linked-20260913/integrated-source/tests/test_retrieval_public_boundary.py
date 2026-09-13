"""Policy metadata stays in audit records across all Q8.2/Q8.3 requests."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.retrieval_panel_drivers import _SCOPE, freeze_retrieval_bundle
from test_modular_retrieval_panel_drivers import _run, _task
from test_retrieval_linked_benchmark import _neutral_materials


def test_actual_24_cell_precursor_requests_exclude_policy_and_pool_metadata(tmp_path):
    observed = []
    for benchmark in ('blade', 'discoverybench'):
        task = _task(benchmark)
        bundle = freeze_retrieval_bundle(task,
            query={'task_digest': task.content_hash, 'question': 'fixed train query'},
            budget={'provider_calls': 3, 'source_cap': 3, 'context_bytes': 4096},
            materials=_neutral_materials())
        for experiment, variants in _SCOPE.items():
            for variant in variants:
                for enabled in ((), ('M6',)):
                    stage, _, _, requests = _run(tmp_path / str(len(observed)), task, bundle,
                        experiment, variant, enabled)
                    observed.append((stage.detail.data(), requests[0]))
    assert len(observed) == 24
    # The complete original requests are checked, including precursor prompts.
    # These digests are actual controller metadata, not guessed sentinel values.
    forbidden_values = {stage[key] for stage, _ in observed
                        for key in ('policy_digest', 'source_bundle_digest')}
    for stage, request in observed:
        public = request['module_context']['retrieval']
        assert set(public) == {'by_lane', 'source_qualification', 'scientific_admission'}
        assert public == {key: stage[key] for key in public}
        encoded = FrozenRecord.from_dict(request).encoded
        assert all(key not in encoded for key in ('policy_digest', 'source_bundle_digest'))
        assert all(value not in encoded for value in forbidden_values)

