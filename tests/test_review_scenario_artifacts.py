from research_loop.modular.review_scenario_artifacts import verify_review_artifacts
from research_loop.modular.scenarios_review import run_review_scenario
from test_modular_review_scenarios import task,controls,responder
import pytest
from research_loop.ontology import ContractError

_VARIANTS = [("Q4.1", "single"), ("Q4.1", "independent_samples"), ("Q4.1", "roles"),
    ("Q4.2", "mechanism"), ("Q4.2", "alternative"), ("Q4.2", "measurement"), ("Q4.2", "experiment"), ("Q4.2", "generic"),
    ("Q4.3", "sealed_then_exchange"), ("Q4.3", "sequential"), ("Q4.4", "none_valid"), ("Q4.4", "defective"),
    ("Q4.5", "right_to_wrong"), ("Q4.5", "wrong_to_right"), ("Q4.5", "heterogeneous")]


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), _VARIANTS)
def test_every_registered_variant_has_a_strict_durable_round_trip(tmp_path, adapter, experiment_id, variant):
    public = task(adapter); root = tmp_path / "review"
    identities = None if variant != "heterogeneous" else {"reviewer_one": {"reviewer_id": "a", "model_id": "m1", "provider": "p1", "provenance": "fixture A"}, "reviewer_two": {"reviewer_id": "b", "model_id": "m2", "provider": "p2", "provenance": "fixture B"}}
    result = run_review_scenario(experiment_id, variant, task=public, frozen_controls=controls(public), review_callback=responder, artifact_root=root, reviewer_identities=identities)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id=experiment_id, variant=variant, result=result, reviewer_identities=identities).data()["status"] == "succeeded"


def test_strict_reader_rejects_coherent_content_attack_without_a_callback(tmp_path):
    public = task("blade"); root = tmp_path / "review"
    result = run_review_scenario("Q4.3", "sequential", task=public, frozen_controls=controls(public), review_callback=responder, artifact_root=root)
    attempt = root / "review-attempts.jsonl"
    text = attempt.read_text(encoding="utf-8").replace('"invocation":"revision"', '"invocation":"initial"')
    attempt.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(ContractError):
        verify_review_artifacts(root, task=public, controls=controls(public), experiment_id="Q4.3", variant="sequential", result=result)


def test_callback_failure_closes_a_partial_audit(tmp_path):
    public = task("blade"); root = tmp_path / "failed"
    def fail(_): raise RuntimeError("fixture callback failed")
    with pytest.raises(RuntimeError, match="fixture callback failed"):
        run_review_scenario("Q4.1", "single", task=public, frozen_controls=controls(public), review_callback=fail, artifact_root=root)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id="Q4.1", variant="single").data()["status"] == "failed"

def test_review_artifact_round_trip(tmp_path):
    public=task('blade'); root=tmp_path/'review'
    result=run_review_scenario('Q4.3','sequential',task=public,frozen_controls=controls(public),review_callback=responder,artifact_root=root)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id='Q4.3', variant='sequential', result=result).data()['status']=='succeeded'

# Coherent mutations rewrite all mechanical hashes, so rejection must come from
# the independent reconstruction rather than the terminal checksum alone.
import json
import shutil
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.review_scenario_artifacts import inventory
from test_modular_review_scenarios import prediction_responder


def _read_rows(root):
    return [json.loads(line) for line in (root / 'review-attempts.jsonl').read_text(encoding='utf-8').splitlines()]


def _write_record(path, body):
    path.write_bytes((FrozenRecord.from_dict(body).encoded + '\n').encode())


def _reseal(root, rows):
    previous = None
    for index, row in enumerate(rows):
        row.update(sequence=index, previous=previous)
        for field, digest in [('payload', 'payload_digest'), ('typed_response', 'typed_digest'),
                              ('review_event', 'review_event_digest'), ('prediction_event', 'prediction_event_digest')]:
            if field in row:
                row[digest] = FrozenRecord.from_dict(row[field]).content_hash
        previous = FrozenRecord.from_dict(row).content_hash
    (root / 'review-attempts.jsonl').write_bytes(b''.join((FrozenRecord.from_dict(row).encoded + '\n').encode() for row in rows))
    terminal = json.loads((root / 'review-terminal.json').read_bytes())
    terminal['entry_count'] = len(rows)
    terminal['files'] = inventory(root, include_terminal=False)
    _write_record(root / 'review-terminal.json', terminal)


def _check(root, experiment='Q4.3', variant='sequential', **kwargs):
    public = task('blade')
    return verify_review_artifacts(root, task=public, controls=controls(public), experiment_id=experiment, variant=variant, **kwargs)


def _produce(root, experiment='Q4.3', variant='sequential', **kwargs):
    public = task('blade')
    return run_review_scenario(experiment, variant, task=public, frozen_controls=controls(public),
        artifact_root=root, review_callback=kwargs.pop('review_callback', responder), **kwargs)


@pytest.fixture
def sequential_artifact(tmp_path):
    root = tmp_path / 'original'
    _produce(root)
    return root


@pytest.mark.parametrize('attack', ['allocation_missing', 'allocation_cost', 'sequential_prior', 'revision_prior',
                                  'identity', 'metrics', 'trace', 'budget', 'output_field', 'engine_submit'])
def test_exact_replay_refuses_coherently_rehashed_copies(sequential_artifact, tmp_path, attack):
    copied = tmp_path / 'copied'
    shutil.copytree(sequential_artifact, copied)
    assert _check(copied).data()['semantic_completion_verified'] is True
    rows = _read_rows(copied)
    if attack == 'allocation_missing':
        rows.remove(next(row for row in rows if row['event'] == 'callback_reserved'))
    elif attack == 'allocation_cost':
        next(row for row in rows if row['event'] == 'callback_reserved')['allocation']['fixture_units'] = 19
    elif attack in {'sequential_prior', 'revision_prior', 'identity'}:
        payloads = [row['payload'] for row in rows if row['event'] == 'callback_payload']
        if attack == 'sequential_prior':
            payloads[1]['prior_visible_submission']['response']['uncertainty'] = 'forged exposed material'
        elif attack == 'revision_prior':
            payloads[2]['prior_visible_submission'][0]['response']['uncertainty'] = 'forged revision material'
        else:
            payloads[0]['reviewer_identity']['provenance'] = 'invented provenance'
    elif attack == 'engine_submit':
        next(row['review_event'] for row in rows if row['event'] == 'review_engine_event' and row['review_event']['event'] == 'submit')['cost_units'] = 2
    else:
        output = next(row['output'] for row in rows if row['event'] == 'output')
        if attack == 'metrics': output['result']['metrics']['net_correction'] = 100
        elif attack == 'trace': output['mechanism_trace']['events'][0]['planned_call_count'] = 100
        elif attack == 'budget': output['result']['budget']['revision_callback_units'] = 100
        else: output['result']['unregistered_claim'] = 'extra output'
        _write_record(copied / 'review-outputs.json', output)
    _reseal(copied, rows)
    with pytest.raises(ContractError):
        _check(copied)
    assert _check(sequential_artifact).data()['status'] == 'succeeded'


def test_actual_m4_freeze_payload_reconstructed_from_retained_candidates(tmp_path):
    original, copied = tmp_path / 'original', tmp_path / 'copied'
    result = _produce(original, 'Q4.1', 'roles', review_callback=prediction_responder)
    assert result.record.data()['m4']['status'] == 'on'
    shutil.copytree(original, copied)
    assert _check(copied, 'Q4.1', 'roles').data()['status'] == 'succeeded'
    rows = _read_rows(copied)
    freeze = next(row['prediction_event'] for row in rows if row['event'] == 'prediction_registry_event' and row['prediction_event']['event'] == 'freeze')
    freeze['budget_units'] = 123
    _reseal(copied, rows)
    with pytest.raises(ContractError): _check(copied, 'Q4.1', 'roles')


@pytest.mark.parametrize('raw', ['{not valid JSON', ['not', 'a', 'mapping'], None, {'assessment': 'invalid'}])
def test_raw_values_survive_failed_conversion_and_prefix_replays(tmp_path, raw):
    root = tmp_path / 'failed'
    with pytest.raises(ContractError): _produce(root, 'Q4.1', 'single', review_callback=lambda _: raw)
    rows = _read_rows(root)
    assert next(row['raw'] for row in rows if row['event'] == 'callback_raw') == {'encoding': 'json', 'value': raw}
    assert not any(row['event'] == 'callback_response' for row in rows)
    assert _check(root, 'Q4.1', 'single').data()['semantic_completion_verified'] is False


def test_late_oracle_failure_has_complete_retained_prefix(tmp_path, monkeypatch):
    import research_loop.modular.scenarios_review as module
    root = tmp_path / 'failed'
    with monkeypatch.context() as patch:
        def fail(*_): raise RuntimeError('late fixture oracle failure')
        patch.setattr(module, '_fixture_oracle', fail)
        with pytest.raises(RuntimeError, match='late fixture oracle failure'): _produce(root)
    rows = _read_rows(root)
    assert len([row for row in rows if row['event'] == 'callback_response']) == 4
    assert _check(root).data()['status'] == 'failed'


def test_consumer_only_reads_archived_external_log_and_never_writes(tmp_path, monkeypatch):
    root, copied, external = tmp_path / 'original', tmp_path / 'copy', tmp_path / 'external.jsonl'
    _produce(root, review_log_path=external)
    raw = external.read_bytes()
    assert (root / 'review-engine-log.jsonl').read_bytes() == raw
    shutil.copytree(root, copied)
    external.unlink()
    original_open = Path.open
    def guarded_open(path, mode='r', *args, **kwargs):
        assert path != external, 'reader reopened external registry log'
        assert not any(flag in mode for flag in 'wax+'), 'reader attempted a file write'
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    assert _check(copied, review_log_path=external).data()['status'] == 'succeeded'


def test_external_log_must_be_fresh_and_callback_tampering_stops_progress(tmp_path):
    external = tmp_path / 'external.jsonl'
    external.write_bytes(b'existing evidence\n')
    with pytest.raises(ContractError, match='fresh'): _produce(tmp_path / 'existing', review_log_path=external)
    assert external.read_bytes() == b'existing evidence\n'
    other = tmp_path / 'new.jsonl'
    calls = []
    def tamper(payload):
        calls.append(payload)
        other.write_bytes(b'forged\n')
        return responder(payload)
    with pytest.raises(ContractError, match='external review log changed'):
        _produce(tmp_path / 'tampered', review_log_path=other, review_callback=tamper)
    assert len(calls) == 1
    with pytest.raises(ContractError): _check(tmp_path / 'tampered', review_log_path=other)


def test_journal_tampering_and_source_drift_stop_before_next_callback(tmp_path, monkeypatch):
    import research_loop.modular.review_scenario_artifacts as artifacts
    root = tmp_path / 'drift'
    calls = []
    original_sources = artifacts._sources
    def drift(payload):
        calls.append(payload)
        monkeypatch.setattr(artifacts, '_sources', lambda: [])
        return responder(payload)
    with pytest.raises(ContractError, match='source changed'):
        _produce(root, review_callback=drift)
    assert len(calls) == 1
    monkeypatch.setattr(artifacts, '_sources', original_sources)
    assert _check(root).data()['status'] == 'failed'


def test_actual_runner_requires_consumer_acceptance_before_return(tmp_path, monkeypatch):
    import research_loop.modular.review_scenario_artifacts as artifacts
    def reject(*args, **kwargs): raise ContractError('consumer refused delivery')
    monkeypatch.setattr(artifacts, 'verify_review_artifacts', reject)
    root = tmp_path / 'rejected'
    with pytest.raises(ContractError, match='consumer refused delivery'): _produce(root, 'Q4.1', 'single')
    assert (root / 'review-delivery-failure.json').is_file()


def test_partial_output_write_is_preserved_and_refused(tmp_path, monkeypatch):
    import research_loop.modular.review_scenario_artifacts as artifacts
    original = artifacts._write_new
    root = tmp_path / 'partial'
    def partial(path, record):
        if path.name == 'review-outputs.json':
            path.write_bytes(b'{partial')
            raise OSError('injected output write interruption')
        original(path, record)
    monkeypatch.setattr(artifacts, '_write_new', partial)
    with pytest.raises(OSError, match='injected output write interruption'): _produce(root, 'Q4.1', 'single')
    assert (root / 'review-outputs.json').read_bytes() == b'{partial'
    assert json.loads((root / 'review-terminal.json').read_bytes())['status'] == 'failed'
    with pytest.raises(ContractError): _check(root, 'Q4.1', 'single')

@pytest.mark.parametrize('attack', ['registry', 'frozen_payload'])
def test_m4_event_and_actual_frozen_payload_both_required(tmp_path, attack):
    original, copied = tmp_path / 'original', tmp_path / 'copied'
    _produce(original, 'Q4.1', 'roles', review_callback=prediction_responder)
    rows = _read_rows(original)
    registry = next(row['prediction_event'] for row in rows if row['event'] == 'prediction_registry_event')
    frozen = next(row['payload'] for row in rows if row['event'] == 'prediction_frozen_plan')
    assert frozen == {key: registry[key] for key in ('question', 'branches', 'budget_units')}
    shutil.copytree(original, copied)
    assert _check(copied, 'Q4.1', 'roles').data()['status'] == 'succeeded'
    if attack == 'registry':
        rows.remove(next(row for row in rows if row['event'] == 'prediction_registry_event'))
    else:
        next(row['payload'] for row in rows if row['event'] == 'prediction_frozen_plan')['budget_units'] = 90
    _reseal(copied, rows)
    with pytest.raises(ContractError): _check(copied, 'Q4.1', 'roles')


def test_caller_identity_is_independent_input_for_copied_artifacts(tmp_path):
    identities = {'assessment': {'reviewer_id': 'caller-reviewer', 'model_id': 'caller-model',
        'provider': 'caller-provider', 'provenance': 'explicit caller receipt'}}
    root, copied = tmp_path / 'original', tmp_path / 'copy'
    _produce(root, 'Q4.1', 'single', reviewer_identities=identities)
    shutil.copytree(root, copied)
    assert _check(copied, 'Q4.1', 'single', reviewer_identities=identities).data()['status'] == 'succeeded'
    with pytest.raises(ContractError): _check(copied, 'Q4.1', 'single')
    identities['assessment']['provider'] = 'other-provider'
    with pytest.raises(ContractError): _check(copied, 'Q4.1', 'single', reviewer_identities=identities)


def test_linked_artifact_parent_is_refused_before_callback(tmp_path):
    import os
    actual, linked = tmp_path / 'actual', tmp_path / 'linked'
    actual.mkdir()
    try:
        os.symlink(actual, linked, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'host cannot create a test directory symlink: {exc}')
    calls = []
    with pytest.raises(ContractError, match='link'):
        _produce(linked / 'artifact', 'Q4.1', 'single', review_callback=lambda value: calls.append(value))
    assert calls == []
    assert list(actual.iterdir()) == []


def test_partial_journal_append_is_preserved(tmp_path, monkeypatch):
    import research_loop.modular.review_scenario_artifacts as artifacts
    root = tmp_path / 'partial-journal'
    original = artifacts.ReviewArtifactSession._persist
    def partial(self, record):
        if record.data()['event'] == 'callback_raw':
            with (root / 'review-attempts.jsonl').open('ab') as stream: stream.write(b'{partial')
            raise OSError('injected journal interruption')
        return original(self, record)
    monkeypatch.setattr(artifacts.ReviewArtifactSession, '_persist', partial)
    with pytest.raises(OSError, match='injected journal interruption'): _produce(root, 'Q4.1', 'single')
    assert (root / 'review-attempts.jsonl').read_bytes().endswith(b'{partial')
    assert json.loads((root / 'review-terminal.json').read_bytes())['status'] == 'failed'
    with pytest.raises(ContractError): _check(root, 'Q4.1', 'single')
