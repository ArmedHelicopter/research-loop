import hashlib
import json
from pathlib import Path
import shutil
import subprocess

work = Path('E:/_ryanDev/AI/research-loop-modular/work')
target = work / 'grok130-initialize-private-log-r1'
target.mkdir(exist_ok=False)
source = work / 'grok130-initialize-stdin-ab-r1/init_engine.py'
shutil.copyfile(source, target / 'init_engine.py')
assert (target / 'init_engine.py').read_bytes() == source.read_bytes()
raw = subprocess.check_output(['git', '--git-dir=' + str(work / 'grok-source-tree-r5'),
    'show', 'bc7f02eddd3d84085849dc19ed216f11c23b0571:crates/codegen/xai-grok-pager/README.md'])
assert b'GROK_LOG_FILE' in raw and b'RUST_LOG' in raw
(target / 'official-pager-README.md').write_bytes(raw)
(target / 'preparation.json').write_text(json.dumps({'engine_source': str(source),
    'engine_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'documentation_source_commit': 'bc7f02eddd3d84085849dc19ed216f11c23b0571',
    'documentation_sha256': hashlib.sha256(raw).hexdigest()}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'prepared': str(target), 'no_native_launch': True}))
