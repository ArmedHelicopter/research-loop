"""Read-only replay of the closed training trial, with metadata-only output."""
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
spec=importlib.util.spec_from_file_location('frozen_pair_runner', BASE/'work/run_m4m5_train_20260913.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmark_solver import CompletedSolverSession, BenchmarkSolveResult, _candidate_from
from research_loop.modular.benchmark_cell import _solver_journal_state
from research_loop.modular.combination_benchmark_driver import CombinationBenchmarkCellResult, verify_m4_m5_combination_benchmark_cell
from research_loop.modular.panel_receipts import RuntimeReceipt

frozen,compiled,preflight=runner.checked()
trial=runner.OUT
paths=[p for p in trial.rglob('*') if p.is_file()]
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
attempt=runner.read(trial/'run/controller-attempt.json')
rows=[]
for cell,row in zip(compiled.panel.cells,attempt['cells']):
    assert row['cell']==cell.data()
    sidecar=trial/'run/cells'/FrozenRecord.from_dict(cell.data()).content_hash
    trace=sidecar/'trace.jsonl'
    events=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    state=_solver_journal_state(events)
    lock=FrozenRecord.from_dict(events[0]['data'])
    task=next(p.task for p in compiled.packets if p.task.content_hash==cell.task_digest)
    view=CompletedSolverSession(task,lock,FrozenRecord.from_dict(lock.data()['objective']),sidecar)
    solver=BenchmarkSolveResult(view,(),state['analysis'],state['execution'],state['answer'],state['decision'],state['status'])
    joint=next((FrozenRecord.from_dict(e['data']['joint']) for e in events if e['stage']=='combination_mechanism'),None)
    r=row['runtime']
    runtime=RuntimeReceipt(cell.key,r['status'],trace,r['trace_digest'],r['output_digest'],r['failure_reason'])
    result=CombinationBenchmarkCellResult(cell,runtime,solver,joint)
    diagnostic={'benchmark':cell.identity.benchmark,'arm':cell.arm_id,'trial_phase':row['phase'],
        'trial_status':row['status'],'solver_status':state['status'],'terminal':events[-1]['stage'],
        'execution_status':state['execution'].status if state['execution'] else None}
    try:
        verify_m4_m5_combination_benchmark_cell(result,panel=compiled.panel,task=task,
            scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash])
        diagnostic['replay']='verified'
    except Exception as exc:
        diagnostic.update(replay='rejected',error_type=type(exc).__name__,error=str(exc),
            frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)])
    if state['answer'] is not None:
        try:_candidate_from(state['answer'],view.objective)
        except Exception as exc:
            answer=state['answer'].data()
            diagnostic['candidate_protocol']={'error':str(exc),'fields':sorted(answer),
                'objective_matches':answer.get('objective_digest')==view.objective.content_hash,
                'outcome':answer.get('outcome'),'evidence_count':len(answer.get('evidence_ids',[])),
                'programme_complete':answer.get('programme_complete')}
    rows.append(diagnostic)
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in before.items())
out={'schema':'closed-m4m5-replay-diagnosis-v1','source_commit':preflight['source_commit'],
    'original_file_count':len(before),'original_files_unchanged':True,'model_calls':0,'docker_calls':0,
    'scorer_calls':0,'rows':rows}
dest=BASE/'work/m4m5-closed-diagnosis-20260913-01.json'
with dest.open('x',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False))
