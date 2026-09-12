"""Execute the frozen training-only panel through the actual isolated provider."""
import hashlib
import importlib.util
import json
from pathlib import Path
from evaluation.modular.custody import CustodyStore
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_q31_train_panel
from research_loop.ontology import canonical

root = Path(r'E:\_ryanDev\AI\research-loop-modular\work\q31-live-20260913-isolated')
isolation = Path(r'E:\_ryanDev\AI\research-loop-modular\work\q31-isolated-context')
spec = importlib.util.spec_from_file_location('q31_child_environment', isolation / 'context_environment_v2.py')
environment_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment_module)
config_path = root / 'controls/config.json'
config = FrozenTrainControllerConfig.from_path(config_path, 'ba56ddb5286848bccc3d31c8110ac8b897930bea24d959b78ad752ae95993ab1')
policy = FrozenBaseContextPolicy(isolation / 'debug-root-20260913/REVIEWED-POLICY.json',
                                '2d687abb3d47b83c9f01a03d8a67aa85cf07ff17304db013ed732547c06d4425')
data = config.data()
port = CodexModelPort(Path(policy.data()['binding']['cli_path']), root / 'model',
    model=data['model'], effort=data['effort'], max_calls=data['max_calls'], max_tokens=data['max_tokens'],
    schema_by_slot=data['schemas'], frozen_base_context=policy, environment=environment_module.child_environment())
# Reject drift before any panel materialization, reservation or provider call.
port._require_frozen_context()
print(canonical({'status': 'fresh_context_matched', 'planned_cells': 12, 'paid_reservations': len(port.ledger['calls'])}), flush=True)
keys = {name: bytes.fromhex((root / 'controls' / (name + '.key')).read_text().strip())
        for name in ('unused-engineering-audit-a', 'unused-engineering-audit-b')}
result = run_q31_train_panel(config,
    custody=CustodyStore(Path(r'E:\_ryanDev\AI\research-loop-modular\benchmarks\work\custody-live-20260912.json')),
    snapshot_root=Path(r'E:\_ryanDev\AI\research-loop-benchmark-20260912'),
    export_root=root / 'export', run_root=root / 'run', model=port, audit_verifier=AuditVerifier(keys))
summary = {'execution_status': result.receipt.data()['execution_status'],
    'panel_digest': result.compiled.panel.digest, 'cells': result.verdict.observed_cells,
    'failures': result.verdict.failures, 'blocked': result.verdict.blocked,
    'calls': len(port.ledger['calls']), 'tokens': port.ledger['tokens'],
    'usage_incomplete': port.ledger['usage_incomplete'], 'scientific_status': 'not_measured',
    'controller_receipt_sha256': hashlib.sha256((root / 'run/controller-receipt.json').read_bytes()).hexdigest()}
(root / 'metadata-summary.json').write_text(canonical(summary), encoding='utf-8')
print(canonical(summary), flush=True)
