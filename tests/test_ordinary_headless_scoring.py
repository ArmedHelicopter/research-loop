"""Ordinary Q3.1: native producer, live Docker, private native scorer and closure."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from evaluation.modular.linked_scoring import issue_linked_score_input, verify_linked_adapted_receipt
from evaluation.modular.scorer_process import LinkedScorerProcessClient, headless_evaluator_descriptor
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.benchmark_cell import verify_linked_benchmark_cell
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import compile_train_panel
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError, canonical
from helpers.headless_train_provider import headless_train_provider
from test_headless_train_controllers import _native_body, _response
from test_modular_linked_train_controller import _linked_config, AUDIT
from test_modular_train_controller import snapshot_and_custody
from test_headless_evaluator_factory import native_spec
from test_scorer_process import _config as scorer_config
from test_train_adapted_selection import EXEC, SCORER


def setup(root, patch):
    snapshot, custody = snapshot_and_custody(root)
    old = _linked_config(custody, snapshot, root).data()
    packets = TrainPacketExporter(custody, snapshot, root/'material').export(old['item_ids'])
    tasks = {p.task.content_hash: p.task for p in packets}
    def response(request):
        body = request.data()
        if body['slot'] == 'analysis_program':
            context = body['module_context']['predecessor_context']
            assert context
            return {'analysis': 'Count the supplied public rows after reading the frozen precursor.',
                'program': "import csv,json\nwith open('/input/public_csv',newline='') as f:\n rows=list(csv.DictReader(f))\nprint(json.dumps({'rows':len(rows)}))"}
        return _response(request)
    provider, calls, gets = headless_train_provider(root/'p', patch, schemas=old['schemas'],
        max_calls=old['max_calls'], response=response, timeout_seconds=600)
    rubric = ScorerConfig.create(benchmark='core_pair', evaluator_id='fixture', version='v1',
                                rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest())
    data = _native_body(old, provider); data['scorer'] = rubric.record.data()
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict(data))
    compiled = compile_train_panel(stage=data['stage'], scope_ids=tuple(data['scope_ids']), tasks=tuple(tasks.values()),
        evidence_by_task={k:FrozenRecord.from_dict(v) for k,v in data['evidence_by_task'].items()},
        budget=FrozenRecord.from_dict(data['budget']), baseline_digest=data['baseline_digest'],
        p0_control=FrozenRecord.from_dict(data['p0_control']),
        packages_by_arm={k:CandidatePackage(FrozenRecord.from_dict(v)) for k,v in data['packages_by_arm'].items()},
        scorer=rubric.record, acceptance_criteria=FrozenRecord.from_dict(data['acceptance_criteria']), replicates=('r1',))
    server = scorer_config(root, {'panel':compiled.panel, 'tasks':tasks, 'config':rubric})
    with pytest.MonkeyPatch.context() as private_patch:
        spec, _, _ = native_spec(root/'e', private_patch)
    spec.update(max_calls=12, max_tokens=12*131072, timeout_seconds=600,
        evaluator_id=rubric.record.data()['evaluator_id'], evaluator_version=rubric.record.data()['version'])
    server['evaluator'] = spec
    path = root/'server.json'; path.write_text(canonical(server),encoding='utf-8')
    return dict(root=root,snapshot=snapshot,custody=custody,provider=provider,calls=calls,gets=gets,
        rubric=rubric,frozen=frozen,compiled=compiled,server=server,path=path)


def client(value, *, provider_digest=None, journal='client.jsonl'):
    root=value['root']; path=value['path']
    provider=headless_evaluator_descriptor(value['server']['evaluator'])
    descriptor={'kind':'grok-headless-frozen-evaluator-v1',
        'configuration_digest':provider_digest or provider['configuration_digest']}
    return LinkedScorerProcessClient(panel=value['compiled'].panel, config=value['rubric'],
        command=[sys.executable,str(Path(__file__).parent/'helpers/headless_evaluator_process.py'),
            '--config',str(path),'--config-sha256',hashlib.sha256(path.read_bytes()).hexdigest(),
            '--journal',str(root/'worker.jsonl')], journal_path=root/journal,
        task_handle_bindings={key:hashlib.sha256(handle.encode()).hexdigest() for key,handle in value['server']['task_handles'].items()},
        execution_authority_keys={EXEC.authority_id:EXEC.key}, scorer_authority_keys={SCORER.authority_id:SCORER.key},
        evaluator_provider=descriptor, response_timeout_seconds=720,
        environment={**os.environ,'PYTHONIOENCODING':'utf-8'})


def test_all_twelve_cells_reach_native_solve_live_docker_private_score_and_signed_closure(tmp_path,monkeypatch):
    value=setup(tmp_path,monkeypatch)
    service=client(value)
    try:
        result=run_train_panel(value['frozen'],custody=value['custody'],snapshot_root=value['snapshot'],
            export_root=tmp_path/'export',run_root=tmp_path/'run',model=value['provider'],audit_verifier=AuditVerifier(AUDIT))
        assert result.receipt.data()['execution_status']=='engineering_complete'
        assert len(result.linked_results)==len(result.compiled.panel.cells)==12
        assert len(value['calls'])==48
        assert result.receipt.data()['provider_final_gate']['provider_evidence_eligible'] is True
        receipts=[]; inputs=[]
        for row in result.linked_results:
            task=result.compiled.tasks[row.cell.task_digest]; scenario=result.compiled.scenarios[row.cell.key]
            package=result.compiled.packages[row.cell.runtime_arm.content_hash]
            assert verify_linked_benchmark_cell(row,task=task,scenario=scenario,package=package).data()['engineering_verified']
            assert json.loads(row.solver.execution.record.data()['stdout'])['rows']==1
            linked=issue_linked_score_input(panel=result.compiled.panel,result=row,task=task,scenario=scenario,package=package,authority=EXEC)
            score=service.submit(cell_key=row.cell.key,linked_input=linked)
            verify_linked_adapted_receipt(score,authority_keys={SCORER.authority_id:SCORER.key},config=value['rubric'],
                panel=result.compiled.panel,cell=row.cell,linked_input=linked,execution_authority_keys={EXEC.authority_id:EXEC.key})
            receipts.append(score); inputs.append(linked)
        closure=service.finalize_headless_evaluator(receipts=receipts)
        assert closure.data()['body']['scope']['unscored_cell_count']==0
        assert service.finalize_headless_evaluator(receipts=receipts)==closure
        with pytest.raises(ContractError,match='finalized'):
            service.submit(cell_key=result.linked_results[0].cell.key,linked_input=inputs[0])
        with pytest.raises(ContractError,match='sequence differs'):
            service.finalize_headless_evaluator(receipts=receipts[:-1])
        from evaluation.modular.scorer_process import build_service, parse_server_config
        from evaluation.modular.headless_evaluator_closure import finalize
        journal=[json.loads(line) for line in (tmp_path/'worker.jsonl').read_text(encoding='utf-8').splitlines()]
        altered=[]
        for item in journal:
            if item['status']=='succeeded':
                wrong={**item['receipt']['body'],'schema':'combination-adapted-scored-cell-v1'}
                item={**item,'receipt':SCORER.issue(wrong).data()}
                altered.append(FrozenRecord.from_dict(item['receipt']).content_hash)
        wrong_journal=tmp_path/'wrong-family.jsonl'
        wrong_journal.write_text(''.join(canonical(item)+'\n' for item in journal),encoding='utf-8')
        # Keep the real worker journal unchanged; a second independent reader
        # rejects even correctly signed receipts from the wrong panel family.
        for index,item in enumerate(journal):
            if item['status']=='succeeded':
                journal[index]={**item,'receipt':SCORER.issue({**item['receipt']['body'],
                    'schema':'combination-adapted-scored-cell-v1'}).data()}
        wrong_journal.write_text(''.join(canonical(item)+'\n' for item in journal),encoding='utf-8')
        verifier=build_service(parse_server_config(value['server']))
        with pytest.raises(ContractError,match='untrusted authority receipt'):
            finalize(service=verifier,panel=result.compiled.panel,journal_path=wrong_journal,nonce='wrong-family',receipt_digests=altered)
        (tmp_path/'independent-readback.json').write_text(canonical({'expected_cells':12,'producer_calls':48,
            'receipts':[r.receipt.data() for r in receipts],'closure':closure.data(),'scientific_effect':'not_measured'}),encoding='utf-8')
    finally:
        service.close()
    for path in (tmp_path/'client.jsonl',tmp_path/'worker.jsonl'):
        assert 'PRIVATE-REFERENCE-SENTINEL' not in path.read_text(encoding='utf-8')


def test_wrong_provider_binding_rejects_before_model_dispatch(tmp_path,monkeypatch):
    value=setup(tmp_path,monkeypatch)
    with pytest.raises(ContractError,match='startup binding differs'):
        client(value,provider_digest='0'*64)
    assert not value['calls']
    ledger=Path(value['server']['evaluator']['work_root'])/'ledger.json'
    assert not ledger.exists() or json.loads(ledger.read_bytes())['calls']==[]


def test_incomplete_ordinary_binding_rejects_before_child_creation(tmp_path):
    with pytest.raises(ContractError,match='complete exact FrozenPanel'):
        LinkedScorerProcessClient(panel=None,config=object(),command=['must-not-run'],journal_path=tmp_path/'no.jsonl')
    assert not (tmp_path/'no.jsonl').exists()


@pytest.mark.parametrize('field', ['evaluator_id','evaluator_version'])
def test_worker_rejects_mismatched_native_identity_before_allocator(tmp_path,monkeypatch,field):
    from evaluation.modular.scorer_process import build_service, parse_server_config
    value=setup(tmp_path,monkeypatch)
    server=value['server']; server['evaluator'][field]='foreign'
    with pytest.raises(ContractError,match='identity or rubric differs'):
        build_service(parse_server_config(server))
    assert not value['calls']
    assert not (Path(server['evaluator']['work_root'])/'ledger.json').exists()
