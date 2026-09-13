"""Prospective custody, real Codex fixture port, Docker and independent scorer grid.

All source/reference material here is synthetic; rubric numbers test plumbing only.
"""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.state_prediction_combination_controller import (
    FrozenStatePredictionTrainConfig, compile_state_prediction_train_panels,
    run_state_prediction_train_panels, _arms,
)
from research_loop.modular.state_prediction_combination_driver import DESIGNS, SLOTS, verify_state_prediction_combination_cell
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.ontology import ContractError, canonical
from test_remaining_prospective_train_sources import prepared_primary, changed_source_config, corrupt_export
from test_primary_prospective_exporter import events
from test_lineage_combination_controller import _fixture, _sources, EXECUTION, SCORER
from test_admission_combination import sources
from test_modular_train_controller import model_port, SCENARIO, FINAL
from test_modular_combination_train_controller import ANALYSIS
from test_modular_combination_benchmark_driver import _plan, _rewrite_trace, IMAGE
from test_scorer_process import _store, _command


def prepare(root, *, fault=None):
    exporter, selected, all_items, packets = prepared_primary(root)
    calls = []
    verifiers = {pair: (sources(calls, fault=fault, root=root/'run') if pair == 'pair:M1+M4'
        else _sources(calls, fault='exception' if fault == 'source_exception' else None, run_root=root/'run'))
        for pair in DESIGNS}
    _, custody, old_packets, legacy, _, _ = _fixture(root/'legacy', _sources([]))
    b = legacy.data()
    materials = {}
    for pair in DESIGNS:
        materials[pair] = {}
        for packet in packets:
            previous = next(p for p in old_packets if p.task.identity.benchmark == packet.task.identity.benchmark)
            material = legacy.data()['materials_by_task'][previous.task.content_hash]
            material.update(identity=packet.task.identity.data(), task_digest=packet.task.content_hash)
            material['public_artifacts'][0]['artifact'].update(sha256=hashlib.sha256(packet.csv_path.read_bytes()).hexdigest(),
                byte_count=packet.csv_path.stat().st_size)
            for row in material['originals'] + material['claims']:
                row['subject_bindings']['task'] = packet.task.identity.task_id
            if pair == 'pair:M1+M4':
                material.update(schema='admission-combination-material-v1', withdrawals=[])
                material['originals'].append({'key':'uncalibrated','root_material':{'observation':'instrument-c'},
                    'content':{'x':99},'subject_bindings':material['originals'][0]['subject_bindings']})
                material['qualification_observations'] = {
                    'before': {'old':{'effect':1,'calibration_error':0},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}},
                    'after': {'old':{'effect':1,'calibration_error':2},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}}}
            materials[pair][packet.task.content_hash] = material
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt':{'instructions':'Analyze the supplied public training observations.'}}, search_cost=0)
    store, handles, manifest_sha = _store(root, {'tasks':{p.task.content_hash:p.task for p in packets}})
    b.pop('materials_by_task'); b.pop('source_verifier_binding')
    b.update(schema='state-prediction-combination-train-config-v2', export_mode='primary_prospective',
        stage='synthetic-prospective-state-prediction', item_ids=[i.token for i in selected],
        task_bindings={i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size}
            for i,p in zip(selected, packets, strict=True)},
        packages_by_arm={a:package.record.data() for a in _arms(b['baseline_digest'])},
        scorer=ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-primary',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        scorer_handle_bindings={k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        materials_by_pair=materials, source_verifier_bindings={p:v.binding().data() for p,v in verifiers.items()},
        max_calls=72, schemas={'m4_plan':SCENARIO,'analysis_program':ANALYSIS,'final_answer':FINAL},
        allocation={'model_slots_per_cell':list(SLOTS),'docker_attempts_per_cell':1,'scorer_calls_per_cell':1,
            'scorer_call_limit':24,'scorer_token_accounting':'transport_not_provided','source_calls_per_cell':2})
    config = FrozenStatePredictionTrainConfig(FrozenRecord.from_dict(b))
    compiled = compile_state_prediction_train_panels(config, packets)
    # Make the prior fixture store and CSVs unusable before any execution. Their
    # identities/material shapes seeded fixtures; they are not a runtime source.
    for path in (root/'legacy').rglob('*'):
        if path.is_file(): path.write_bytes(b'UNUSABLE LEGACY FIXTURE')
    (root/'frozen-config.json').write_text(config.record.encoded+'\n',encoding='utf-8')
    return dict(root=root, exporter=exporter, selected=selected, all_items=all_items, packets=packets,
        custody=custody, config=config, compiled=compiled, verifiers=verifiers, calls=calls,
        store=store, handles=handles, manifest_sha=manifest_sha)


def services(setup, stack):
    root=setup['root']; b=setup['config'].data(); rubric=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
    (root/'execution.key').write_bytes(EXECUTION.key); (root/'score.key').write_bytes(SCORER.key)
    clients={}
    for n,panel in enumerate(setup['compiled'].panels):
        server={'schema':'state-prediction-scorer-process-config-v1',
            'panel':serialize_combination_panel(panel,state_prediction=True),'scorer_config':rubric.record.data(),
            'scorer_config_digest':rubric.digest,'train_reference_store':{'root':str(setup['store'].resolve()),
                'manifest_sha256':setup['manifest_sha'],'inventory_digest':panel.cells[0].identity.dataset_version,
                'split_digest':panel.split_digest},'task_handles':setup['handles'],
            'execution_authority_key_files':{EXECUTION.authority_id:str(root/'execution.key')},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str(root/'score.key')},'evaluator':{'synthetic_mode':'normal'}}
        path=root/f'server-{n}.json';path.write_text(canonical(server),encoding='utf-8')
        command=_command(path,root/f'worker-{n}.jsonl')
        command[1]=str((Path(__file__).parent/'helpers/state_prediction_scorer_process_helper.py').resolve())
        client=CombinationScorerProcessClient(panel=panel,config=rubric,state_prediction=True,command=command,
            journal_path=root/f'client-{n}.jsonl',task_handle_bindings=b['scorer_handle_bindings'],
            execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
            environment={**os.environ,'PYTHONIOENCODING':'gbk'})
        stack.callback(client.close);clients[panel.obligation_id]=client
    return clients


def invoke(setup, monkeypatch, *, fault=None):
    root=setup['root'];config=setup['config'];b=config.data();seen=[]
    def response(request):
        data=request.data();seen.append(data)
        assert all(marker not in request.encoded for marker in ('PRIVATE-REFERENCE-SENTINEL','"arm_id"','"enabled"','"truth"'))
        frozen=json.loads((root/'run/controller-attempt.json').read_text(encoding='utf-8'))
        assert len(frozen['cells'])==24 and len(frozen['panels'])==3
        assert [(p['digest'],p['cells']) for p in frozen['panels']] == [(p.digest,[c.data() for c in p.cells]) for p in setup['compiled'].panels]
        if len(seen)==1:
            assert frozen['actual_scorer_calls']==0
            assert all(r['status']=='not_started' for r in frozen['cells'][1:])
            if fault=='poison':raise RuntimeError('synthetic unknown model usage')
        if data['slot']=='m4_plan':
            state=data['module_context']['state_projection']
            assert state['observations']
            plan=_plan();plan['question'] += ' State '+FrozenRecord.from_dict(state).content_hash
            return FrozenRecord.from_dict(plan)
        if data['slot']=='analysis_program':
            joint=data['module_context']['joint_mechanism'];assert joint['proposal']['question'].endswith(FrozenRecord.from_dict(joint['state_projection']).content_hash)
            return FrozenRecord.from_dict({'analysis':'Use the actual state and actual prediction proposal.',
                'program':"import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))\nprint("+repr(joint['proposal']['question'])+")"})
        assert data['execution_feedback'][0]['status']=='succeeded'
        return FrozenRecord.from_dict({'objective_digest':data['module_context']['required_objective_digest'],
            'outcome':'unknown','evidence_ids':[],'conclusion':'Actual output '+data['execution_feedback'][0]['stdout'],'programme_complete':False})
    port=model_port(root/'port',monkeypatch,max_calls=b['max_calls'],max_tokens=b['max_tokens'],schemas=b['schemas'],response_factory=response)
    def forbidden(*args,**kwargs):raise AssertionError('legacy export route was invoked')
    monkeypatch.setattr(TrainPacketExporter,'export',forbidden)
    exporter=setup['exporter']
    kwargs=dict(custody=None,prospective_exporter=exporter,snapshot_root=Path(exporter.config['snapshot_root']),
        export_root=exporter.output_root,run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
        source_verifiers=setup['verifiers'],execution_authority=EXECUTION,scorer_authority_keys={SCORER.authority_id:SCORER.key})
    no_io={'both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','source','material'}
    if fault=='both':kwargs['custody']=setup['custody']
    if fault=='wrong_port':kwargs.update(custody=setup['custody'],prospective_exporter=None)
    if fault=='roots':kwargs['export_root']=root/'wrong-export'
    if fault=='split':exporter.expected_split_digest='f'*64
    if fault in ('validation','swapped_tokens'):config=changed_source_config(config,setup['all_items'],fault)
    if fault in ('export_receipt','completion_anchor'):corrupt_export(monkeypatch,exporter,fault)
    if fault=='source':
        path=Path(exporter.config['snapshot_root'])/'scienceagent/work/BLADE/blade_bench/datasets/case0/data.csv'
        path.write_bytes(path.read_bytes()+b' ')
    if fault=='material':
        original=exporter.export_controller_packets
        def drift(tokens):
            packets=original(tokens);packets[0].csv_path.write_bytes(b'drift');return packets
        monkeypatch.setattr(exporter,'export_controller_packets',drift)
    with ExitStack() as stack:
        kwargs['scoring_services']=services(setup,stack)
        if fault in no_io:
            with pytest.raises((ContractError,CustodyError)):run_state_prediction_train_panels(config,**kwargs)
            assert not seen and not setup['calls'] and not port.ledger['calls']
            assert not list((root/'run').glob('cells/*/runtime/analysis-1.py'))
            assert not list(root.glob('worker-*.jsonl'))
            return
        result=run_state_prediction_train_panels(config,**kwargs)
    return result,port,seen


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('state-prediction-grid');setup=prepare(root)
    with pytest.MonkeyPatch.context() as patch:
        result,port,seen=invoke(setup,patch)
    return setup,result,port,seen


def test_all_24_prospective_cells_actual_modules_docker_and_scorer(grid):
    setup,result,port,seen=grid
    assert len(result.scores)==len(result.results)==len(result.attempts)==24, [a.data() for a in result.attempts if a.data()['status']!='succeeded']
    assert len(seen)==len(port.ledger['calls'])==72 and len(setup['calls'])==48
    receipt=result.receipt.data()
    assert receipt['status']=='complete_train_engineering'
    assert receipt['actual_docker_attempts']==receipt['actual_scorer_calls']==24
    assert receipt['source_calls']==48 and receipt['pruned_cells']==[]
    assert receipt['validation_opened'] is receipt['scientific_effectiveness_proven'] is False
    assert {p.obligation_id for p in result.compiled.panels}==set(DESIGNS)
    assert [e['event'] for e in events(setup['exporter'])]==['export_reserved','sources_verified','exposure_reserved','exposure_reserved','export_completed']
    for attempt,executed in zip(result.attempts,result.results,strict=True):
        row=attempt.data();assert row['status']=='succeeded' and len(row['source_verification']['calls'])==2
        assert row['docker_attempts']==row['scorer_calls']==1
        assert row['execution_receipt']['image']==IMAGE
        enabled=executed.cell.runtime_arm.data()['enabled']
        if executed.cell.coverage_id=='pair:M3+M4':assert 'M2' in enabled
        journal=executed.runtime.trace_path.parent/'predictions.jsonl'
        assert bool(journal.read_text(encoding='utf-8').strip())==('M4' in enabled)
        assert executed.joint_mechanism.data()['proposal']['question'] in executed.solver.execution.record.data()['stdout']
    for n in range(3):
        worker=[json.loads(l) for l in (setup['root']/f'worker-{n}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(worker)==16


@pytest.mark.parametrize('fault',['both','wrong_port','roots','split','validation','swapped_tokens','export_receipt','completion_anchor','source','material'])
def test_source_faults_precede_downstream_io(tmp_path,monkeypatch,fault):
    invoke(prepare(tmp_path),monkeypatch,fault=fault)


def test_poisoned_model_ledger_keeps_all_remaining_opportunities(tmp_path,monkeypatch):
    setup=prepare(tmp_path);result,port,seen=invoke(setup,monkeypatch,fault='poison')
    b=result.receipt.data()
    assert len(result.attempts)==24 and b['failed_cells']==1 and b['blocked_cells']==23
    assert len(seen)==len(port.ledger['calls'])==1 and port.ledger['usage_incomplete'] is True
    assert b['actual_docker_attempts']==b['actual_scorer_calls']==0
    assert b['unused_model_opportunities']==71 and b['unused_docker_opportunities']==b['unused_scorer_opportunities']==24
    assert b['pruned_cells']==[] and all(c.data()['status']=='inconclusive' for c in result.contrasts)


def test_m1_qualification_drift_preserves_scores_but_blocks_contrast(tmp_path,monkeypatch):
    setup=prepare(tmp_path,fault='source_cell_drift');result,port,seen=invoke(setup,monkeypatch)
    assert len(result.scores)==len(result.attempts)==24 and len(seen)==72
    assert all(a.data()['status']=='succeeded' for a in result.attempts)
    contrasts={p.obligation_id:c.data() for p,c in zip(result.compiled.panels,result.contrasts,strict=True)}
    assert contrasts['pair:M1+M4']['status']=='inconclusive'
    assert contrasts['pair:M1+M4']['reason']=='admission_qualification_semantic_drift'
    assert contrasts['pair:M1+M4']['qualification_drift']
    assert all(contrasts[p]['status']=='estimated' for p in DESIGNS if p!='pair:M1+M4')
    assert result.receipt.data()['status']=='inconclusive'


def test_source_failure_preserves_full_denominator(tmp_path,monkeypatch):
    setup=prepare(tmp_path,fault='source_exception');result,port,seen=invoke(setup,monkeypatch)
    b=result.receipt.data()
    assert len(result.attempts)==len(result.results)==24 and b['pruned_cells']==[]
    assert b['failed_cells']==8 and b['scored_cells']==16
    assert len(seen)==48 and b['actual_docker_attempts']==b['actual_scorer_calls']==16
    assert all(a.data()['source_verification']['calls'] for a in result.attempts)
    assert result.contrasts[0].data()['status']=='inconclusive'


@pytest.mark.parametrize('fault',['original_proposal','proposal_context','model_response','joint','modules','program','registry'])
def test_rehashed_replay_forgeries_fail_closed(grid,fault):
    setup,result,_,_=grid;mutations=[]
    for executed in result.results:
        if executed.cell.identity.benchmark!='blade' or executed.cell.arm_id not in ('00','01'):continue
        panel=next(p for p in result.compiled.panels if executed.cell in p.cells)
        packet=next(p for p in result.compiled.packets if p.task.content_hash==executed.cell.task_digest)
        path=executed.runtime.trace_path;original=path.read_bytes();joint=executed.joint_mechanism.data()
        args=dict(panel=panel,task=packet.task,scenario=result.compiled.scenarios[executed.cell.key],
            package=result.compiled.packages[executed.cell.runtime_arm.content_hash],
            material=result.compiled.materials[panel.obligation_id][executed.cell.task_digest],
            source_verifier=setup['verifiers'][panel.obligation_id],public_inputs={'public_csv':packet.csv_path},
            broker=DockerExecutionBroker([setup['root']/'export',setup['root']/'run']))
        extra=None;saved=None
        def change(rows):
            if fault=='original_proposal':
                target=next(e for e in rows if e['stage']=='state_prediction_plan')['data']
                target['proposal']['question']='forged original';target['proposal_digest']=FrozenRecord.from_dict(target['proposal']).content_hash
            elif fault=='proposal_context':
                target=next(e for e in rows if e['stage']=='model_request')['data'];old=target['request_digest']
                target['request']['module_context']['state_projection']={}
                target['request_digest']=FrozenRecord.from_dict(target['request']).content_hash
                for row in rows:
                    if row['stage']=='model_response' and row['data']['request_digest']==old:row['data']['request_digest']=target['request_digest']
            elif fault=='model_response':
                target=next(e for e in rows if e['stage']=='model_response')['data']
                target['response']['question']='forged response';target['response_digest']=FrozenRecord.from_dict(target['response']).content_hash
            elif fault=='joint':
                joint['proposal']['question']='forged solver proposal'
                target=next(e for e in rows if e['stage']=='state_prediction_joint')['data']
                target.update(joint=joint,joint_digest=FrozenRecord.from_dict(joint).content_hash)
            elif fault=='modules':
                rows[0]['data']['arm']['enabled']=[]
        try:
            if fault in ('program','registry'):
                extra=path.parent/('analysis-1.py' if fault=='program' else 'predictions.jsonl');saved=extra.read_bytes()
                extra.write_bytes(b'print("forged")\n' if fault=='program' else b'{}\n')
                forged=executed
            else:
                tail=_rewrite_trace(path,change)
                forged=replace(executed,joint_mechanism=FrozenRecord.from_dict(joint),runtime=replace(executed.runtime,trace_digest=tail))
            with pytest.raises((ContractError,KeyError,ValueError)):
                verify_state_prediction_combination_cell(forged,**args)
            mutations.append({'pair':panel.obligation_id,'arm':executed.cell.arm_id,'fault':fault})
        finally:
            path.write_bytes(original)
            if extra is not None:extra.write_bytes(saved)
        verify_state_prediction_combination_cell(executed,**args)
    assert {m['pair'] for m in mutations}==set(DESIGNS)
    (setup['root']/f'replay-{fault}.json').write_text(canonical(mutations),encoding='utf-8')
