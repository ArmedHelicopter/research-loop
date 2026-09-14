"""Source-only call-site inventory; no imports or dataset/credential access."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

WORK = Path(__file__).resolve().parent
TREE = WORK.parent/'artifact-evidence-provenance'
TARGETS = {'run_phase', 'RestrictedBuilderPort', 'EvidenceLedger', 'ClaimLedger',
    'PredictionRegistry', 'ReviewEngine', 'ContextBuilder'}
rows, sources = [], {}
for path in sorted((TREE/'research_loop/modular').rglob('*.py')):
    raw = path.read_bytes(); source = raw.decode('utf-8-sig'); tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
        if name not in TARGETS: continue
        scope, cursor = [], node
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): scope.append(cursor.name)
        enclosing = list(reversed(scope))
        relative = path.relative_to(TREE).as_posix()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        rows.append({'path': relative, 'line': node.lineno, 'callee': name,
            'enclosing': '.'.join(enclosing), 'keywords': [kw.arg for kw in node.keywords],
            'explicit_phase_bridge': any(kw.arg == 'artifact_bridge' for kw in node.keywords) if name == 'run_phase' else None,
            'replay_named_scope': any('verif' in part or 'replay' in part for part in enclosing)})
rows.sort(key=lambda row: (row['callee'], row['path'], row['line']))
report = {'schema': 'artifact-production-call-site-inventory-v1',
    'commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=TREE, text=True).strip(),
    'scope': 'AST call sites in research_loop/modular only; aliases and runtime indirect calls require separate audit',
    'source_pins': sources, 'call_sites': rows, 'all_module_coverage_proven': False}
output = WORK/'artifact-host-call-sites-r1.json'
with output.open('x', encoding='utf-8') as stream: json.dump(report, stream, indent=2); stream.write('\n')
print(json.dumps({'output':str(output), 'source_files':len(sources), 'call_sites':len(rows),
    'phase_calls':sum(r['callee']=='run_phase' for r in rows),
    'phase_calls_without_bridge':sum(r['callee']=='run_phase' and not r['explicit_phase_bridge'] for r in rows)}))
