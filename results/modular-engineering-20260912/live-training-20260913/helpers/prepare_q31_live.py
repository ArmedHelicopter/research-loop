"""Freeze an actual two-source, training-only Q3.1 transport panel; no paid call."""
import hashlib
import argparse
import json
import secrets
import subprocess
from pathlib import Path
from research_loop.modular.__main__ import programme_plan
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import executable_arms, obligation_grids, compile_train_panel
from research_loop.modular.train_controller import FrozenTrainControllerConfig
from research_loop.ontology import canonical

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
root = parser.parse_args().output
root.mkdir(exist_ok=False)
controls = root / 'controls'
controls.mkdir()
packet_root = Path(r'E:\_ryanDev\AI\research-loop-modular\benchmarks\work\train-packets-live-20260912-v3')
tasks = []
for benchmark in ('blade', 'discoverybench'):
    paths = list((packet_root / benchmark).glob('*/public.json'))
    assert len(paths) == 1
    envelope = json.loads(paths[0].read_text(encoding='utf-8'))
    identity = DataIdentity.parse(envelope['task']['identity'])
    identity.require_train()
    task = PublicTask.create(identity, envelope['task']['payload'])
    assert task.content_hash == envelope['receipt']['packet_hash']
    assert hashlib.sha256((paths[0].parent / 'data.csv').read_bytes()).hexdigest() == envelope['receipt']['csv_sha256']
    tasks.append(task)

def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
def array(item):
    return {'type': 'array', 'items': item}
string = {'type': 'string'}
prediction = obj({name: string for name in ('prediction_id', 'discriminator_id', 'observable', 'direction', 'failure_condition')} | {'value_range': {'type': 'null'}})
branch = obj({name: string for name in ('hypothesis_id', 'mechanism_key', 'mechanism', 'intervention', 'elimination_condition')} | {'predictions': array(prediction)})
schemas = {
    'scenario': obj({'question': string, 'branches': array(branch), 'budget_units': {'type': 'integer', 'enum': [3]}}),
    'final': obj({'objective_digest': string, 'outcome': {'type': 'string', 'enum': ['unknown']},
                  'evidence_ids': array(string), 'conclusion': string, 'programme_complete': {'type': 'boolean', 'enum': [False]}}),
}
source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
baseline = hashlib.sha256(('q31-live-transport-v1:' + source_commit).encode()).hexdigest()
plan = programme_plan(baseline)
control = FrozenRecord.from_dict(plan.data()['P0_control_source_lock'])
grids = obligation_grids(('Q3.1',), baseline_digest=baseline, p0_control=control)
package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks]),
    changes={'prompt': {'instructions': 'Use only the current public task and supplied scenario. Freeze competing predictions without inventing observations. This panel measures transport and plan mechanics only; no scientific result or programme completion is authorized.'}}, search_cost=0)
packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
body = {'schema': 'q31-train-controller-v1', 'engineering_scope': 'train_only_q3_1_engineering',
        'stage': 'q31-live-training-transport-20260912', 'scope_ids': ['Q3.1'],
        'item_ids': [f'{task.identity.benchmark}:{task.identity.task_id}' for task in tasks],
        'evidence_by_task': {task.content_hash: {'observations': [], 'scope': 'No executed observation supplied to this prediction-planning panel.'} for task in tasks},
        'budget': {'model_calls_per_cell': 2, 'execution_limit': 0, 'matched_tokens': 'not_claimed'},
        'baseline_digest': baseline, 'p0_control': control.data(),
        'packages_by_arm': {key: value.record.data() for key, value in packages.items()},
        'scorer': {'identity': 'unconfigured', 'scientific_status': 'not_measured'},
        'acceptance_criteria': {'scope': 'engineering_only', 'required_cells': 12, 'allowed_failures': 0, 'scientific_promotion': False},
        'replicates': ['r1'], 'model': 'gpt-5.6-luna', 'effort': 'low', 'max_calls': 24, 'max_tokens': 250000, 'schemas': schemas}
config = FrozenTrainControllerConfig(FrozenRecord.from_dict(body))
compiled = compile_train_panel(stage=body['stage'], scope_ids=('Q3.1',), tasks=tasks,
    evidence_by_task={key: FrozenRecord.from_dict(value) for key, value in body['evidence_by_task'].items()},
    budget=FrozenRecord.from_dict(body['budget']), baseline_digest=baseline, p0_control=control,
    packages_by_arm=packages, scorer=FrozenRecord.from_dict(body['scorer']), acceptance_criteria=FrozenRecord.from_dict(body['acceptance_criteria']))
(controls / 'config.json').write_text(config.record.encoded, encoding='utf-8')
(controls / 'frozen-panel.json').write_text(canonical({'panel_digest': compiled.panel.digest,
    'manifest': compiled.manifest.data(), 'cells': [cell.data() for cell in compiled.panel.cells]}), encoding='utf-8')
for authority in ('unused-engineering-audit-a', 'unused-engineering-audit-b'):
    (controls / (authority + '.key')).write_text(secrets.token_bytes(32).hex(), encoding='ascii')
record = {'config_sha256': hashlib.sha256((controls / 'config.json').read_bytes()).hexdigest(),
          'source_commit': source_commit, 'panel_digest': compiled.panel.digest, 'cells': len(compiled.panel.cells),
          'model_call_cap': 24, 'token_cap': 250000, 'training_items': body['item_ids'],
          'scientific_status': 'not_measured', 'audit_keys': 'unused local engineering-only verifier slots; no audit authority deployment or scientific receipt claimed'}
(controls / 'preflight.json').write_text(canonical(record), encoding='utf-8')
print(canonical(record))
