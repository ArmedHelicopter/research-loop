"""Trusted controller pass; only counts and hashes leave the private process."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from evaluation.modular.custody import CustodyStore
from evaluation.modular.extended_ingestion import ExtendedInventoryImporter
from research_loop.ontology import canonical

private = Path(r'E:\_ryanDev\AI\research-loop-modular\custody-private\extended-sources')
destination = private / 'custody-inventory-v1.json'
assert not destination.exists(), 'new immutable custody state required'
old = Path(r'E:\_ryanDev\AI\research-loop-modular\benchmarks\work\custody-live-20260912.json')
old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
store = CustodyStore(destination)
result = ExtendedInventoryImporter(private).import_into(store)
inventory = store.state['inventory']
summary = result.receipt.data() | {
    'custody_state_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    'group_counts': {source: len({row['group_id'] for row in inventory if row['benchmark'] == source}) for source in ('scicode', 'scienceagentbench')},
    'exposure_counts': dict(Counter(row['exposure'] for row in inventory)),
    'split_assigned': False,
    'existing_core_custody_unchanged': hashlib.sha256(old.read_bytes()).hexdigest() == old_hash,
}
assert summary['existing_core_custody_unchanged']
target = Path('work/extended-live-import-metadata.json')
with target.open('x', encoding='utf-8') as stream:
    stream.write(canonical(summary))
print(canonical(summary))
