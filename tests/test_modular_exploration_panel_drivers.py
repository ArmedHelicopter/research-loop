"""52-cell public synthetic grid; real Docker, no provider or validation I/O."""
from hashlib import sha256
import base64
import csv as csv_module
import io
import hmac
import json
import os

import pytest

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import scenario as base_scenario
from research_loop.modular.exploration_panel_drivers import (
    BUDGET, Q71_VARIANTS, Q72_VARIANTS, exploration_panel_injection, freeze_exploration_panel_bundle, install_drivers,
)
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditAuthority, AuditVerifier
from research_loop.ontology import ContractError

IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
PROGRAM = "import csv,json\nwith open('/input/data_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'mean':sum(xs)/len(xs),'control':sum(x-x for x in xs)}))\n"
BAD_PROGRAM = PROGRAM.replace("sum(x-x for x in xs)", "1.0")


def _task(name):
    identity = DataIdentity(name, 'public-exploration', name + ':exploration', 'synthetic-v1', '7' * 64, 'train')
    if name == 'blade':
        return BladeAdapter().prepare(identity, {'task_id': identity.task_id, 'dataset_id': 'public', 'research_question': 'public bounded diagnostic', 'data_schema': [{'name': 'x', 'dtype': 'float'}]})
    return DiscoveryBenchAdapter().prepare(identity, {'task_id': identity.task_id, 'question': 'public bounded diagnostic', 'source_kind': 'synthetic', 'dataset': [{'name': 'x', 'columns': [{'name': 'x'}]}]})


class Authority:
    """Caller-side independent fixture verifier, never a variant oracle.

    Two pre-frozen observation documents bind literal program/input hashes,
    source versions and measurement checks. Actual Docker stdout is compared to
    both independently frozen numeric observations, including the control.
    """
    def __init__(self):
        self.keys = {'a': b'a' * 32, 'b': b'b' * 32}
        self.documents = {}; self.calls = []; self.fault = None

    def _call(self, subject, observed=False):
        body = subject.data(); self.calls.append(body)
        if self.fault == 'transport':
            raise OSError('synthetic verification unavailable')
        if self.fault in ('partial_known', 'partial_unknown'):
            cost = {'unit': 'verifier_units', 'units': 3 if self.fault == 'partial_known' else None}
            error = OSError('synthetic partial transport')
            error.partial_response = FrozenRecord.from_dict({'schema': 'synthetic-partial-response-v1',
                'subject_digest': subject.content_hash, 'cost': cost})
            error.cost = FrozenRecord.from_dict(cost)
            raise error
        diagnostic = body['diagnostic']; contract = body['authority_contract']; proofs = []; documents = []
        for declared in contract['authorities']:
            proof = self.documents[(contract['contract_id'], declared['authority_id'], diagnostic['diagnostic_id'])]
            assert proof['task_digest'] == body['task_digest']
            assert proof['source_id'] == body['source_id'] and proof['data_version'] == body['data_version']
            assert proof['program_sha256'] == diagnostic['program_sha256']
            assert proof['inputs'] == diagnostic['inputs']
            assert proof['measurement_contract'] == diagnostic['measurement_contract']
            assert proof['original_requirements'] == body['original_requirements']
            assert proof['diagnostic_requirements'] == diagnostic['requirements']
            documents.append(proof)
            observation = {'authority_id': declared['authority_id'], 'source_group': declared['source_group'],
                'subject_digest': subject.content_hash, 'contract_id': contract['contract_id'],
                'observation_digest': FrozenRecord.from_dict(proof).content_hash}
            encoded = FrozenRecord.from_dict(observation).encoded.encode()
            signed = hmac.digest(self.keys[declared['authority_id']], encoded, 'sha256')
            if self.fault == 'bad_signature': signed = bytes(32)
            valid = hmac.compare_digest(signed, hmac.digest(self.keys[declared['authority_id']], encoded, 'sha256'))
            proofs.append({**observation, 'signature_verified': valid})
        d = documents[0]
        facts = {'safe': True, 'authorized': d['authorized'], 'resources_available': d['resources_available'],
            'diagnostic_inputs_available': True, 'scientific_data_status': 'passed' if d['data_known'] else 'unknown',
            'block_status': 'blocked' if d['requires_repair'] else 'unknown'}
        audits = []
        if observed:
            material = body['trusted_execution_material']
            receipt = ExecutionReceipt.parse(material['execution_receipt'])
            assert receipt.content_hash == body['execution_digest']
            program_bytes = base64.b64decode(material['program_bytes_b64'], validate=True)
            assert sha256(program_bytes).hexdigest() == diagnostic['program_sha256'] == receipt.artifact.sha256
            assert len(program_bytes) == receipt.artifact.byte_count
            assert material['public_input_bytes'].keys() == diagnostic['inputs'].keys()
            for artifact_id, supplied in material['public_input_bytes'].items():
                content = base64.b64decode(supplied['bytes_b64'], validate=True)
                expected_input = diagnostic['inputs'][artifact_id]
                assert supplied['sha256'] == sha256(content).hexdigest() == expected_input['sha256']
                assert supplied['byte_count'] == len(content) == expected_input['byte_count']
                assert receipt.record.data()['input_artifacts'][artifact_id] == {'artifact_id': artifact_id, **expected_input}
            received_csv = base64.b64decode(material['public_input_bytes']['data_csv']['bytes_b64']).decode()
            numeric = [float(x['x']) for x in csv_module.DictReader(io.StringIO(received_csv))]
            assert sum(numeric) / len(numeric) == -1.0
            assert receipt.record.data()['stdout'] == body['execution_observation']['stdout']
            output = json.loads(body['execution_observation']['stdout']) if body['execution_status'] == 'succeeded' else None
            observed_pair = [(doc['expected_mean'], doc['expected_control']) for doc in documents]
            conflict = len(set(observed_pair)) != 1
            matches = output is not None and all(output == {'mean': doc['expected_mean'], 'control': doc['expected_control']} for doc in documents)
            qualified = matches and not conflict and all(doc['data_known'] and doc['measurement_qualified'] for doc in documents)
            validity = 'valid' if qualified else 'invalid' if output is not None and output['control'] != 0 else 'unknown'
            outcome = 'negative' if output is not None and output['mean'] <= 0 else 'positive'
            state = ScientificState(validity, ('refuted' if outcome == 'negative' else 'supported') if qualified else 'undetermined', 'unknown', 'explore')
            repaired = matches and d['requires_repair'] and d['repairable']
            facts = {'block_status': 'cleared' if repaired else 'blocked' if d['requires_repair'] else 'unknown',
                'resource_request_verified': diagnostic['requirements']['execution_units'] < body['original_requirements']['execution_units'],
                'diagnostic_answer': 'repair_supported' if repaired else 'inconclusive' if not d['data_known'] else 'no_repair',
                'scientific_status': 'conflict' if conflict else 'data_unknown' if not d['data_known'] else
                    'qualified_' + outcome if qualified else 'measurement_repair' if d['requires_repair'] else 'unknown'}
            for aid, key in self.keys.items():
                audits.append(AuditAuthority(aid, key).issue(identity=DataIdentity.parse(body['identity']),
                    objective_digest=body['objective_digest'], execution_digest=body['execution_digest'], state=state,
                    outcome=outcome, audit=[AuditItem('measurement', True, qualified)]).data())
        row = {'schema': 'exploration-observation-verified-v1' if observed else 'exploration-preflight-verified-v1',
            'subject_digest': subject.content_hash, 'observations': proofs, 'facts': facts,
            'cost': {'unit': 'verifier_units', 'units': None if self.fault == 'unknown_cost' else 1}}
        if observed: row['audits'] = audits
        if self.fault == 'source': proofs[0]['source_group'] = 'foreign'
        if self.fault == 'subject': row['subject_digest'] = '0' * 64
        if self.fault == 'audit_subject' and observed:
            row['audits'][0]['body']['execution_digest'] = '0' * 64
        return FrozenRecord.from_dict(row)

    def verify_preflight(self, subject): return self._call(subject)
    def verify_observation(self, subject): return self._call(subject, True)


def _item(task, csv, authority, *, data_known=True, qualified=False, conflict=False, repair=False, repairable=True, kind=None, hard='none'):
    inputs = {'data_csv': {'sha256': sha256(csv.read_bytes()).hexdigest(), 'byte_count': len(csv.read_bytes())}}
    diagnostics = []
    for identifier, code, uncertainty, subjective, tokens in (('broad_probe', BAD_PROGRAM, 1, 10, 4), ('small_probe', PROGRAM, 4, 1, 1)):
        diagnostics.append({'diagnostic_id': identifier, 'program': code,
            'program_sha256': sha256(code.replace('\n', os.linesep).encode()).hexdigest(), 'image': IMAGE,
            'inputs': inputs, 'requirements': {'execution_units': 1, 'token_units': tokens},
            'subjective_score': subjective, 'uncertainty_reduction': uncertainty,
            'measurement_contract': {'contract_id': 'mean-zero-control-v1', 'source_id': task.identity.group_id,
                'data_version': task.identity.dataset_version, 'observable': 'mean', 'negative_control_id': 'subtract-self'}})
    if qualified:
        # Both diagnostic opportunities can retain the valid negative. The
        # module contrast concerns evidence handling, not withholding data.
        diagnostics[0]['program'] = PROGRAM
        diagnostics[0]['program_sha256'] = diagnostics[1]['program_sha256']
    original = {'execution_units': 3, 'token_units': 8}
    doc = {'task_digest': task.content_hash, 'source_id': task.identity.group_id, 'data_version': task.identity.dataset_version,
        'data_known': data_known, 'measurement_qualified': qualified, 'requires_repair': repair, 'repairable': repairable,
        'authorized': hard != 'authorization', 'resources_available': hard != 'resource', 'original_requirements': original}
    contract_id = FrozenRecord.from_dict({**doc, 'conflict': conflict, 'diagnostics': diagnostics}).content_hash
    pairs = [{'authority_id': aid, 'source_group': 'independent-fixture-' + aid} for aid in authority.keys]
    for declaration in pairs:
        for diagnostic in diagnostics:
            authority.documents[(contract_id, declaration['authority_id'], diagnostic['diagnostic_id'])] = {
                **doc, 'observer': declaration['authority_id'], 'inputs': inputs, 'program_sha256': diagnostic['program_sha256'],
                'measurement_contract': diagnostic['measurement_contract'], 'diagnostic_requirements': diagnostic['requirements'],
                'expected_mean': 1.0 if conflict and declaration['authority_id'] == 'b' else -1.0, 'expected_control': 0.0}
    row = {'source_id': task.identity.group_id, 'data_version': task.identity.dataset_version,
        'public_issue': 'Evaluate the frozen measurement and a smaller public diagnostic without upgrading exploratory work.',
        'diagnostic_scope': 'data_check' if not data_known else 'instrument_repair' if repair else 'measurement',
        'original_requirements': original, 'declared_state': ScientificState('unknown', 'undetermined', 'unknown', 'explore').__dict__,
        'diagnostics': diagnostics, 'hard_constraint': hard,
        'authority_contract': {'contract_id': contract_id, 'source_id': task.identity.group_id, 'authorities': pairs}}
    if kind:
        row['veto'] = {'kind': kind, 'reason': 'Original frozen plan has an unresolved source-bound feasibility objection.',
            'evidence_digest': FrozenRecord.from_dict(doc).content_hash}
    return row


def _compile(tmp_path, monkeypatch, *, hard='none', repairable=True):
    csv = tmp_path / 'data.csv'; csv.write_text('x\n-2\n0\n')
    tasks = {name: _task(name) for name in ('blade', 'discoverybench')}; authority = Authority(); bundles = {}
    for task in tasks.values():
        q71 = {'low_cost': _item(task, csv, authority, hard=hard), 'data_unknown': _item(task, csv, authority, data_known=False, hard=hard),
            'measurement_repair': _item(task, csv, authority, repair=True, hard=hard),
            'valid_negative': _item(task, csv, authority, qualified=True, hard=hard),
            'conflict': _item(task, csv, authority, conflict=True, hard=hard)}
        q72 = {name: _item(task, csv, authority, kind=kind, repair=name != 'value', repairable=repairable, hard=hard if hard != 'none' else 'contract' if name == 'deterministic' else 'none')
               for name, kind in zip(Q72_VARIANTS, ('deterministic_block', 'evidence_insufficient', 'value_doubt'))}
        bundles[task.content_hash] = freeze_exploration_panel_bundle(task, q71=q71, q72=q72, budget=FrozenRecord.from_dict(BUDGET))
    local = dict(panel_runner.DRIVERS)
    broker = DockerExecutionBroker([tmp_path])
    install_drivers(local, broker=broker, input_resolver=lambda task, bundle: {'data_csv': csv}, authority=authority)
    monkeypatch.setattr(panel_runner, 'DRIVERS', local)
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={'prompt': {'instructions': 'synthetic'}}, search_cost=0)
    p0 = FrozenRecord.from_dict({'control': 'fixed'})
    grids = obligation_grids(('Q7.1', 'Q7.2'), baseline_digest='f' * 64, p0_control=p0)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage='exploration', scope_ids=('Q7.1', 'Q7.2'), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict(BUDGET), baseline_digest='f' * 64, p0_control=p0, packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({'scorer': 'none'}), acceptance_criteria=FrozenRecord.from_dict({'engineering': True}))
    return compiled, tasks, authority, bundles


def _model(seen, *, overclaim=False):
    def call(request):
        row = request.data(); seen.append(row)
        encoded = request.encoded
        for forbidden in ('"variant"', '"arm_id"', '"enabled_modules"', 'independent-fixture-', '"expected_mean"', '"authorities"',
                          '"trusted_execution_material"', '"program_bytes_b64"', '"public_input_bytes"', '"execution_receipt"'):
            assert forbidden not in encoded
        if row['slot'] == 'prospective':
            assert row['execution_feedback'] == []
            assert 'declared_state' not in row['module_context']['public_material']
            return FrozenRecord.from_dict({'diagnostic_id': 'broad_probe', 'exploration_allowed': True,
                'evidence_qualified': True, 'decision': 'explore', 'rationale': 'Frozen subjective choice before observed results.'})
        if row['slot'] == 'diagnostic':
            obs = row['module_context']['observation']; transition = obs['exploration_transition']; gate = obs['evidence_gate']
            return FrozenRecord.from_dict({'decision': transition['decision'] if transition else 'explore' if obs['host_diagnostic_allowed'] else 'block',
                'exploration_allowed': obs['host_diagnostic_allowed'], 'evidence_qualified': gate['admitted'] if gate else obs['execution'] is not None and obs['execution']['exit_code'] == 0,
                'rationale': 'Only available operation results update the observed judgement.'})
        p0 = row['module_context']['p0_evidence']
        return FrozenRecord.from_dict({'objective_digest': row['module_context']['required_objective_digest'],
            'outcome': p0['outcome'] if p0 and p0['admitted'] else 'positive' if overclaim else 'invalid' if p0 and p0['state']['validity'] == 'invalid' else 'unknown',
            'evidence_ids': p0['evidence_ids'] if p0 else [], 'conclusion': 'Bounded synthetic observation; no programme completion.', 'programme_complete': False})
    return call


def _run(compiled, tasks, cell, sidecar, seen, **kwargs):
    return panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({'objective': 'mean exceeds zero under calibrated control'}),
        sidecar=sidecar, model=_model(seen, **kwargs), audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}))


def _events(result):
    return [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text().splitlines()]


def test_freeze_complete_grid_without_any_external_call(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch)
    assert len(compiled.panel.cells) == 52 and authority.calls == []
    bundle = next(iter(bundles.values())).data(); task = next(iter(tasks.values()))
    bundle['q71']['low_cost']['data_version'] = 'foreign'
    with pytest.raises(ContractError):
        freeze_exploration_panel_bundle(task, q71=bundle['q71'], q72=bundle['q72'], budget=FrozenRecord.from_dict(BUDGET))


def test_boolean_budget_cannot_impersonate_integer_opportunity(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch)
    task = next(iter(tasks.values())); bundle = bundles[task.content_hash].data()
    with pytest.raises(ContractError):
        freeze_exploration_panel_bundle(task, q71=bundle['q71'], q72=bundle['q72'],
            budget=FrozenRecord.from_dict({**BUDGET, 'execution_opportunities': True}))
    assert authority.calls == []


def test_full_52_cell_real_docker_grid_keeps_prospective_and_actual_denominators(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch); runs = []; results = {}
    for index, cell in enumerate(compiled.panel.cells):
        seen = []; before = len(authority.calls)
        result = _run(compiled, tasks, cell, tmp_path / 'runs' / str(index), seen); events = _events(result)
        assert result.runtime.status == 'succeeded'
        assert result.call_plan.data()['model_calls'] == 3 and result.call_plan.data()['execution_attempts'] == 1
        assert len(authority.calls) - before == 2
        assert len([e for e in events if e['stage'] == 'exploration_verifier_request']) == 2
        assert sum(e['data']['cost']['units'] for e in events if e['stage'] == 'exploration_verifier_result') == 2
        first_response = next(i for i, e in enumerate(events) if e['stage'] == 'model_response')
        assert first_response < next(i for i,e in enumerate(events) if e['stage'] == 'exploration_verifier_request')
        assert next(i for i,e in enumerate(events) if e['stage'] == 'exploration_execution_reservation') < next(i for i,e in enumerate(events) if e['stage'] == 'execution_request')
        obs = seen[1]['module_context']['observation']; key = (cell.identity.benchmark, cell.coverage_id, cell.variant, tuple(cell.runtime_arm.data()['enabled']))
        results[key] = obs
        if cell.coverage_id == 'Q7.1' and cell.variant == 'valid_negative':
            assert events[-1]['data']['decision'] == 'closed_negative'
            assert events[-1]['data']['scientific_validated'] is True
        if cell.coverage_id == 'Q7.1' and cell.variant != 'valid_negative':
            assert events[-1]['data']['scientific_validated'] is False
        if cell.coverage_id == 'Q7.1' and 'M1' in cell.runtime_arm.data()['enabled']:
            expected_status = {'low_cost': 'unknown', 'data_unknown': 'data_unknown', 'measurement_repair': 'measurement_repair', 'valid_negative': 'qualified_negative', 'conflict': 'conflict'}[cell.variant]
            assert obs['scientific_status'] == expected_status
        if 'M7' in cell.runtime_arm.data()['enabled']:
            assert obs['selected_diagnostic_id'] == 'small_probe'
            assert obs['exploration_transition']['original_prerequisite_promoted'] is False
        else:
            assert obs['selected_diagnostic_id'] == 'broad_probe'
        runs.append(result.runtime)
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runs)).observed_cells == 52
    assert any(k[1:3] == ('Q7.2', 'deterministic') and v['exploration_transition'] and v['exploration_transition']['decision'] == 'repair' for k,v in results.items())
    assert any(k[1:3] == ('Q7.2', 'value') and v['exploration_transition'] and v['exploration_transition']['decision'] == 'explore' for k,v in results.items())
    assert any(v['evidence_gate'] is not None and v['evidence_gate']['admitted'] is False for v in results.values())


@pytest.mark.parametrize('hard', ['authorization', 'resource'])
@pytest.mark.parametrize('scope,variant,count', [('Q7.1', 'low_cost', 4), ('Q7.2', 'deterministic', 2)])
def test_legitimate_hard_missing_conditions_remain_in_both_arm_denominators(tmp_path, monkeypatch, hard, scope, variant, count):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch, hard=hard)
    cells = [cell for cell in compiled.panel.cells if cell.identity.benchmark == 'blade' and cell.coverage_id == scope and cell.variant == variant]
    assert len(cells) == count
    for index, cell in enumerate(cells):
        seen = []; result = _run(compiled, tasks, cell, tmp_path / str(index), seen)
        assert result.runtime.status == 'succeeded' and result.call_plan.data()['model_calls'] == 3
        assert result.call_plan.data()['execution_attempts'] == 0
        obs = seen[1]['module_context']['observation']
        assert obs['host_diagnostic_allowed'] is False
        if obs['exploration_transition']:
            assert obs['exploration_transition']['decision'] == 'block'


def test_actual_diagnostic_does_not_clear_unrepaired_deterministic_block(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch, repairable=False)
    cell = next(cell for cell in compiled.panel.cells if cell.coverage_id == 'Q7.2' and cell.variant == 'deterministic' and 'M7' in cell.runtime_arm.data()['enabled'])
    seen = []; result = _run(compiled, tasks, cell, tmp_path / 'run', seen)
    assert result.runtime.status == 'succeeded' and result.call_plan.data()['execution_attempts'] == 1
    transition = seen[1]['module_context']['observation']['exploration_transition']
    assert transition['decision'] == 'block' and transition['observed_block_status'] == 'blocked'
    assert transition['prior_evidence_digest'] != transition['diagnostic_evidence_digest']


@pytest.mark.parametrize('fault', ['transport', 'source', 'subject', 'bad_signature', 'audit_subject'])
def test_authority_failures_preserve_reserved_calls_and_unknown_cost(tmp_path, monkeypatch, fault):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch); authority.fault = fault
    cell = next(cell for cell in compiled.panel.cells if cell.coverage_id == 'Q7.1' and 'M7' in cell.runtime_arm.data()['enabled'])
    seen = []; result = _run(compiled, tasks, cell, tmp_path / 'run', seen); events = _events(result)
    assert result.runtime.status == 'failed'
    assert len(seen) == 1 and len(authority.calls) == (2 if fault == 'audit_subject' else 1)
    assert all(e['data']['cost']['units'] is None for e in events if e['stage'] == 'exploration_verifier_request')
    if fault != 'audit_subject':
        assert any(e['stage'] == 'exploration_verifier_failure' for e in events)


def test_unknown_cost_and_unchanged_candidate_reach_fixed_p0_gate(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch); authority.fault = 'unknown_cost'
    cell = next(cell for cell in compiled.panel.cells if cell.coverage_id == 'Q7.1' and cell.variant == 'low_cost' and 'M7' in cell.runtime_arm.data()['enabled'])
    seen = []; result = _run(compiled, tasks, cell, tmp_path / 'run', seen, overclaim=True); events = _events(result)
    assert result.runtime.status == 'blocked'
    assert events[-1]['data']['reasons'] == ['missing_validated_evidence']
    assert all(e['data']['cost']['units'] is None for e in events if e['stage'] == 'exploration_verifier_result')
    response = next(e['data']['response'] for e in reversed(events) if e['stage'] == 'model_response')
    assert events[-1]['data']['candidate_digest'] == FrozenRecord.from_dict(response).content_hash


def test_bad_actual_source_spends_no_model_or_verifier_opportunity(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch)
    (tmp_path / 'data.csv').write_text('x\n777\n')
    cell = compiled.panel.cells[0]; seen = []
    result = _run(compiled, tasks, cell, tmp_path / 'run', seen)
    assert result.runtime.status == 'failed' and seen == [] and authority.calls == []
    assert result.call_plan.data()['model_calls'] == result.call_plan.data()['execution_attempts'] == 0


def test_both_candidates_checked_even_if_bad_second_one_not_proposed(tmp_path, monkeypatch):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch)
    cell = compiled.panel.cells[0]
    driver = panel_runner.DRIVERS[cell.coverage_id]
    original = driver.broker.validate_inputs
    calls = []
    def checking(identity, inputs):
        calls.append(identity)
        if len(calls) == 2:
            raise ContractError('second candidate input drift')
        return original(identity, inputs)
    monkeypatch.setattr(driver.broker, 'validate_inputs', checking)
    seen = []; result = _run(compiled, tasks, cell, tmp_path / 'run', seen)
    assert result.runtime.status == 'failed' and len(calls) == 2 and seen == [] and authority.calls == []


@pytest.mark.parametrize('kind', ['input', 'program'])
def test_actual_bytes_drift_after_docker_never_reaches_observation_verifier(tmp_path, monkeypatch, kind):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch)
    cell = compiled.panel.cells[0]; broker = panel_runner.DRIVERS[cell.coverage_id].broker
    original = broker.execute
    def drift(request):
        receipt = original(request)
        target = tmp_path / 'data.csv' if kind == 'input' else request.program
        target.write_text('mutated after Docker')
        return receipt
    monkeypatch.setattr(broker, 'execute', drift)
    seen = []; result = _run(compiled, tasks, cell, tmp_path / 'run', seen)
    assert result.runtime.status == 'failed' and len(seen) == 1 and len(authority.calls) == 1
    assert result.call_plan.data()['execution_attempts'] == 1


@pytest.mark.parametrize('fault', ['partial_known', 'partial_unknown'])
def test_partial_transport_receipt_and_cost_are_persisted_before_failure(tmp_path, monkeypatch, fault):
    compiled, tasks, authority, bundles = _compile(tmp_path, monkeypatch); authority.fault = fault
    seen = []; result = _run(compiled, tasks, compiled.panel.cells[0], tmp_path / 'run', seen); events = _events(result)
    assert result.runtime.status == 'failed' and len(seen) == len(authority.calls) == 1
    partial = next(e for e in events if e['stage'] == 'exploration_verifier_partial_response')
    failure = next(e for e in events if e['stage'] == 'exploration_verifier_failure')
    assert events.index(partial) < events.index(failure)
    assert failure['data']['partial_response_digest'] == partial['data']['receipt_digest']
    expected = 3 if fault == 'partial_known' else None
    assert failure['data']['reported_cost']['units'] == failure['data']['exception_reported_cost']['units'] == expected
    assert failure['data']['cost']['units'] is None
