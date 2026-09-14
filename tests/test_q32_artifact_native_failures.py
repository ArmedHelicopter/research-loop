"""Actual native panel orchestration; synthetic model transport and real Docker."""
import json

import pytest

from research_loop.modular.q32_artifacts import Q32ArtifactBridge
from research_loop.modular.q32_execution import Q32ExecutionStage, run_q32_prospective_execution_panel
from research_loop.modular.m4_m5_artifacts import M4M5ArtifactBridge
from research_loop.modular.runtime import AuditVerifier
from test_q32_native_provider import prepare


@pytest.mark.parametrize('fault', ['initial', 'terminal', 'later', 'final'])
def test_actual_native_artifact_failure_preserves_calls_and_panel_denominator(tmp_path, monkeypatch, fault):
    exporter, config, providers, logs = prepare(tmp_path, monkeypatch)
    (tmp_path / 'independent-config-before-producer.json').write_text(config.record.encoded, encoding='utf-8')
    if fault == 'initial':
        original = M4M5ArtifactBridge.journal
        def fail_first_freeze(self, journal, event):
            original(self, journal, event)
            raise OSError('synthetic failure after first durable prediction')
        monkeypatch.setattr(M4M5ArtifactBridge, 'journal', fail_first_freeze)
    elif fault == 'terminal':
        original = Q32ArtifactBridge.close
        def fail_after_close(self):
            original(self)
            raise OSError('synthetic delivery failure after durable closure')
        monkeypatch.setattr(Q32ArtifactBridge, 'close', fail_after_close)
    else:
        original = Q32ExecutionStage.run
        def corrupt_prior_after_later_stage(self, model, broker):
            result = original(self, model, broker)
            trigger = providers[1] if fault == 'later' else providers[3]
            if model.session.provider is trigger:
                source = tmp_path / 'run/0/runtime' / ('predictions.jsonl' if fault == 'later' else 'result.json')
                (tmp_path / ('original-' + source.name)).write_bytes(source.read_bytes())
                source.write_bytes(b'{}\n')
            return result
        monkeypatch.setattr(Q32ExecutionStage, 'run', corrupt_prior_after_later_stage)
    result = run_q32_prospective_execution_panel(config, prospective_exporter=exporter,
        snapshot_root=exporter.config['snapshot_root'], export_root=exporter.output_root,
        run_root=tmp_path/'run', model_factory=lambda i: providers[i],
        verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32})).data()['result']
    expected_calls = {'initial': [0, 0, 0, 0], 'terminal': [4, 0, 0, 0],
                      'later': [4, 4, 0, 0], 'final': [4, 4, 4, 4]}[fault]
    assert [len(log) for log in logs] == expected_calls
    assert result['cell_count'] == 4 and result['measurement_denominator'] == 12
    assert len(result['results']) == 4 and sum(len(row['rows']) for row in result['results']) == 12
    assert result['status'] == 'incomplete' and result['run_terminal'] is True
    assert result['eligible_measurements'] == 0 and not result['score_eligible']
    assert result['historical_measurements'] == {'initial': 0, 'terminal': 3, 'later': 6, 'final': 12}[fault]
    assert [row['model_attempts'] for row in result['results']] == expected_calls
    assert all(row['score_eligible'] is False for row in result['results'])
    assert not result['scientific_validated'] and not result['programme_complete']
    if fault == 'terminal':
        assert result['results'][0]['runtime_result'] is None
        assert len([r for r in result['results'][0]['rows'] if r['receipt'] is not None]) == 3
        assert (tmp_path/'run/0/runtime/audit-failure.json').is_file()
    saved = json.loads((tmp_path/'run/panel-result.json').read_bytes())
    assert saved == result
