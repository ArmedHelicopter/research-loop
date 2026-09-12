"""Root's fresh no-paid isolated context audit, followed by material review."""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from research_loop.modular.model_port import audit_base_context, FrozenBaseContextPolicy, _reviewed_notice_messages
from research_loop.ontology import canonical

parser = argparse.ArgumentParser()
parser.add_argument('--record-review', action='store_true')
args = parser.parse_args()
root = Path(r'E:\_ryanDev\AI\research-loop-modular\work\q31-isolated-context')
spec = importlib.util.spec_from_file_location('q31_child_environment', root / 'context_environment_v2.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
prior = json.loads((root / 'debug-v2-3/UNQUALIFIED-POLICY.json').read_text())
binding = prior['binding']
target = root / 'debug-root-20260913'
if not args.record_review:
    candidate = audit_base_context(Path(binding['cli_path']), Path(binding['fixed_cwd']), target,
        source_specs=binding['source_specs'], config_overrides=tuple(binding['config_overrides']),
        environment=module.child_environment())
    value = json.loads(candidate.read_text())
    print(canonical({'candidate': str(candidate), 'paid_calls': 0,
        'context_digest': value['binding']['context_digest'],
        'same_source_configuration': value['binding']['config_sources_hash'] == binding['config_sources_hash'],
        'changed_binding_fields': [key for key in binding if binding[key] != value['binding'].get(key)]}))
else:
    value = json.loads((target / 'UNQUALIFIED-POLICY.json').read_text())
    previous_notice = json.loads(Path(r'E:\_ryanDev\AI\research-loop-modular\work\startup-notice-amendment-20260912\UNQUALIFIED-POLICY.json').read_text())
    entries = [item for item in previous_notice['allowed_startup_notices'] if item['kind'] == 'disabled_code_mode_host']
    _reviewed_notice_messages(value['binding'], entries)
    value.update(status='REVIEWED', allowed_startup_notices=entries, review={
        'reviewer': 'root controller / inspected complete current render and source manifest',
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'rationale': 'Inspected the complete fresh isolated developer/user base messages. They contain five ordinary bundled skill descriptions, fixed read-only settings, current date and a dedicated empty public cwd. No global memory instruction, benchmark input, reference, score or validation material is present. Global .agents skill descriptions and review-agent are not visible. The previous global-skill drift and first isolated skill catalogue leakage remain rejected historical attempts.',
        'source_completeness': 'The dedicated CODEX_HOME/profile and fixed model catalogue are hash-bound. All 754 discovered host .agents skill files are explicitly disabled in the isolated config and their actual host glob is an additional source inventory, so additions/deletions/drift reject later calls. Isolated system skills, local configuration and ancestor files are frozen. Credential file contents are excluded from source inventories and all evidence exports; local login status was verified independently. This is local prompt reproducibility and no-tool execution, not proof of OS isolation or remote deployment identity.',
        'startup_notice_rationale': 'Only the exact code-mode-host-disabled notice is allowed, authenticated against the retained historical events file and matching fixed disabled flags. The unstable-feature notice is suppressed by the frozen isolated config, so its old global-home message is not permitted. Unknown context diagnostics remain failures.'})
    reviewed = target / 'REVIEWED-POLICY.json'
    with reviewed.open('x', encoding='utf-8') as stream:
        stream.write(canonical(value))
    sha = hashlib.sha256(reviewed.read_bytes()).hexdigest()
    FrozenBaseContextPolicy(reviewed, sha).data()
    print(canonical({'policy': str(reviewed), 'sha256': sha, 'paid_calls': 0, 'status': 'REVIEWED'}))
