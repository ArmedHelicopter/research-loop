"""Read-only typed-relation views for verified M2 ledger artifacts.

This module deliberately leaves the M2 bridge byte-stable: bridge-source
snapshots are part of every recorded M2 payload.  The existing semantic replay
remains the sole authority for whether a historical ledger can be read.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from research_loop.modular import evidence_artifacts
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def _catalogue_anchor(catalogue):
    raw = Path(catalogue.path).read_bytes()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def project_m2_typed_edges(catalogue, sidecar, *, seal=None):
    """Project only M2 payload relations after the existing semantic replay.

    Descriptor parents intentionally remain out of this view: runtime attaches
    the latest trace descriptor to every module output for chronology, whereas
    this projection reports only relations rebuilt from the M2 ledger payload.
    The existing replay requires the installed M2 bridge source to match the
    recorded bridge source; this reader does not execute archived source from
    another worktree.
    """
    if type(seal) is not FrozenRecord:
        raise ContractError('M2 projection needs a sealed catalogue')
    catalogue.verify(seal)
    anchor = _catalogue_anchor(catalogue)
    records = catalogue.records()
    if _catalogue_anchor(catalogue) != anchor:
        raise ContractError('M2 projection catalogue changed during snapshot')
    checked = evidence_artifacts.verify_evidence_artifacts(catalogue, sidecar)
    if _catalogue_anchor(catalogue) != anchor:
        raise ContractError('M2 projection catalogue changed during semantic replay')
    catalogue.verify(seal)
    nodes, edges = [], []
    for descriptor in records:
        body = descriptor.data()
        payload = body['payload']['canonical']
        if (body['kind'] != 'ledger_event' or body['module'] != 'M2'
                or not isinstance(payload, dict) or payload.get('schema') != 'm2-ledger-artifact-v1'):
            continue
        output = payload['output']
        needs_review = output.get('needs_review') if isinstance(output, dict) else None
        if needs_review is not None and type(needs_review) is not bool:
            raise ContractError('M2 projection needs-review field is invalid')
        nodes.append({'descriptor_digest': descriptor.content_hash, 'status': body['status'],
                      'module_enabled': payload['module_enabled'], 'journal': payload['journal'], 'event': payload['event']['event'],
                      'needs_review': needs_review})
        for relation in payload['relations']:
            if set(relation) != {'relation', 'artifact'} or not isinstance(relation['relation'], str) or not relation['relation']:
                raise ContractError('M2 projection relation is invalid')
            edges.append({'from_descriptor_digest': descriptor.content_hash,
                          'relation': relation['relation'], 'to_descriptor_digest': relation['artifact']})
    seal_digest = seal.content_hash if seal is not None else None
    return FrozenRecord.from_dict({'schema': 'm2-typed-edge-projection-v1',
        'identity': catalogue.identity.data(), 'catalogue_head': seal.data()['head'] if seal is not None else None,
        'catalogue_seal_digest': seal_digest, 'replay_digest': checked.content_hash,
        'semantic_replay_source': source_snapshot(Path(evidence_artifacts.__file__)),
        'nodes': nodes, 'edges': edges, 'scientific_validated': False})


def query_m2_withdrawal_observations(withdrawal_descriptor_digest, sources):
    """Return explicit observations under one current M2 bridge source only.

    It never claims a closed consumer scope or treats an observation as a
    causal affected artifact.  Historical source is rejected when the existing
    M2 replay cannot reproduce its semantics from the installed bridge source.
    """
    if not isinstance(withdrawal_descriptor_digest, str) or not withdrawal_descriptor_digest:
        raise ContractError('M2 withdrawal query needs a descriptor digest')
    withdrawn_roots, observed = [], []
    replay_source = source_snapshot(Path(evidence_artifacts.__file__))
    for source in sources:
        if not isinstance(source, tuple) or len(source) != 3:
            raise ContractError('M2 withdrawal query needs explicit catalogue, sidecar and seal')
        catalogue, sidecar, seal = source
        if type(seal) is not FrozenRecord:
            raise ContractError('M2 withdrawal query needs a sealed catalogue')
        body = project_m2_typed_edges(catalogue, sidecar, seal=seal).data()
        if replay_source != body['semantic_replay_source']:
            raise ContractError('M2 withdrawal query crosses semantic replay sources')
        nodes = {row['descriptor_digest']: row for row in body['nodes']}
        for edge in body['edges']:
            if edge['relation'] == 'withdraws' and edge['from_descriptor_digest'] == withdrawal_descriptor_digest:
                withdrawn_roots.append({'identity': body['identity'], 'catalogue_seal_digest': body['catalogue_seal_digest'],
                                        'descriptor_digest': edge['to_descriptor_digest']})
            if edge['relation'] == 'withdrawal_observed' and edge['to_descriptor_digest'] == withdrawal_descriptor_digest:
                node = nodes.get(edge['from_descriptor_digest'])
                if node is None:
                    raise ContractError('M2 withdrawal observation lacks a projected node')
                observed.append({'identity': body['identity'], 'catalogue_seal_digest': body['catalogue_seal_digest'],
                                 'descriptor_digest': edge['from_descriptor_digest'], 'event': node['event'],
                                 'status': node['status'], 'module_enabled': node['module_enabled'],
                                 'needs_review': node['needs_review']})
    return FrozenRecord.from_dict({'schema': 'm2-withdrawal-observation-query-v1',
        'withdrawal_descriptor_digest': withdrawal_descriptor_digest, 'withdrawn_roots': withdrawn_roots, 'observed': observed,
        'semantic_replay_source': replay_source, 'complete': False, 'unknown_scope': True, 'scientific_validated': False})
