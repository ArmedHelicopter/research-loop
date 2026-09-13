"""Coherently signed source-cost changes must not bypass M9 stop rules."""
from dataclasses import replace
import hashlib
import json
import pytest

import test_state_improvement_train_controller as state
import test_mechanism_improvement_train_controller as mechanism
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_driver import _source_binding
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import verify_trace
from research_loop.modular.state_improvement_build import verify_build, build_binding
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import ContractError, canonical
from test_modular_combination_benchmark_driver import _rewrite_trace


@pytest.fixture(scope='module')
def state_grid(tmp_path_factory):
    return state.grid.__wrapped__(tmp_path_factory)


@pytest.fixture(scope='module')
def mechanism_grid(tmp_path_factory):
    return mechanism.grid.__wrapped__(tmp_path_factory)


def unknown_source(path, verifier):
    body = json.loads(path.read_bytes())
    for row, authority in zip(body['calls'], verifier.authorities, strict=True):
        signed = {k: v for k, v in row['response']['body'].items() if k != 'authority'}
        signed['cost_units'] = None
        row.update(response=authority.authority.issue(signed).data(), cost_units=None, cost_unknown=True)
    path.write_text(canonical(body), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def forbid_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('replay must not execute new Docker work')
    monkeypatch.setattr(DockerExecutionBroker, 'execute', forbidden)


def preserve(root, *, original_source, original_trace, source, trace, rejected, issued=None):
    (root / 'original-source.json').write_bytes(original_source)
    (root / 'original-trace.jsonl').write_bytes(original_trace)
    (root / 'forged-source.json').write_bytes(source.read_bytes())
    (root / 'forged-trace.jsonl').write_bytes(trace.read_bytes())
    (root / 'counterexample.json').write_text(canonical({
        'original_verified': True, 'generic_verified': True, 'family_rejected': rejected,
        'score_input_issued': issued is not None,
        'score_input_digest': issued.content_hash if issued is not None else None,
        'new_model_calls_during_replay': 0, 'new_source_calls_during_replay': 0,
        'new_docker_calls_during_replay': 0,
    }), encoding='utf-8')


def target_attack(grid, module, pair, corpus, tmp_path, monkeypatch):
    setup, run = grid
    assert run.receipt.data()['status'] == 'complete_train_engineering'
    result = next(r for r in reversed(run.results) if r.cell.coverage_id == pair)
    args = module.replay_args(setup, run, result)
    issue = (state.issue_state_improvement_score_input if module is state
             else mechanism.issue_mechanism_improvement_score_input)
    forbid_execution(monkeypatch)
    counts = (len(setup['calls']), len(setup['port'].ledger['calls']), len(setup.get('corpus_calls', [])))
    issue(authority=module.EXECUTION, result=result, **args)
    path = result.runtime.trace_path
    source = path.parent.parent / ('retrieval/source-verification.json' if corpus else 'source-verification.json')
    original, trace = source.read_bytes(), path.read_bytes()
    qualifier = args['retrieval_verifier'] if corpus else args['source_verifier']
    material = args['retrieval_material'] if corpus else args['material']
    stage = ('state' if module is state else 'mechanism') + '_improvement_transition'
    field = 'retrieval_source_sha256' if corpus else 'source_sha256'
    rejected = False; issued = None
    try:
        sha = unknown_source(source, qualifier)
        assert qualifier.replay(material, source, cell_binding=_source_binding(result.cell)) == sha
        def mutate(rows):
            next(row for row in rows if row['stage'] == stage)['data'][field] = sha
        tail = _rewrite_trace(path, mutate)
        forged = replace(result, runtime=replace(result.runtime, trace_digest=tail))
        PanelReceiptVerifier()._verify_runtime(forged.runtime, forged.cell)
        try:
            issued = issue(authority=module.EXECUTION, result=forged, **args)
        except ContractError as exc:
            assert 'unknown' in str(exc) and 'cost' in str(exc)
            rejected = True
        preserve(tmp_path, original_source=original, original_trace=trace,
                 source=source, trace=path, rejected=rejected, issued=issued)
        assert counts == (len(setup['calls']), len(setup['port'].ledger['calls']), len(setup.get('corpus_calls', [])))
        assert rejected, 'signed unknown cost bypasses successful M9 target replay'
    finally:
        source.write_bytes(original); path.write_bytes(trace)
    issue(authority=module.EXECUTION, result=result, **args)


@pytest.mark.parametrize('pair', ['pair:M1+M9', 'pair:M2+M9', 'pair:M3+M9'])
def test_state_target_replay_rejects_signed_unknown_cost(state_grid, pair, tmp_path, monkeypatch):
    target_attack(state_grid, state, pair, False, tmp_path, monkeypatch)


@pytest.mark.parametrize('pair,corpus', [
    ('pair:M4+M9', False), ('pair:M5+M9', False), ('pair:M6+M9', False), ('pair:M6+M9', True),
])
def test_mechanism_target_replay_rejects_signed_unknown_cost(mechanism_grid, pair, corpus, tmp_path, monkeypatch):
    target_attack(mechanism_grid, mechanism, pair, corpus, tmp_path, monkeypatch)


@pytest.mark.parametrize('pair', ['pair:M1+M9', 'pair:M3+M9'])
def test_build_replay_rejects_signed_unknown_cost(state_grid, pair, tmp_path, monkeypatch):
    setup, run = state_grid
    build = next(b for b in run.builds if b.record.data()['recipe']['pair'] == pair)
    args = state.build_args(setup, run, build)
    forbid_execution(monkeypatch)
    verify_build(build, **args)
    source = build.root / 'source/source-verification.json'
    trace = build.root / 'proposal/trace.jsonl'
    receipt = build.root / 'build-receipt.json'
    original_source, original_trace, original_receipt = source.read_bytes(), trace.read_bytes(), receipt.read_bytes()
    counts = len(setup['calls']), len(setup['port'].ledger['calls'])
    rejected = False
    try:
        sha = unknown_source(source, args['qualifier'])
        binding = build_binding(args['plan_digest'], args['recipe'])
        assert args['qualifier'].replay(args['material'], source, cell_binding=binding) == sha
        def mutate(rows):
            next(row for row in rows if row['stage'] == 'state_improvement_history')['data']['source_sha256'] = sha
        _rewrite_trace(trace, mutate); verify_trace(trace)
        metadata = build.record.data()
        metadata['files'] = {name: hashlib.sha256((build.root / name).read_bytes()).hexdigest()
                             for name in metadata['files']}
        forged = replace(build, record=FrozenRecord.from_dict(metadata))
        receipt.write_text(forged.record.encoded + '\n', encoding='utf-8', newline='\n')
        try:
            verify_build(forged, **args)
        except ContractError as exc:
            assert 'unknown' in str(exc) and 'cost' in str(exc)
            rejected = True
        preserve(tmp_path, original_source=original_source, original_trace=original_trace,
                 source=source, trace=trace, rejected=rejected)
        (tmp_path / 'original-build-receipt.json').write_bytes(original_receipt)
        (tmp_path / 'forged-build-receipt.json').write_bytes(receipt.read_bytes())
        assert counts == (len(setup['calls']), len(setup['port'].ledger['calls']))
        assert rejected, 'coherent build receipt bypasses unknown source cost stop rule'
    finally:
        source.write_bytes(original_source); trace.write_bytes(original_trace); receipt.write_bytes(original_receipt)
    verify_build(build, **args)
