"""Separate read-only re-verification; original paid trial stays immutable."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
SOURCE = BASE / 'integration'
VERIFIER_COMMIT = '39cfac6e3702879b139af58c7d4f02b1acb00ad5'
sys.path.insert(0, str(SOURCE))
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.benchmark_cell import _solver_journal_state
from research_loop.modular.benchmark_solver import CompletedSolverSession, BenchmarkSolveResult, _candidate_from
from research_loop.modular.combination_benchmark_driver import CombinationBenchmarkCellResult, verify_m4_m5_combination_benchmark_cell
from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.panel_receipts import RuntimeReceipt

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_pin():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip() == VERIFIER_COMMIT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip()

source_pin()
trial = BASE / 'work/m4m5-train-process-20260913-01'
archive = SOURCE / 'results/modular-engineering-20260912/combination-exploration-20260913'
pins = read(archive / 'original-trial-file-hashes.json')
assert len(pins) == 302
def verify_original():
    assert {p.relative_to(trial).as_posix() for p in trial.rglob('*') if p.is_file()} == set(pins)
    assert all(sha(trial / relative) == value for relative, value in pins.items())
verify_original()
preflight = read(trial / 'preflight.json')
assert preflight['source_commit'] == '60cc333965c75d0d493afab3ac63dec1f5b12d9a'
assert sha(BASE / 'work/run_m4m5_train_20260913.py') == preflight['runner_sha256']
assert sha(trial / 'controller.json') == preflight['controller_sha256']
packets = []
for benchmark in ('blade', 'discoverybench'):
    paths = list((trial / 'export' / benchmark).glob('*/public.json'))
    assert len(paths) == 1
    path = paths[0]
    body = read(path)
    identity = DataIdentity.parse(body['task']['identity'])
    identity.require_train()
    task = PublicTask.create(identity, body['task']['payload'])
    receipt = FrozenRecord.from_dict(body['receipt'])
    assert receipt.data()['packet_hash'] == task.content_hash
    assert sha(path.parent / 'data.csv') == receipt.data()['csv_sha256']
    packets.append(PublicTrainPacket(task, path, path.parent / 'data.csv', receipt))
frozen = FrozenM4M5TrainConfig(FrozenRecord.from_dict(read(trial / 'controller.json')))
compiled = compile_m4_m5_train_panel(frozen, tuple(packets))
assert compiled.panel.digest == preflight['panel_digest']
attempt = read(trial / 'run/controller-attempt.json')
assert len(compiled.panel.cells) == len(attempt['cells']) == 8
rows = []
for cell, old in zip(compiled.panel.cells, attempt['cells']):
    assert old['cell'] == cell.data()
    sidecar = trial / 'run/cells' / FrozenRecord.from_dict(cell.data()).content_hash
    trace = sidecar / 'trace.jsonl'
    events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    state = _solver_journal_state(events)
    lock = FrozenRecord.from_dict(events[0]['data'])
    task = next(packet.task for packet in packets if packet.task.content_hash == cell.task_digest)
    session = CompletedSolverSession(task, lock, FrozenRecord.from_dict(lock.data()['objective']), sidecar)
    solver = BenchmarkSolveResult(session, (), state['analysis'], state['execution'], state['answer'], state['decision'], state['status'])
    joint = next((FrozenRecord.from_dict(event['data']['joint']) for event in events if event['stage'] == 'combination_mechanism'), None)
    prior = old['runtime']
    runtime = RuntimeReceipt(cell.key, prior['status'], trace, prior['trace_digest'], prior['output_digest'], prior['failure_reason'])
    result = CombinationBenchmarkCellResult(cell, runtime, solver, joint)
    verified = verify_m4_m5_combination_benchmark_cell(result, panel=compiled.panel, task=task,
        scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash])
    row = {'benchmark': cell.identity.benchmark, 'arm': cell.arm_id, 'original_phase': old['phase'],
           'original_status': old['status'], 'runtime_status': runtime.status, 'solver_status': state['status'],
           'replay_status': 'verified', 'verification_digest': verified.content_hash, 'candidate_valid': None}
    if state['answer'] is not None:
        try:
            _candidate_from(state['answer'], session.objective)
            row['candidate_valid'] = True
        except Exception as exc:
            row['candidate_valid'] = False
            row['candidate_error_type'] = type(exc).__name__
    rows.append(row)
verify_original()
source_pin()
out = {'schema': 'closed-m4m5-reverification-v2', 'original_source_commit': preflight['source_commit'],
       'verification_source_commit': VERIFIER_COMMIT, 'script_sha256': sha(Path(__file__)),
       'panel_digest': compiled.panel.digest, 'original_files': len(pins), 'original_files_unchanged': True,
       'original_pin_manifest_sha256': sha(archive / 'original-trial-file-hashes.json'),
       'new_model_calls': 0, 'new_docker_calls': 0, 'new_scorer_calls': 0, 'validation_payload_reads': 0,
       'original_scored_cells': 5, 'original_failed_cells': 3, 'original_denominator': 8,
       'conclusion': 'inconclusive', 'pruned_combinations': [], 'rows': rows}
destination = BASE / 'work/m4m5-closed-reverification-20260913-r2.json'
with destination.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(out, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps(out, ensure_ascii=False))
