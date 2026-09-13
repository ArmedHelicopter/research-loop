"""Synthetic source publication and explicit child environment; no native login."""
import json
import os
from pathlib import Path
import sys

from evaluation.modular.calibration import COVERAGE_KINDS
from evaluation.modular.diagnostic_material_authoring import CONFIG_SCHEMA, own_sources
from evaluation.modular.diagnostic_subscription import sha
from research_loop.modular.grok_acp_transport import SinglePromptACP, DIAGNOSTIC_OPPORTUNITY_CONTRACT
from research_loop.ontology import digest
from tests.helpers.calibration_pilot_fixture import build_fixture, write, record


def authored_answer(references):
    rows = []
    for category in COVERAGE_KINDS:
        unavailable = category in ('valid_negative', 'reasonable_alternative')
        rows.append({'category': category, 'status': 'unresolved_material' if unavailable else 'ready',
            'candidate': {'answer': None if unavailable else '' if category == 'empty_output'
                          else 'PRIVATE_SYNTHETIC_CANDIDATE_' + str(len(rows))},
            'support': {'provenance': 'unsupported' if unavailable else 'controlled_hypothetical',
                'negative_basis': 'unresolved' if unavailable else 'not_claimed',
                'reference_indices': [], 'evidence': [],
                'rationale': 'PRIVATE_SYNTHETIC_RATIONALE; provisional synthetic control only.'}})
    rows[0]['support'].update(provenance='reference_supported', reference_indices=[0],
        evidence=[{'reference_index': 0, 'excerpt': references[0]['hypothesis']}])
    return {'slots': rows}


def prepare_fixture(root, reference_bytes=0):
    old, _, _, config = build_fixture(root)
    c = config.data(); store_path = Path(c['reference_store']['root']) / 'manifest.json'
    store = json.loads(store_path.read_text()); checks = []
    for row in store['rows']:
        path = store_path.parent / row['file']; ref = json.loads(path.read_text())
        if reference_bytes:
            ref['references'][0]['hypothesis'] += 'X' * reference_bytes
            row['reference_sha256'] = write(path, ref)['sha256']
        checks.append({'identity_digest': row['identity_digest'], 'resolver_verified': True,
            'task_handle': row['task_handle'], 'reference_file_sha256': row['reference_sha256'],
            'reference_record_digest': record(ref).content_hash, 'reference_count': len(ref['references'])})
    store_desc = write(store_path, store)
    publication = write(root / 'publication.json', {'schema': 'train-reference-publication-v1',
        'scope': 'train_only', 'reference_count': 4, 'manifest_sha256': store_desc['sha256'],
        'inventory_digest': 'inventory', 'split_digest': 'split',
        'task_handles': {r['identity_digest']: r['task_handle'] for r in store['rows']}})
    exported = write(root / 'export-result.json', {'status': 'success', 'requested_train_items': 4,
        'validation_reference_exports': 0, 'model_calls': 0, 'checks': checks, 'private_store_manifest': store_desc})
    c = {'schema': CONFIG_SCHEMA, 'publication': publication, 'export_result': exported,
        'authority_ids': old.data()['authorities'], 'key_files': c['key_files'],
        'source_files': {str(p.absolute()): sha(p) for p in own_sources().values()}, 'native_deployment': None}
    extra = root / 'synthetic-source.json'; write(extra, {'synthetic': True})
    c['source_files'][str(extra)] = sha(extra)
    return write(root / 'authoring-config.private.json', c)


def fixture_factory(mode='authoring'):
    def invoke(entry, prompt, schema, directory, frozen_files, spec):
        checkout = Path(__file__).resolve().parents[2]
        peer = checkout / 'tests' / 'fixtures' / 'grok_acp_peer.py'
        # Set this in the child itself; correctness never depends on the parent
        # pytest runner having an inherited PYTHONPATH.
        return SinglePromptACP([sys.executable, str(peer), mode, str(directory / 'peer.private.jsonl')],
            cwd=directory, env=dict(os.environ, PYTHONPATH=str(checkout)),
            private_dir=directory / 'native', reservation=directory / 'native-reservation.json',
            frozen_files=frozen_files, timeout=10, opportunity_contract=DIAGNOSTIC_OPPORTUNITY_CONTRACT,
            main_output_cap=spec['main_output_cap'], max_total_tokens=spec['observed_main_token_cap'],
            input_byte_cap=spec['max_input_bytes']).invoke(prompt, schema)
    return invoke
