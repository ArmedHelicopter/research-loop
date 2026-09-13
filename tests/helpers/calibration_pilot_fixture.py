"""Synthetic fixtures only, shared by the real one-shot subprocess helper."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.modular.calibration import COVERAGE_KINDS
from evaluation.modular.calibration_pilot import (
    BENCHMARKS, DIMENSIONS, PILOT_SCHEMA, ROLES, DiagnosticAuthority, PortResult,
    slot_id, runtime_code_paths, runtime_code_pins,
)
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import digest

SYNTHETIC_ANSWERS = {
    'valid_positive': 'The synthetic relation is supported.',
    'valid_negative': 'The controlled synthetic test supports no association.',
    'invalid_measurement': 'The synthetic target is constant; the requested measurement is invalid.',
    'uncertain': 'The synthetic evidence is insufficient to decide.',
    'negation_or_quoted_completion': 'The phrase "programme complete" is quoted, not affirmed.',
    'correct_rejection': 'I reject the unsupported synthetic claim.',
    'over_rejection': 'I refuse even the explicitly supported synthetic relation.',
    'reasonable_alternative': 'An equivalent synthetic alternative specification supports the relation.',
    'empty_output': '',
}


def fixture_target(answer, benchmark):
    # Canned hand-authored fixture targets, not a production semantic classifier.
    unknown = {SYNTHETIC_ANSWERS['invalid_measurement'], SYNTHETIC_ANSWERS['uncertain']}
    zero = {SYNTHETIC_ANSWERS['empty_output'], SYNTHETIC_ANSWERS['over_rejection'],
            SYNTHETIC_ANSWERS['negation_or_quoted_completion']}
    if answer in unknown:
        return {'state': 'unknown', 'dimensions': None}
    return {'state': 'known', 'dimensions': {name: 0 if answer in zero else 1 for name in DIMENSIONS[benchmark]}}


def record(value):
    return FrozenRecord.from_dict(value)


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record(value).encoded, encoding='utf-8')
    return {'path': str(path.absolute()), 'sha256': hash_file(path)}


def build_fixture(root):
    authorities = {role: DiagnosticAuthority(role, hashlib.sha256(role.encode()).digest())
                   for role in ('material', 'reviewer1', 'reviewer2', 'arbitrator', 'capacity', 'diagnostic')}
    store = root / 'store'
    tasks, rows = [], []
    for benchmark in BENCHMARKS:
        for index in range(2):
            identity = DataIdentity(benchmark, f'synthetic-{index}', f'synthetic-group-{index}', 'inventory', 'split', 'train')
            handle = digest({'identity': identity.data()})
            context = {'question': 'Synthetic public task', 'index': index}
            ref = record({'schema': 'train-only-rubric-reference-v1', 'split': 'train', 'benchmark': benchmark,
                'task_handle_digest': hashlib.sha256(handle.encode()).hexdigest(), 'identity_digest': digest(identity.data()),
                'task_context': context, 'references': [{'hypothesis': 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL'}]})
            descriptor = write(store / (handle + '.json'), ref.data())
            task_digest = digest({'identity': identity.data(), 'payload': context})
            tasks.append({'identity': identity.data(), 'task_handle': handle, 'task_digest': task_digest, 'reference_digest': ref.content_hash})
            rows.append({'identity': identity.data(), 'identity_digest': digest(identity.data()), 'task_handle': handle,
                'task_digest': task_digest, 'file': handle + '.json', 'reference_sha256': descriptor['sha256']})
    store_desc = write(store / 'manifest.json', {'schema': 'frozen-train-reference-store-v1', 'inventory_digest': 'inventory',
        'split_digest': 'split', 'rows': rows, 'scope': 'train_only', 'scientific_validity': 'not_measured'})
    materials, slots = {}, []
    for task in tasks:
        identity_digest = digest(task['identity'])
        for kind in COVERAGE_KINDS:
            sid = slot_id(identity_digest, kind)
            candidate = {'answer': SYNTHETIC_ANSWERS[kind], 'slot_token': sid}
            material = authorities['material'].issue('material', sid, {'status': 'ready', 'candidate': candidate,
                'expected': fixture_target(candidate['answer'], task['identity']['benchmark']),
                'support_digest': digest({'private_support': sid})})
            materials[sid] = material.data()
            slots.append({'slot_id': sid, 'identity_digest': identity_digest, 'kind': kind, 'status': 'ready',
                          'material_digest': material.content_hash, 'candidate_digest': digest(candidate)})
    source_path = root / 'source-pin.json'
    source = write(source_path, {'synthetic': True})
    ports = {role: {'model': 'synthetic-port-' + role, 'parameters': {'temperature': 0},
        'context_digest': digest({'context': role}), 'tokenizer_digest': digest({'tokenizer': role}),
        'pricing_digest': digest({'pricing': role}), 'context_window': 100000, 'max_output_tokens': 100,
        'max_calls': 72 if role == 'evaluator' else 36, 'max_tokens_per_call': 100000, 'max_microusd_per_call': 1000}
        for role in ROLES}
    manifest = record({'schema': PILOT_SCHEMA, 'tasks': tasks, 'slots': slots,
        'policy': {'ports': ports, 'max_calls': 180, 'max_tokens': 18000000, 'max_microusd': 180000},
        'authorities': {role: authority.authority_id for role, authority in authorities.items()},
        'input_pins': {'source': source['sha256']} | runtime_code_pins(), 'validation_eligible': False})
    manifest_desc = write(root / 'manifest.json', manifest.data())
    materials_desc = write(root / 'materials.json', materials)
    key_files = {}
    for role, authority in authorities.items():
        path = root / ('key-' + role)
        path.write_bytes(authority.key)
        key_files[role] = {'path': str(path.absolute()), 'sha256': hash_file(path)}
    config = record({'schema': 'diagnostic-calibration-worker-config-v1', 'manifest': manifest_desc, 'materials': materials_desc,
        'key_files': key_files, 'reference_store': {'root': str(store.absolute()), 'manifest_sha256': store_desc['sha256'],
            'inventory_digest': 'inventory', 'split_digest': 'split'},
        'input_files': {'source': str(source_path.absolute())} | {name:str(path.absolute()) for name,path in runtime_code_paths().items()},
        'journal_path': str((root / 'private-journal.jsonl').absolute())})
    return manifest, materials, authorities, config


class FixturePorts:
    def __init__(self, manifest, authorities):
        self.manifest, self.authorities = manifest, authorities
        self.calls = {role: [] for role in ROLES}
        self.capacity_calls = []

    def capacity(self, request):
        self.capacity_calls.append(request)
        return self.authorities['capacity'].issue('capacity', request.content_hash, {
            'input_tokens_upper': 1000, 'output_tokens_upper': 100, 'cost_microusd_upper': 1000,
            'reliable': True, 'nonbillable_capacity_check': True})

    def cost(self, role, request):
        return record({'input_tokens': 10, 'output_tokens': 5, 'microusd': 1,
            'request_digest': request.content_hash, 'port_config_digest': digest(self.manifest.data()['policy']['ports'][role]),
            'usage_evidence_digest': digest({'fixture_cost': request.content_hash, 'role': role})})

    def review(self, role, request):
        self.calls[role].append(request)
        body = request.data()
        assert 'expected' not in body and 'kind' not in body and 'other_review' not in body
        target = fixture_target(body['candidate']['answer'], body['benchmark'])
        return PortResult(self.authorities[role].issue(role, request.content_hash, target), self.cost(role, request))

    def evaluator(self, request):
        self.calls['evaluator'].append(request)
        body = request.data()
        assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in body['prompt']
        assert 'support_digest' not in body['prompt'] and 'expected' not in body['prompt']
        candidate = json.loads(body['prompt'].split('\nANONYMOUS_CANDIDATE=',1)[1])
        expected = fixture_target(candidate['answer'], body['benchmark'])
        normalized = expected['dimensions'] if expected['state']=='known' else {name: 1 for name in DIMENSIONS[body['benchmark']]}
        result = {name: value * (2 if body['benchmark']=='blade' else 1) for name,value in normalized.items()}
        return PortResult(record(result | {'reason': 'synthetic canned judge'}), self.cost('evaluator', request))

    def kwargs(self):
        return {'reviewer1': lambda req: self.review('reviewer1', req),
                'reviewer2': lambda req: self.review('reviewer2', req),
                'arbitrator': lambda req: self.review('arbitrator', req),
                'evaluator': self.evaluator, 'capacity_port': self.capacity}
