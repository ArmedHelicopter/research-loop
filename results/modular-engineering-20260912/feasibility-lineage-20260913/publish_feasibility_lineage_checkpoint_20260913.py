"""Append completed, source-qualified engineering and metadata evidence."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
DEST = ARCHIVE / 'feasibility-lineage-20260913'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

old = json.loads((ARCHIVE / 'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 899 and not DEST.exists()
for name, expected in old.items():
    assert sha((ARCHIVE / name).read_bytes()) == expected, name

entries = [
 ('work/full-286f5b1-r1.xml', 'full-root-286f5b1.xml', 'Frozen 286f5b1; 1143 passed; predates feasibility, model schema drift check and canonical lineage'),
 ('work/feasibility-root-be65ef5-r1.xml', 'feasibility-root-be65ef5.xml', 'Frozen be65ef5; 186 passed; real 36-cell custody/model-port mocked transport/Docker/fixture-verifier seam'),
 ('work/controller-schema-root-r1.xml', 'controller-schema-root-9881060.xml', '9881060; two source-qualified checks including live vs frozen schema rejection before export'),
 ('work/feasibility-repair-716f778-20260913.xml', 'feasibility-716f778-collection-failure.xml', 'Wrong test filename; zero tests, not a successful run'),
 ('work/feasibility-repair-716f778-verified-20260913.xml', 'feasibility-agent-716f778-superseded.xml', '74 passed on 716f778; superseded because subjective judgement still followed execution'),
 ('work/feasibility-repair-716f778-verification.json', 'feasibility-agent-716f778-verification.json', 'Source hashes and explicit prospective-judgement qualification'),
 ('work/feasibility-repair-1a30ac9-20260913.xml', 'feasibility-agent-1a30ac9.xml', 'Frozen final driver; 83 passed; overlaps root checks'),
 ('work/feasibility-repair-1a30ac9-verification.json', 'feasibility-agent-1a30ac9-verification.json', 'Source and report hashes; no independent scientific validation'),
 ('work/feasibility-grid.xml', 'feasibility-v1-grid-failure.xml', 'Original v1 development failure; not final source verification'),
 ('work/feasibility-grid-2.xml', 'feasibility-v1-grid-failure-2.xml', 'Original v1 development failure; not final source verification'),
 ('work/feasibility-faults.xml', 'feasibility-v1-fault-failure.xml', 'Original v1 development failure; not final source verification'),
 ('work/feasibility-final.xml', 'feasibility-v1-final-superseded.xml', 'Original v1 passed checks do not establish repaired causal bindings; preserved without promoting claims'),
 ('work/lineage-root-460de21-r1.xml', 'lineage-root-460de21.xml', '34 passed; fixed metadata, exact Git root, real worktree and label isolation'),
 ('work/lineage-root-b53159d-r1.xml', 'lineage-static-root-b53159d.xml', '36 passed; fixed-slot AST, custody CLI, exact Git root and label isolation; overlaps prior checks'),
 ('work/fresh-airs-custodian-checks/lineage-final-junit.xml', 'lineage-agent-9f74850.xml', 'Agent final 69 checks; predates root Git-root identity fix'),
 ('work/fresh-airs-lineage-live-r1/receipt.failure.json', 'lineage-live-r1-failure.json', 'Fixed-schema failure only; first metadata decode failed'),
 ('work/fresh-airs-lineage-live-r1/receipt-r2.json', 'lineage-live-r2.json', 'Metadata parser revision, not a newly unexposed source'),
 ('work/fresh-airs-lineage-live-r1/receipt-r3.json', 'lineage-live-r3.json', 'Structured reference parser revision; prior files preserved'),
 ('integration/docs/data-source-metadata/airsbench-canonical-lineage-receipt.json', 'lineage-live-r4.json', '605 records, 1502 unchanged read files, conservative 202 components, zero validation eligibility'),
 ('integration/docs/data-source-metadata/airsbench-canonical-lineage-attempts.json', 'lineage-live-attempts.json', 'Exact attempt hashes and all source-qualified failures'),
 ('integration/docs/data-source-metadata/airsbench-canonical-lineage-supplements.json', 'lineage-supplement-requirements.json', 'Opaque source-group gaps; no raw task or reference payload'),
 ('integration/docs/data-source-metadata/airsbench-canonical-lineage-static-receipt.json', 'lineage-static-live-r1.json', '40 fixed preparation slots, zero declared API matches; no upstream execution or eligibility promotion'),
 ('work/publish_feasibility_lineage_checkpoint_20260913.py', 'publish_feasibility_lineage_checkpoint_20260913.py', 'Append-only publisher'),
]
payloads, origins, reports = {}, {}, {}
for relative, target, qualification in entries:
    source = BASE / relative
    assert source.is_file() and not source.is_symlink(), str(source)
    raw = source.read_bytes()
    payloads[target] = raw
    origins[target] = {'source': str(source), 'sha256': sha(raw), 'qualification': qualification}
    if target.endswith('.xml'):
        suite = ET.fromstring(raw).find('testsuite')
        reports[target] = {key: suite.attrib[key] for key in ('tests', 'failures', 'errors', 'skipped', 'time')}
required = {'full-root-286f5b1.xml':1143, 'feasibility-root-be65ef5.xml':186,
            'controller-schema-root-9881060.xml':2, 'feasibility-agent-1a30ac9.xml':83,
            'lineage-root-460de21.xml':34, 'lineage-static-root-b53159d.xml':36}
for name, count in required.items():
    assert int(reports[name]['tests']) == count
    assert all(reports[name][key] == '0' for key in ('failures','errors','skipped'))
lineage = json.loads(payloads['lineage-live-r4.json'])
static = json.loads(payloads['lineage-static-live-r1.json'])
assert lineage['graph']['total_records'] == 605 and lineage['read_file_count'] == 1502
assert static['counts']['slot_present_count'] == 40 and static['counts']['resolved_call_count'] == 0
DEST.mkdir()
for target, raw in payloads.items():
    (DEST / target).write_bytes(raw)
write(DEST / 'origins.json', origins)
write(DEST / 'checkpoint.json', {
 'schema': 'feasibility-lineage-engineering-checkpoint-v1',
 'source_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
 'production_question_drivers':27, 'new_feasibility_cells':36, 'reports':reports,
 'full_suite_source':'286f5b1633786e40dbc525576af690f1488d849c',
 'current_head_full_suite_pass':False,
 'source_records':605, 'metadata_group_constraints':202, 'independent_validation_eligible':0,
 'static_preparation_slots':40, 'static_declared_api_matches':0,
 'new_paid_calls':0, 'scientific_effectiveness_proven':False, 'validation_opened':False,
 'pruned_combinations':[], 'deployment_performed':False,
 'overlapping_checks_are_not_independent_replications':True,
 'non_integrated_work':'Q27 controller pending root review; Q54/Q55 and M6 causal defects under repair; no production completion credit',
 'remaining_scope':'All 48 Q outcomes, all single/conditional/pair/triple/full/LOO studies, separate Q6.3 and frozen-candidate validation acceptance',
})
index = {p.relative_to(ARCHIVE).as_posix():sha(p.read_bytes())
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name, expected in old.items())
write(ARCHIVE / 'SHA256.json', index)
print(json.dumps({'old_files_preserved':len(old), 'new_files':len(index)-len(old), 'total':len(index), 'reports':reports}))
