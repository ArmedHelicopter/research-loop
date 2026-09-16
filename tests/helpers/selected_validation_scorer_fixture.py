"""Synthetic test peer; it is never a production evaluator or calibration."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import SignedAuthority
from research_loop.modular.selected_bundle_validation_executor import replay_validation_score_request

R = FrozenRecord.from_dict
body = json.loads(Path(sys.argv[1]).read_bytes())
keys = {kind: {k: bytes.fromhex(v) for k, v in values.items()} for kind, values in body['keys'].items()}
scores = []
for request in body['requests']:
    source = replay_validation_score_request(R(request), freeze_keys=keys['freeze'], custody_keys=keys['custody'], source_keys=keys['source']).data()
    if source['runtime_status'] != 'succeeded': continue
    result = json.loads(source['submission']['execution_feedback']['stdout'])
    assert isinstance(result['mean'], (int, float))
    receipt = SignedAuthority('scorer', b'j'*32).issue({'schema': 'independent-scored-cell-v1',
        'cell_digest': R(source['cell']).content_hash, 'runtime_trace_digest': source['runtime_trace_digest'],
        'scorer_digest': source['cell']['scorer_digest'], 'synthetic_fixture': True,
        'replayed_input_digest': R(source).content_hash, 'observed_mean': result['mean']})
    scores.append({'cell_key': source['cell_key'], 'receipt': receipt.data()})
print(R({'pid': os.getpid(), 'scores': scores}).encoded)
