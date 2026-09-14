"""Preserve the two closed C5 precommit checks and their exact source bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'integration/results/modular-engineering-20260914/c5-common-train'
CHECKS = BASE/'work/c5-common-checks'
ROOT.mkdir(parents=True, exist_ok=False)
sha = lambda raw: hashlib.sha256(raw).hexdigest()
def write(name, value): (ROOT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
members = {}; excluded = []
for name in ('r1','r2'):
    closure = json.loads((CHECKS/(name+'-closed.json')).read_bytes())
    assert closure['source_unchanged'] and closure['exit_code'] == 0
    assert closure['junit'] == dict(tests=31,failures=0,errors=0,skipped=0)
    for suffix in ('-before.json','-closed.json','.xml','-stdout.txt','-sources.zip','-source-members.json'):
        shutil.copyfile(CHECKS/(name+suffix), ROOT/(name+suffix))
    source_manifest = json.loads((ROOT/(name+'-source-members.json')).read_bytes())
    members[name+'-sources'] = source_manifest['members']
    with zipfile.ZipFile(ROOT/(name+'-originals.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
        original_members = []
        origin = (CHECKS/name).resolve(strict=True)
        for path in sorted(origin.rglob('*')):
            if not path.is_file(): continue
            relative = path.relative_to(origin).as_posix()
            if (path.is_symlink() or not path.resolve().is_relative_to(origin)
                    or path.name in {'auth.json','login.json'} or '__pycache__' in path.parts
                    or path.suffix in {'.pyc','.exe','.key'}):
                excluded.append({'run':name,'path':relative}); continue
            raw = path.read_bytes(); archive.writestr(relative,raw)
            original_members.append({'path':relative,'bytes':len(raw),'sha256':sha(raw)})
        members[name+'-originals'] = original_members
write('archive-members.json',members)
write('excluded-paths.json',excluded)
shutil.copyfile(__file__,ROOT/'archive_builder.py')
shutil.copyfile(BASE/'integration/docs/c5-common-train-protocol.md',ROOT/'protocol-scope.md')
(ROOT/'independent-review.md').write_text('''# Independent source review

Reviewer: /root/grok_provider_independent_review. Reviewed 461575a read-only.
No blocking defect within the explicit precommit/input-verification scope.
Catalogue regeneration checks complete recipes/aliases, conditional prerequisites,
structural origins, B0 exclusion, allocation, M9-history/M8-target and all48 Q records.
Original public/component/runtime bytes are reopened before exclusive lock write.
Manifest completeness, native launch, scorer/reference originals and actual module
consumers remain unproved. Complete identity must include protocol digest, never
bare recipe alias across different configs. Follow-up b3cd045 exposes trial_binding
with that full identity; the second closed31-check run includes its regression.

Both runs are synthetic precommit checks: zero actual model/scorer/Docker calls,
no validation access or scientific effect measurement. The original 48 questions,
C1-C4 experimental obligations, separate Q6.3 and C5 execution/selection/acceptance
remain required. No old scores were imported, no actual winner selected.
''',encoding='utf-8')
write('archive-integrity.json',{p.relative_to(ROOT).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
    for p in sorted(ROOT.rglob('*')) if p.is_file()})
print(json.dumps({'archive':str(ROOT),'files':len(list(ROOT.iterdir())),
                  'zip_members':sum(len(rows) for rows in members.values())}))
