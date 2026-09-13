"""Synthetic causal wiring: two benchmarks, 36 cells, real Docker, no provider I/O."""
from dataclasses import replace
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path

import pytest

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import scenario as base_scenario
from research_loop.modular.feasibility_panel_drivers import (
    _STAGES, _identifiable, _verified, feasibility_panel_injection,
    freeze_feasibility_panel_bundle, install_drivers)
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError

SPLIT = '7' * 64
IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
PROGRAM = "import csv, json\nwith open('/input/data_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'sum':sum(xs),'negative_control':sum(x-x for x in xs)}))\n"


def _task(name):
    identity = DataIdentity(name, 'f-' + name, name + ':f', 'synthetic-v1', SPLIT, 'train')
    if name == 'blade':
        return BladeAdapter().prepare(identity, {'task_id': identity.task_id, 'dataset_id': 'public', 'research_question': 'public feasibility', 'data_schema': [{'name': 'x', 'dtype': 'float'}]})
    return DiscoveryBenchAdapter().prepare(identity, {'task_id': identity.task_id, 'question': 'public feasibility', 'source_kind': 'synthetic', 'dataset': [{'name': 'x', 'columns': [{'name': 'x'}]}]})


def _branches(opposite):
    directions = ('increase', 'decrease') if opposite else ('increase', 'increase')
    return [{'hypothesis_id': 'h' + str(i), 'mechanism_key': 'm' + str(i), 'mechanism': 'public mechanism',
        'intervention': 'same public intervention', 'elimination_condition': 'public falsifier',
        'predictions': [{'prediction_id': 'p' + str(i), 'discriminator_id': 'd', 'observable': 'x',
            'direction': direction, 'value_range': None, 'failure_condition': 'public failure'}]} for i, direction in enumerate(directions, 1)]


class _Authority:
    """Fixture endpoint verifies two HMAC-bound synthetic observation documents.

    The synthetic source records are explicit inputs; exit status alone never
    establishes a measurement or independent scientific observation.
    """
    def __init__(self):
        self.sources = {}; self.calls = []; self.fault = None
        self.keys = {'synthetic-a': b'a' * 32, 'synthetic-b': b'b' * 32}

    def _receipt(self, subject, prediction=False):
        row = subject.data(); self.calls.append(row)
        if self.fault == 'transport':
            raise OSError('synthetic verifier unavailable')
        contract = row['authority_contract']; observations = []
        for authority in contract['authorities']:
            proof = self.sources[(contract['contract_id'], authority['authority_id'])]
            assert proof['program_sha256'] == row['program_sha256']
            assert proof['input_artifacts'] == row['input_artifacts']
            status = 'unknown' if proof['observation'] is None else 'passed'
            if row['stage'] != 'data' and row['execution_status'] != 'succeeded':
                status = 'failed'
            if row['stage'] in ('discriminating_measurement', 'independent_result') and status == 'passed':
                output = json.loads(row['execution_observation']['stdout'])
                status = 'passed' if output == proof['observation'] else 'failed'
            if row['stage'] == 'discriminating_measurement' and row['prediction_plan'] is not None and not _identifiable(row['prediction_plan']['branches']):
                status = 'failed'
            if prediction and (row['measurement_status'] != 'passed' or not _identifiable(row['prediction_plan']['branches'])):
                status = 'unknown'
            if self.fault == 'unknown': status = 'unknown'
            if self.fault == 'failed': status = 'failed'
            if self.fault in ('data_unknown', 'data_failed') and row['stage'] == 'data': status = self.fault.removeprefix('data_')
            observation = {'authority_id': authority['authority_id'], 'source_group': authority['source_group'],
                'observation_digest': FrozenRecord.from_dict(proof).content_hash,
                'contract_id': contract['contract_id'], 'subject_digest': subject.content_hash, 'status': status}
            encoded = FrozenRecord.from_dict(observation).encoded.encode()
            signed = hmac.digest(self.keys[authority['authority_id']], encoded, 'sha256')
            if self.fault == 'bad_signature': signed = bytes(32)
            verified = hmac.compare_digest(signed, hmac.digest(self.keys[authority['authority_id']], encoded, 'sha256'))
            observations.append({**observation, 'signature_verified': verified})
        statuses = [x['status'] for x in observations]
        status = 'failed' if 'failed' in statuses else 'unknown' if 'unknown' in statuses else 'passed'
        receipt = {'schema': 'verified-prediction-outcome-v2' if prediction else 'verified-feasibility-stage-v2',
            'subject_digest': subject.content_hash, 'observations': observations, 'status': status,
            'cost': {'unit': 'verifier_units', 'units': 1}}
        if prediction:
            receipt['classifications'] = {x['hypothesis_id']: 'unknown' if status != 'passed' else
                'consistent' if x['predictions'][0]['direction'] == 'increase' else 'failed'
                for x in row['prediction_plan']['branches']}
        if self.fault == 'subject': receipt['subject_digest'] = '0' * 64
        if self.fault == 'nonboolean': observations[0]['signature_verified'] = 'true'
        if self.fault == 'same_observation': observations[1]['observation_digest'] = observations[0]['observation_digest']
        if self.fault == 'foreign_source': observations[1]['source_group'] = 'foreign'
        if self.fault == 'unknown_classification' and prediction:
            receipt['status'] = 'unknown'
            for obs in observations: obs['status'] = 'unknown'
            receipt['classifications'] = {'h1': 'consistent', 'h2': 'failed'}
        return FrozenRecord.from_dict(receipt)

    def verify_stage(self, subject): return self._receipt(subject)
    def verify_prediction_outcome(self, subject): return self._receipt(subject, prediction=True)


def _item(task, csv, authority, level=4, branches=None, program=PROGRAM):
    program_hash = sha256(program.replace('\n', os.linesep).encode()).hexdigest()
    inputs = {'data_csv': {'sha256': sha256(csv.read_bytes()).hexdigest(), 'byte_count': len(csv.read_bytes())}}
    contracts = {}
    for i, stage in enumerate(_STAGES):
        proof_binding = {'program_sha256': program_hash, 'input_artifacts': [{'artifact_id': k, **v} for k, v in inputs.items()],
            'observation': ({'sum': 1.0, 'negative_control': 0.0} if i >= 2 else {'available': True}) if i < level else None,
            'stage': stage, 'task_digest': task.content_hash}
        contract_id = FrozenRecord.from_dict(proof_binding).content_hash
        pair = [{'authority_id': aid, 'source_group': task.identity.group_id + ':replication:' + aid if stage == 'independent_result' else task.identity.group_id} for aid in authority.keys]
        contracts[stage] = {'source_id': task.identity.group_id, 'contract_id': contract_id, 'authorities': pair}
        for a in pair:
            authority.sources[(contract_id, a['authority_id'])] = {**proof_binding, 'observer': a['authority_id'], 'source_group': a['source_group']}
    row = {'source_id': task.identity.group_id, 'program': program, 'program_sha256': program_hash, 'image': IMAGE, 'inputs': inputs,
        'closure': {'data_version': 'synthetic-v1', 'minimum_artifact_digest': program_hash, 'negative_control_id': 'subtract_self', 'execution_units': 1, 'token_units': 0},
        'stage_contracts': contracts, 'measurement_contract': {'source_id': task.identity.group_id, 'contract_id': 'synthetic-subtract-self', 'discriminator_id': 'd', 'observable': 'x', 'negative_control_id': 'subtract_self'},
        'verification_budget': {'stage_calls': 4, 'prediction_calls': int(branches is not None), 'cost_accounting': 'authority_reported_or_unknown'}}
    if branches is not None: row['branches'] = branches
    return row


def _compile(tmp_path, monkeypatch, *, program=PROGRAM, runner=None):
    csv = tmp_path / 'data.csv'; csv.write_text('x\n1', encoding='utf-8')
    tasks = {name: _task(name) for name in ('blade', 'discoverybench')}; authority = _Authority(); bundles = {}
    for task in tasks.values():
        q51 = {name: _item(task, csv, authority, level=i, program=program) for i, name in enumerate(('subjective', 'data', 'minimal_run', 'measurement', 'independent'))}
        q52 = {'zero_exit_same_prediction': _item(task, csv, authority, branches=_branches(False), program=program), 'negative_control': _item(task, csv, authority, branches=_branches(True), program=program)}
        bundles[task.content_hash] = freeze_feasibility_panel_bundle(task, q51=q51, q52=q52)
    def inject(spec, variant, *, inputs):
        body = base_scenario(spec, variant, inputs=inputs).data()
        body['controller_input'] = dict(feasibility_panel_injection(spec.experiment_id, variant, task=inputs.task, evidence=inputs.evidence))
        return FrozenRecord.from_dict(body)
    monkeypatch.setattr(panel_plan, 'scenario', inject)
    broker = DockerExecutionBroker([tmp_path], **({'runner': runner} if runner else {}))
    resolver = lambda _task, _bundle: {'data_csv': csv}
    local = dict(panel_runner.DRIVERS); install_drivers(local, broker=broker, input_resolver=resolver, authority=authority)
    monkeypatch.setattr(panel_runner, 'DRIVERS', local)
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={'prompt': {'instructions': 'synthetic'}}, search_cost=0)
    control = FrozenRecord.from_dict({'control': 'fixed'}); grids = obligation_grids(('Q5.1', 'Q5.2'), baseline_digest='f' * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage='feasibility', scope_ids=('Q5.1', 'Q5.2'), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({'calls': 3}), baseline_digest='f' * 64, p0_control=control, packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({'scorer': 'none'}), acceptance_criteria=FrozenRecord.from_dict({'engineering': True}))
    return compiled, tasks, authority, broker, csv


def _expected(public):
    stages = [v['status'] for v in public['stages'].values() if v is not None]
    if public['execution']['status'] != 'succeeded' or public['prediction']['identifiable'] is False or 'failed' in stages or public['prediction']['status'] == 'failed': return 'stop'
    if any(x in ('unknown', 'blocked') for x in stages) or public['prediction']['status'] == 'unknown': return 'defer'
    return 'continue'  # fixtures declare feasible when no objective observation is exposed


def _model(seen, wrong=False):
    def call(request):
        row = request.data(); seen.append(row); encoded = FrozenRecord.from_dict(row).encoded
        for marker in ('"variant"', '"arm_id"', '"enabled_modules"', '"argv"', '"path"', 'feasibility-repair', 'M7_ON_SECRET'):
            assert marker not in encoded
        if row['slot'] == 'subjective':
            assert row['execution_feedback'] == [] and 'execution' not in row['module_context']
            assert 'program' in row['module_context']['public_material']
            return FrozenRecord.from_dict({'feasibility': 'feasible', 'rationale': 'synthetic subjective input'})
        if row['slot'] == 'diagnostic':
            return FrozenRecord.from_dict({'decision': 'continue' if wrong else _expected(row['module_context']['observation']), 'rationale': 'public observations control diagnostic'})
        decision = row['module_context']['diagnostic']['decision']
        return FrozenRecord.from_dict({'objective_digest': row['module_context']['required_objective_digest'], 'outcome': 'invalid' if decision == 'stop' else 'unknown', 'evidence_ids': [], 'conclusion': 'bounded synthetic diagnostic', 'programme_complete': False})
    return call


def _run(compiled, tasks, cell, tmp_path, seen, **kwargs):
    return panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({'objective': 'public feasibility'}), sidecar=tmp_path, model=_model(seen, **kwargs), audit_verifier=AuditVerifier({'a': b'a' * 32, 'b': b'b' * 32}))


def _events(result):
    return [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text().splitlines()]


def _cell(compiled, scope='Q5.2', variant='negative_control', modules=('M4','M7')):
    return next(c for c in compiled.panel.cells if c.coverage_id == scope and c.variant == variant and all(m in c.runtime_arm.data()['enabled'] for m in modules))


def test_full_36_cell_grid_real_docker_causal_decisions_and_matched_opportunities(tmp_path, monkeypatch):
    compiled, tasks, authority, _, _ = _compile(tmp_path, monkeypatch); runs=[]; decisions={}
    for i, cell in enumerate(compiled.panel.cells):
        seen=[]; before=len(authority.calls)
        result=_run(compiled,tasks,cell,tmp_path/'M7_ON_SECRET'/str(i),seen); events=_events(result)
        assert result.runtime.status == 'succeeded'
        assert result.call_plan.data()['model_calls'] == 3 and result.call_plan.data()['execution_attempts'] == 1
        calls=4 if cell.coverage_id=='Q5.1' else 5
        assert len(authority.calls)-before == calls
        requests=[e for e in events if e['stage']=='feasibility_verifier_request']
        results=[e for e in events if e['stage']=='feasibility_verifier_result']
        assert len(requests)==len(results)==calls and sum(e['data']['cost']['units'] for e in results)==calls
        for request in requests:
            assert request['data']['cost']['units'] is None
            assert events.index(request)<next(j for j,e in enumerate(events) if e['stage']=='feasibility_verifier_result' and e['data']['call_id']==request['data']['call_id'])
        public=seen[1]['module_context']['observation']; decision=_expected(public)
        decisions[(cell.identity.benchmark,cell.coverage_id,cell.variant,tuple(cell.runtime_arm.data()['enabled']))]=decision
        assert seen[2]['module_context']['diagnostic']['decision']==decision
        assert events[-1]['data']['decision']==('invalid' if decision=='stop' else 'unknown')
        assert events[-1]['data']['scientific_validated'] is False
        if cell.coverage_id=='Q5.2' and cell.variant=='zero_exit_same_prediction' and 'M4' in cell.runtime_arm.data()['enabled']:
            assert decision=='stop' and any(e['data'].get('stage')=='m4_prediction_rejected' for e in events)
        if cell.coverage_id=='Q5.2' and cell.variant=='negative_control' and 'M4' in cell.runtime_arm.data()['enabled']:
            bound=next(e['data'] for e in events if e['data'].get('stage')=='prediction_outcome_bound')
            assert bound['update']['per_hypothesis']=={'h1':'consistent','h2':'failed'}
        runs.append(result.runtime)
    assert len(runs)==36 and PanelReceiptVerifier().verify(compiled.panel,tuple(runs)).observed_cells==36
    assert any(k[1:3]==('Q5.1','subjective') and v=='defer' for k,v in decisions.items())
    assert any(k[1:3]==('Q5.1','subjective') and v=='continue' for k,v in decisions.items())
    assert any(k[1:3]==('Q5.2','zero_exit_same_prediction') and 'M4' not in k[3] and 'M7' in k[3] and v=='stop' for k,v in decisions.items())


@pytest.mark.parametrize('fault',['transport','subject','nonboolean','same_observation','foreign_source','unknown_classification','bad_signature'])
def test_verifier_failures_keep_attempts_costs_and_close_before_final(tmp_path,monkeypatch,fault):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch); authority.fault=fault; seen=[]
    result=_run(compiled,tasks,_cell(compiled),tmp_path/'run',seen); events=_events(result)
    assert result.runtime.status=='failed' and len(authority.calls)==5 and len(seen)==1
    assert result.call_plan.data()['execution_attempts']==1
    failures=[e for e in events if e['stage']=='feasibility_verifier_failure']
    assert failures and all(e['data']['cost']['units'] is None for e in failures)
    assert len([e for e in events if e['stage']=='feasibility_verifier_request'])==5
    if fault!='transport': assert all(e['data']['reported_cost']['units']==1 for e in failures)


@pytest.mark.parametrize('status',['unknown','failed','data_unknown','data_failed'])
def test_nonpassed_measurement_never_definitely_classifies(tmp_path,monkeypatch,status):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch); authority.fault=status; seen=[]
    result=_run(compiled,tasks,_cell(compiled),tmp_path/'run',seen)
    assert result.runtime.status=='succeeded'
    assert seen[1]['module_context']['observation']['prediction']['classifications']=={'h1':'unknown','h2':'unknown'}
    assert seen[2]['module_context']['diagnostic']['decision']==('stop' if status.endswith('failed') else 'defer')


@pytest.mark.parametrize('mutation',['branches','boolean_budget','budget_limit','unpinned_image','measurement','program_hash','authority','independent_source'])
def test_malformed_material_rejected_preflight(tmp_path,monkeypatch,mutation):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch); cell=_cell(compiled)
    body=compiled.scenarios[cell.key].data(); raw=body['controller_input']['bundle']; item=raw['q52']['negative_control']
    if mutation=='branches': item['branches']=[None,None]
    elif mutation=='boolean_budget': item['closure']['token_units']=True
    elif mutation=='budget_limit': item['verification_budget']['stage_calls']=True
    elif mutation=='unpinned_image': item['image']='python:latest'
    elif mutation=='measurement': item['measurement_contract']={'anything':True}
    elif mutation=='program_hash': item['program_sha256']='0'*64
    elif mutation=='authority': item['stage_contracts']['data']['authorities'][1]['authority_id']='synthetic-a'
    elif mutation=='independent_source': item['stage_contracts']['independent_result']['authorities'][1]['source_group']=cell.identity.group_id
    bundle=FrozenRecord.from_dict(raw); body['base']['evidence']=bundle.content_hash
    scenario=FrozenRecord.from_dict(body); changed=replace(cell,scenario_digest=scenario.content_hash)
    compiled=replace(compiled,scenarios={**compiled.scenarios,changed.key:scenario}); seen=[]
    result=_run(compiled,tasks,changed,tmp_path/'run',seen)
    assert result.runtime.status=='failed' and not seen and not authority.calls
    assert result.call_plan.data()['execution_attempts']==0


def test_failed_execution_cannot_qualify_later_stages(tmp_path,monkeypatch):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch,program='raise SystemExit(3)\n'); seen=[]
    result=_run(compiled,tasks,_cell(compiled),tmp_path/'run',seen)
    assert result.runtime.status=='succeeded'  # completed diagnostic, actual execution remains failed
    public=seen[1]['module_context']['observation']
    assert public['execution']['status']=='failed' and public['stages']['minimal_run']['status']=='failed'
    assert public['stages']['discriminating_measurement']['status']=='blocked'
    assert seen[2]['module_context']['diagnostic']['decision']=='stop'
    receipt=next(e['data']['receipt'] for e in _events(result) if e['stage']=='feasibility_verifier_response' and e['data']['subject']['stage']=='minimal_run')
    for obs in receipt['observations']: obs['status']='passed'
    receipt['status']='passed'
    subject=authority.calls[1]
    with pytest.raises(ContractError,match='failed execution'):
        _verified(FrozenRecord.from_dict(receipt),FrozenRecord.from_dict(subject),prediction=False)


def test_execution_receipt_csv_drift_is_rejected_after_real_attempt(tmp_path,monkeypatch):
    compiled,tasks,authority,broker,csv=_compile(tmp_path,monkeypatch); execute=broker.execute
    def changed(request):
        csv.write_text('x\n2',encoding='utf-8')
        return execute(request)
    monkeypatch.setattr(broker,'execute',changed); seen=[]
    result=_run(compiled,tasks,_cell(compiled),tmp_path/'run',seen)
    assert result.runtime.status=='failed' and len(seen)==1 and not authority.calls
    assert result.call_plan.data()['execution_attempts']==1
    actual=next(e['data']['receipt'] for e in _events(result) if e['stage']=='execution_result')
    assert actual['record']['input_artifacts']['data_csv']['sha256']==sha256(csv.read_bytes()).hexdigest()


def test_model_cannot_override_module_stop(tmp_path,monkeypatch):
    compiled,tasks,_,_,_=_compile(tmp_path,monkeypatch); seen=[]
    result=_run(compiled,tasks,_cell(compiled,variant='zero_exit_same_prediction'),tmp_path/'run',seen,wrong=True)
    assert result.runtime.status=='failed' and len(seen)==2


@pytest.mark.parametrize('field',['prediction_plan_digest','discriminator_id','measurement_receipt_digest','execution_digest'])
def test_prediction_receipt_cannot_replay_to_changed_subject(tmp_path,monkeypatch,field):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch); seen=[]
    result=_run(compiled,tasks,_cell(compiled),tmp_path/'run',seen)
    response=next(e['data'] for e in _events(result) if e['stage']=='feasibility_verifier_response' and e['data']['kind']=='prediction_calls')
    subject=response['subject']; subject[field]='foreign'
    with pytest.raises(ContractError,match='subject'):
        _verified(FrozenRecord.from_dict(response['receipt']),FrozenRecord.from_dict(subject),prediction=True)


@pytest.mark.parametrize('mutation',['csv_preflight','controls_false','controls_string','controls_extra','budget'])
def test_preflight_precedes_subjective_and_execution(tmp_path,monkeypatch,mutation):
    compiled,tasks,authority,broker,csv=_compile(tmp_path,monkeypatch); cell=_cell(compiled)
    body=compiled.scenarios[cell.key].data()
    if mutation=='csv_preflight': csv.write_text('x\n2',encoding='utf-8')
    elif mutation=='controls_false': body['controls']['same_budget']=False
    elif mutation=='controls_string': body['controls']['same_task']='true'
    elif mutation=='controls_extra': body['controls']['extra']=True
    elif mutation=='budget': body['base']['budget']='not-a-digest'
    scenario=FrozenRecord.from_dict(body); changed=replace(cell,scenario_digest=scenario.content_hash)
    compiled=replace(compiled,scenarios={**compiled.scenarios,changed.key:scenario}); seen=[]
    result=_run(compiled,tasks,changed,tmp_path/'run',seen)
    assert result.runtime.status=='failed' and not seen and not authority.calls
    assert result.call_plan.data()['execution_attempts']==result.call_plan.data()['model_calls']==0


def test_subjective_is_prospective_and_execution_failure_preserves_its_cost(tmp_path,monkeypatch):
    compiled,tasks,authority,broker,_=_compile(tmp_path,monkeypatch); cell=_cell(compiled); seen=[]; order=[]
    model=_model(seen)
    def checked_model(request):
        if request.data()['slot']=='subjective':
            assert not order
            assert request.data()['execution_feedback']==[]
            assert 'execution' not in request.data()['module_context']
            order.append('subjective')
        return model(request)
    def failed_execution(request):
        assert order==['subjective']
        order.append('execution')
        raise OSError('controlled execution infrastructure failure')
    monkeypatch.setattr(broker,'execute',failed_execution)
    result=panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({'objective':'public feasibility'}),sidecar=tmp_path/'run',model=checked_model,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    assert result.runtime.status=='failed' and order==['subjective','execution'] and not authority.calls
    assert result.call_plan.data()['model_calls']==result.call_plan.data()['execution_attempts']==1
    events=_events(result)
    assert next(i for i,e in enumerate(events) if e['stage']=='model_response') < next(i for i,e in enumerate(events) if e['stage']=='execution_request')

def test_q51_gate_failure_changes_actual_final_with_matched_work(tmp_path,monkeypatch):
    compiled,tasks,authority,_,_=_compile(tmp_path,monkeypatch); authority.fault='failed'; outcomes={}
    cells=[c for c in compiled.panel.cells if c.coverage_id=='Q5.1' and c.variant=='independent' and c.identity.benchmark=='blade']
    for index,cell in enumerate(cells):
        seen=[]; before=len(authority.calls)
        result=_run(compiled,tasks,cell,tmp_path/str(index),seen)
        assert result.runtime.status=='succeeded' and len(authority.calls)-before==4
        assert result.call_plan.data()['model_calls']==3 and result.call_plan.data()['execution_attempts']==1
        enabled='M7' in cell.runtime_arm.data()['enabled']
        outcomes[enabled]=_events(result)[-1]['data']['decision']
        assert seen[2]['module_context']['diagnostic']['decision']==('stop' if enabled else 'continue')
    assert outcomes=={True:'invalid',False:'unknown'}
