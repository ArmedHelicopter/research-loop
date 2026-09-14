"""Archive exact tested source bytes before invoking the existing frozen runner."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
prefix = Path(sys.argv[2]).resolve()
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=root).strip()
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
archive = Path(str(prefix) + '-sources.zip')
manifest = Path(str(prefix) + '-source-members.json')
assert not archive.exists() and not manifest.exists()
names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
rows = []
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
    for name in names:
        if not name or name.startswith('results/') or Path(name).suffix not in ('.py', '.md'):
            continue
        raw = (root / name).read_bytes()
        rows.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        output.writestr(name, raw)
body = {'commit': head, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'scope': 'exact pre-check disk source bytes; compare to frozen runner source_before', 'members': rows}
manifest.write_bytes((json.dumps(body, indent=2) + '\n').encode())
helper = Path(__file__).with_name('run_frozen_useful_checks.py')
status = subprocess.call([sys.executable, str(helper), *sys.argv[1:]])
before = json.loads(Path(str(prefix) + '-before.json').read_bytes())
assert before['commit'] == head
assert before['source_before'] == {row['path']: row['sha256'] for row in rows}
print(json.dumps({'source_archive_matches_frozen_input': True, 'source_files': len(rows),
                  'source_archive_sha256': body['archive_sha256']}))
sys.exit(status)
