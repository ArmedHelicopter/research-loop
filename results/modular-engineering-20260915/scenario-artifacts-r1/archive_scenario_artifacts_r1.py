"""Archive original synthetic scenario outputs after readonly semantic readback."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'artifact-evidence-provenance'
PREFIX = BASE/'work/scenario-artifacts-frozen-r1'
OUT = ROOT/'results/modular-engineering-20260915/scenario-artifacts-r1'
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.scenarios_improvement import (
    ImprovementScenarioResult, inspect_scenario_artifact_failure, verify_scenario_artifacts)
from research_loop.ontology import ContractError
from test_modular_improvement_scenarios import controls, task_for


def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, body):
    with path.open('xb') as stream:
        stream.write((json.dumps(body, indent=2, ensure_ascii=False)+'\n').encode())
def inventory(root):
    found, pending = {}, [root]
    while pending:
        for path in pending.pop().iterdir():
            assert not path.is_symlink() and not path.is_junction()
            if path.is_dir(): pending.append(path)
            else: found[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return dict(sorted(found.items()))


closed = json.loads(Path(str(PREFIX)+'-closed.json').read_bytes())
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert closed['junit'] == {'tests':107, 'failures':0, 'errors':0, 'skipped':0}
OUT.mkdir(parents=True, exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
originals = []
for suffix in ('-before.json','-closed.json','.xml','-sources.zip','-source-members.json'):
    source = Path(str(PREFIX)+suffix); target = OUT/source.name
    shutil.copyfile(source, target)
    originals.append({'file':target.name,'bytes':target.stat().st_size,'sha256':sha(target.read_bytes())})
for name in ('archive_scenario_artifacts_r1.py', 'archive_scenario_artifacts_first_attempt.py', 'scenario-artifacts-archive-first-attempt.json'):
    source = BASE/'work'/name
    shutil.copyfile(source, OUT/name)
    originals.append({'file':name,'bytes':source.stat().st_size,'sha256':sha(source.read_bytes())})
note = BASE/'grok-headless-transport/work/scenario-semantic-verification.md'
shutil.copyfile(note, OUT/'agent-verification-attempts.md')
originals.append({'file':'agent-verification-attempts.md','bytes':note.stat().st_size,'sha256':sha(note.read_bytes())})
source_meta = json.loads(Path(str(PREFIX)+'-source-members.json').read_bytes())
resolver = ArchivedSourceResolver(Path(str(PREFIX)+'-sources.zip'), source_meta['archive_sha256'], ROOT)

patterns = (
    'test_m9_variants_retain_public*',
    'test_actual_offline_scenario_o*',
    'test_failed_callback_keeps_sea*',
    'test_first_callback_opportunit*',
    'test_throwing_first_callback_k*',
    'test_failed_malformed_runtime_*',
    'test_callback_subclass_is_reje*',
    'test_actual_return_gate_requir*',
    'test_callback_link_preserves_o*',
)
records = []
cases = sorted({case for pattern in patterns for case in PREFIX.glob(pattern)
                if not case.name.endswith('current') and not case.is_symlink() and not case.is_junction()})
for case in cases:
    paths = list(case.glob('run/scenario-artifacts.jsonl')) + list(case.glob('Q6.*/*/scenario-artifacts.jsonl'))
    for catalogue_path in sorted(paths):
        root = catalogue_path.parent
        rows = [FrozenRecord(line).data()['descriptor'] for line in catalogue_path.read_text(encoding='utf-8').splitlines()]
        inputs = rows[0]['payload']['canonical']
        task = task_for(inputs['task']['identity']['benchmark'])
        frozen = controls(task)
        assert inputs['task'] == task.data() and inputs['controls'] == frozen.data()
        args = dict(task=task, frozen_controls=frozen, sidecar=root,
                    experiment_id=inputs['experiment_id'], variant=inputs['variant'])
        before = inventory(root)
        terminal_path = root/'scenario-terminal.json'
        incomplete = not (root/'scenario-closure.json').exists()
        status = 'incomplete' if incomplete else json.loads(terminal_path.read_bytes())['status']
        result = None
        if (root/'scenario-result.json').exists():
            requests = tuple(FrozenRecord.from_dict(row['payload']['canonical']) for row in rows
                             if row['kind'] == 'scenario_callback_request')
            outputs = tuple(FrozenRecord.from_dict(row['payload']['canonical']['record']) for row in rows
                            if row['kind'] == 'scenario_callback_return')
            result = ImprovementScenarioResult(args['experiment_id'], args['variant'], requests, outputs,
                FrozenRecord((root/'scenario-result.json').read_text(encoding='utf-8').strip()))
        if status == 'succeeded':
            report = verify_scenario_artifacts(result, **args).data()
            assert report['status'] == 'succeeded' and not report['scientific_validated']
        elif status == 'failed':
            report = inspect_scenario_artifact_failure(**args).data()
            assert report['storage_integrity_verified'] and not report['stage_semantics_verified'] and not report['acceptance_eligible']
        else:
            try:
                if result is not None: verify_scenario_artifacts(result, **args)
                else: inspect_scenario_artifact_failure(**args)
            except ContractError: pass
            else: raise AssertionError('incomplete prefix unexpectedly accepted')
            report = {'reader_rejected_incomplete':True, 'storage_integrity_verified':False,
                      'stage_semantics_verified':False, 'acceptance_eligible':False}
        assert before == inventory(root)
        for row in rows: resolver.verify_snapshot(row['producer_source'])
        for key in ('scenario_source','adapter_source'): resolver.verify_snapshot(inputs[key])
        if not incomplete:
            catalogue = ArtifactCatalogue(catalogue_path, identity=task.identity,
                **rows[0]['binding'], source_resolver=resolver)
            assert len(catalogue.records()) == len(rows)
        name = case.name+'-'+root.name+'.zip'
        with zipfile.ZipFile(OUT/name, 'x', zipfile.ZIP_DEFLATED) as archive:
            for filename in before: archive.writestr(filename, (root/filename).read_bytes())
        raw = (OUT/name).read_bytes()
        item = {'file':name,'bytes':len(raw),'sha256':sha(raw)}
        originals.append(item)
        records.append({**item,'original_root':str(root),'status':status,'descriptors':len(rows),
            'experiment_id':args['experiment_id'],'variant':args['variant'],'benchmark':task.identity.benchmark,
            'read_only':True,'report':report,'source_archive_reverified':True,'files':before})
assert sum(row['status'] == 'succeeded' for row in records) == 32
assert sum(row['status'] == 'failed' for row in records) == 6
assert sum(row['status'] == 'incomplete' for row in records) == 2
write(OUT/'manifest.json', {'schema':'scenario-artifact-evidence-archive-v1','source_commit':closed['commit'],
    'source_root':str(ROOT),'originals':originals,'specimens':records,
    'scope':'actual local offline producers with synthetic callbacks; 28 two-benchmark fixture variants, four explicit callback fixtures, six failures and two incomplete prefixes',
    'new_paid_api_calls':0,'model_calls':0,'docker_calls':0,'real_validation_access':False,
    'scientific_effect':'not_measured','agent_attempt_note_scope':'earlier separate branch attempts, not root frozen run'})
for item in originals:
    raw = (OUT/item['file']).read_bytes()
    assert sha(raw) == item['sha256'] and len(raw) == item['bytes']
    if item['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT/item['file']) as archive: assert archive.testzip() is None
write(OUT/'verification.json', {'status':'verified','original_files':len(originals),'specimens':len(records),
    'succeeded':32,'failed_storage_only':6,'incomplete_rejected':2,
    'descriptors':sum(row['descriptors'] for row in records),
    'all_original_bytes_rechecked':True,'read_only':True,'no_scientific_or_real_validation_claim':True})
print(json.dumps({'archive':str(OUT),'original_files':len(originals),'specimens':len(records),
                  'descriptors':sum(row['descriptors'] for row in records)}))
