"""One new read-only account observation; never repairs the historical receipt."""
import hashlib
import json
from pathlib import Path
import sys

WORK = Path(__file__).parent
TREE = WORK.parent / 'headless-review-runtime'
ROOT = WORK / 'headless-review-account-readonly-r1'
sys.path.insert(0, str(TREE))
import research_loop.modular.grok_headless_transport as native

assert not ROOT.exists()
ROOT.mkdir()
source_sha = hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()
result = {'schema': 'headless-review-account-readonly-v1', 'model_calls': 0,
    'additional_paid_api_budget': 0, 'validation_access': False,
    'source_sha256': source_sha, 'historical_run_changed': False,
    'purpose': 'observe current account GET health after closed postflight failure; not retrospective account proof'}
try:
    observation = native._account(Path('C:/Users/Administrator/.grok'), ROOT / 'account-private')
    assert observation['account_binding'] == 'b13ba3f652654cf9907b60161d7cd397e5edd8da74646e642e4105768d511c2e'
    result.update(status='observed', observation=observation)
except Exception as exc:
    chain = []
    while exc is not None:
        row = {'type': type(exc).__name__}
        if hasattr(exc, 'code') and type(exc.code) is int:
            row['http_status'] = exc.code
        chain.append(row)
        exc = exc.__cause__
    result.update(status='failed', exception_types=chain)
assert hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() == source_sha
with (ROOT / 'public-observation.json').open('x', encoding='utf-8') as f:
    json.dump(result, f, indent=2)
print(json.dumps(result))
