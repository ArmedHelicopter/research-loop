"""Recover only the summary after the successful immutable import."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from evaluation.modular.custody import CustodyStore
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import canonical

private = Path(r'E:\_ryanDev\AI\research-loop-modular\custody-private\extended-sources')
destination = private / 'custody-inventory-v1.json'
state = CustodyStore(destination).state
inventory = state['inventory']
old_snapshot = json.loads(Path('results/modular-engineering-20260912/expanded-sources-and-panels-01/custody-metadata-summary.json').read_text())
old_unchanged = hashlib.sha256(Path(old_snapshot['source']).read_bytes()).hexdigest() == old_snapshot['source_sha256']
assert old_unchanged
summary = {
    'schema': 'extended-source-inventory-metadata-v1', 'inventory_digest': state['inventory_digest'],
    'source_pins': {name: spec.revision for name, spec in SOURCE_SNAPSHOTS.items()},
    'item_counts': dict(Counter(row['benchmark'] for row in inventory)),
    'group_counts': {source: len({row['source_group'] for row in inventory if row['benchmark'] == source}) for source in SOURCE_SNAPSHOTS},
    'unknown_group_counts': {source: len({row['source_group'] for row in inventory if row['benchmark'] == source and ':unknown:' in row['source_group']}) for source in SOURCE_SNAPSHOTS},
    'exposure_counts': dict(Counter(row['exposure'] for row in inventory)),
    'split_assigned': state['split'] is not None, 'leases': len(state['leases']),
    'custody_state_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    'existing_core_custody_unchanged_since_checkpoint': old_unchanged,
    'existing_core_custody_sha256': old_snapshot['source_sha256'],
    'qualification': 'unassigned_pending_source_family_and_exposure_review',
    'raw_private_payload_returned': False, 'access_isolation': 'not_verified',
    'import_attempt': {'source_import': 'succeeded', 'initial_summary': 'failed_KeyError_group_id',
                       'recovery': 'read_existing_metadata_only_no_reimport'},
}
with Path('work/extended-live-import-metadata.json').open('x', encoding='utf-8') as stream:
    stream.write(canonical(summary))
print(canonical(summary))
