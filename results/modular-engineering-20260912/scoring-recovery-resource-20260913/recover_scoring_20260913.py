"""Scorer-only recovery of the closed 02 training execution; never rerun solvers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SOURCE = Path('E:/_ryanDev/AI/research-loop-modular/sr-check')
sys.path.insert(0, str(SOURCE))
from evaluation.modular.linked_scoring import LinkedExecutionAuthority, issue_linked_score_input
from evaluation.modular.scorer_process import LinkedScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.benchmark_cell import restore_completed_benchmark_cell
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import compile_train_panel
from research_loop.modular.panel_receipts import RuntimeReceipt
from research_loop.modular.train_controller import FrozenTrainControllerConfig
from research_loop.modular.train_selection import FrozenTrainSelectionRule, measure_and_select_train
from research_loop.ontology import canonical

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
OLD = BASE / 'work/linked-train-scored-20260913-02'
OLD_PRIVATE = BASE / 'custody-private/linked-scorer-runtime-20260913-02'
OUT = BASE / 'work/linked-train-scoring-recovery-20260913-01'
PRIVATE = BASE / 'custody-private/linked-scorer-recovery-20260913-01'
ENV_SOURCE = BASE / 'work/q31-isolated-context/context_environment_v2.py'
EXECUTOR = 'linked-train-executor-20260913-02'
SCORER = 'linked-train-scorer-20260913-02'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, body):
    with path.open('x', encoding='utf-8') as f:
        f.write(canonical(body))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_commit():
    assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=SOURCE, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()

def environment():
    spec = importlib.util.spec_from_file_location('frozen_child_environment', ENV_SOURCE)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.child_environment()

def original_files():
    paths = [*OLD.joinpath('controls').rglob('*'), *OLD.joinpath('export').rglob('*'), *OLD.joinpath('run').rglob('*'),
        OLD / 'model/ledger.json', OLD / 'scorer-client.jsonl', OLD / 'run-failure.json',
        OLD_PRIVATE / 'server-config.json', OLD_PRIVATE / 'evaluator-model/ledger.json', ENV_SOURCE]
    return {str(p): sha(p) for p in sorted(set(paths)) if p.is_file()}

def reconcile_original():
    assert read(OLD / 'run-failure.json')['scored_cells'] == 0
    assert not (OLD_PRIVATE / 'server.jsonl').exists()
    assert not list((OLD / 'scores').glob('*.json'))
    ledger = read(OLD_PRIVATE / 'evaluator-model/ledger.json')
    assert not ledger['calls'] and ledger['tokens'] == 0 and not ledger['usage_incomplete']
    client = [json.loads(line) for line in (OLD / 'scorer-client.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [row['status'] for row in client] == ['reserved', 'unknown']
    config_path = str(OLD_PRIVATE / 'server-config.json')
    ps = "$n=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*evaluation.modular.scorer_process*' -and $_.CommandLine -like '*linked-scorer-runtime-20260913-02*' }).Count; Write-Output $n"
    live = int(subprocess.check_output(['powershell', '-NoProfile', '-Command', ps], text=True).strip())
    assert live == 0
    return {'schema': 'closed-scoring-attempt-reconciliation-v1', 'old_client_statuses': ['reserved', 'unknown'],
        'old_worker_journal_absent': True, 'old_scores': 0, 'old_evaluator_calls': 0, 'old_evaluator_tokens': 0,
        'old_worker_processes': live, 'old_client_preserved': True, 'reason': 'UTF-8 client versus GBK worker stdin; separate fixture reproduced pre-reservation decoding failure',
        'solver_reexecution': False, 'validation_items': 0}

def restore():
    preflight = read(OLD / 'controls/preflight.json')
    config = FrozenTrainControllerConfig.from_path(OLD / 'controls/controller.json', preflight['config_sha256'])
    data = config.data(); attempt = read(OLD / 'run/controller-attempt.json')
    assert attempt['status'] == 'execution_incomplete' and attempt['config_digest'] == config.record.content_hash
    tasks, paths = [], {}
    for p in sorted((OLD / 'export').glob('*/*/public.json')):
        body = read(p); identity = DataIdentity.parse(body['task']['identity']); identity.require_train()
        task = PublicTask.create(identity, body['task']['payload'])
        assert task.content_hash == body['receipt']['packet_hash'] and sha(p.parent / 'data.csv') == body['receipt']['csv_sha256']
        assert body['receipt'] in attempt['packet_receipts']
        tasks.append(task); paths[task.content_hash] = p.parent / 'data.csv'
    assert {f'{t.identity.benchmark}:{t.identity.task_id}' for t in tasks} == set(data['item_ids'])
    packages = {key: CandidatePackage(FrozenRecord.from_dict(value)) for key, value in data['packages_by_arm'].items()}
    compiled = compile_train_panel(stage=data['stage'], scope_ids=tuple(data['scope_ids']), tasks=tasks,
        evidence_by_task={key: FrozenRecord.from_dict(value) for key, value in data['evidence_by_task'].items()},
        budget=FrozenRecord.from_dict(data['budget']), baseline_digest=data['baseline_digest'], p0_control=FrozenRecord.from_dict(data['p0_control']),
        packages_by_arm=packages, scorer=FrozenRecord.from_dict(data['scorer']),
        acceptance_criteria=FrozenRecord.from_dict(data['acceptance_criteria']), replicates=tuple(data['replicates']))
    assert compiled.panel.digest == attempt['panel_digest'] == preflight['panel_digest']
    assert [cell.data() for cell in compiled.panel.cells] == attempt['cell_plan']
    runtimes = {tuple(row['cell_key']): row for row in attempt['runtime_receipts']}
    receipts = {tuple(row['cell_key']): row for row in attempt['linked_receipts']}
    assert len(receipts) == len(runtimes) == len(compiled.panel.cells) == 12
    results = []
    for cell in compiled.panel.cells:
        r, receipt = runtimes[cell.key], receipts[cell.key]
        root = OLD / 'run/cells' / FrozenRecord.from_dict(cell.data()).content_hash
        runtime = RuntimeReceipt(cell.key, r['status'], root / 'mechanism/trace.jsonl', r['trace_digest'], r['output_digest'], r['failure_reason'])
        results.append(restore_completed_benchmark_cell(cell=cell, task=compiled.tasks[cell.task_digest],
            scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], runtime=runtime,
            linked_receipt=FrozenRecord.from_dict(receipt), solver_sidecar=root / 'solver' if receipt['solver_trace_digest'] else None,
            public_inputs={'public_csv': paths[cell.task_digest]}))
    assert [r.status for r in results] == attempt['linked_statuses']
    return compiled, tuple(results), data

def signed_inputs(compiled, results):
    authority = LinkedExecutionAuthority(EXECUTOR, (OLD_PRIVATE / (EXECUTOR + '.key')).read_bytes())
    return {r.cell.key: issue_linked_score_input(panel=compiled.panel, result=r, task=compiled.tasks[r.cell.task_digest],
        scenario=compiled.scenarios[r.cell.key], package=compiled.packages[r.cell.runtime_arm.content_hash], authority=authority)
        for r in results if r.status == 'linked_succeeded'}

def prepare():
    assert not OUT.exists() and not PRIVATE.exists()
    revision = source_commit(); pins = original_files(); reconciliation = reconcile_original()
    compiled, results, data = restore(); inputs = signed_inputs(compiled, results)
    assert len(inputs) == 11 and original_files() == pins
    old_client = json.loads((OLD / 'scorer-client.jsonl').read_text(encoding='utf-8').splitlines()[0])
    material = {'request_id': old_client['request_id'], 'panel_digest': compiled.panel.digest,
        'cell_key': old_client['cell_key'], 'linked_input': inputs[tuple(old_client['cell_key'])].data()}
    assert hashlib.sha256(canonical(material).encode('utf-8')).hexdigest() == old_client['request_digest']
    server = read(OLD_PRIVATE / 'server-config.json')
    assert sha(OLD_PRIVATE / 'server-config.json') == read(OLD / 'controls/preflight.json')['server_config_sha256']
    # All scoring semantics, reference binding and keys remain exactly frozen.
    # Only the isolated evaluator output location changes for this separate attempt.
    server['evaluator']['work_root'] = str(PRIVATE / 'evaluator-model')
    OUT.mkdir(); PRIVATE.mkdir(); (OUT / 'scores').mkdir()
    write(PRIVATE / 'server-config.json', server)
    write(OUT / 'reconciliation.json', reconciliation)
    write(OUT / 'preflight.json', {'schema': 'scorer-only-recovery-preflight-v1', 'source_commit': revision,
        'runner_sha256': sha(Path(__file__)), 'original_file_sha256': pins, 'panel_digest': compiled.panel.digest,
        'server_config_sha256': sha(PRIVATE / 'server-config.json'), 'cells': 12, 'scorable': 11,
        'statuses': [r.status for r in results], 'signed_input_digests': [{'cell_key': list(k), 'digest': v.content_hash} for k,v in inputs.items()],
        'first_unknown_request_exactly_reproduced': True, 'solver_calls': 0, 'validation_items': 0})
    print(canonical({'stage': 'recovery_frozen', 'cells': 12, 'scorable': 11, 'new_solver_calls': 0}), flush=True)

def run():
    preflight = read(OUT / 'preflight.json')
    assert source_commit() == preflight['source_commit'] and sha(Path(__file__)) == preflight['runner_sha256']
    assert original_files() == preflight['original_file_sha256']
    assert not (OUT / 'scorer-client.jsonl').exists() and not (PRIVATE / 'server.jsonl').exists()
    assert sha(PRIVATE / 'server-config.json') == preflight['server_config_sha256']
    reconcile_original(); compiled, results, data = restore(); inputs = signed_inputs(compiled, results)
    assert [{'cell_key': list(k), 'digest': v.content_hash} for k,v in inputs.items()] == preflight['signed_input_digests']
    command = [sys.executable, '-m', 'evaluation.modular.scorer_process', '--config', str(PRIVATE / 'server-config.json'),
        '--config-sha256', preflight['server_config_sha256'], '--journal', str(PRIVATE / 'server.jsonl')]
    client = LinkedScorerProcessClient(panel=compiled.panel, command=command, journal_path=OUT / 'scorer-client.jsonl',
        environment=environment(), response_timeout_seconds=360)
    scores = []
    try:
        for cell in compiled.panel.cells:
            if cell.key not in inputs:
                continue
            signed = inputs[cell.key]; score = client.submit(cell_key=cell.key, linked_input=signed); scores.append(score)
            write(OUT / 'scores' / (FrozenRecord.from_dict(cell.data()).content_hash + '.json'),
                {'cell_key': list(cell.key), 'linked_input': signed.data(), 'score_receipt': score.receipt.data()})
            print(canonical({'stage': 'recovered_adapted_score', 'scored': len(scores), 'expected_scorable': 11, 'all_cells': 12}), flush=True)
    finally:
        client.close()
    selected = measure_and_select_train(panel=compiled.panel,
        rule=FrozenTrainSelectionRule(FrozenRecord.from_dict(data['acceptance_criteria']['train_adapted_selection'])),
        results=results, tasks=compiled.tasks, scenarios=compiled.scenarios, packages={p.digest:p for p in compiled.packages.values()},
        linked_inputs=inputs, scores=scores, config=ScorerConfig(FrozenRecord.from_dict(data['scorer'])),
        execution_authority_keys={EXECUTOR: (OLD_PRIVATE / (EXECUTOR + '.key')).read_bytes()},
        scoring_authority_keys={SCORER: (OLD_PRIVATE / (SCORER + '.key')).read_bytes()})
    write(OUT / 'train-selection.json', selected.data())
    assert original_files() == preflight['original_file_sha256']
    evaluator = read(PRIVATE / 'evaluator-model/ledger.json'); solver = read(OLD / 'model/ledger.json')
    summary = {'schema': 'scorer-only-recovery-result-v1', 'source_commit': preflight['source_commit'],
        'cells': 12, 'scored': len(scores), 'new_solver_calls': 0, 'original_solver_calls': len(solver['calls']),
        'original_solver_tokens': solver['tokens'], 'evaluator_calls': len(evaluator['calls']), 'evaluator_tokens': evaluator['tokens'],
        'usage_incomplete': solver['usage_incomplete'] or evaluator['usage_incomplete'], 'selection': selected.data()['status'],
        'original_files_unchanged': True, 'validation_items': 0, 'calibration': 'not_measured', 'scientific_validity': 'not_measured'}
    write(OUT / 'summary.json', summary); print(canonical(summary), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare','run']); args=parser.parse_args()
    assert Path.cwd().resolve() == SOURCE.resolve()
    try:
        {'prepare':prepare, 'run':run}[args.action]()
    except Exception as exc:
        if OUT.exists() and not (OUT / (args.action + '-failure.json')).exists():
            write(OUT / (args.action + '-failure.json'), {'schema':'scorer-only-recovery-failure-v1',
                'error_type':type(exc).__name__, 'scores':len(list((OUT / 'scores').glob('*.json'))), 'cells':12,
                'selection':'inconclusive', 'new_solver_calls':0, 'validation_items':0})
        print(canonical({'stage':'recovery_failed', 'error_type':type(exc).__name__, 'message':str(exc)[:240]}), flush=True)
        raise SystemExit(1) from None
