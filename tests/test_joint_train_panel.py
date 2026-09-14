"""C5 panel and real scorer subprocess, using only synthetic signed candidates."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from evaluation.modular.combination_scoring import _panel_cell_digest, verify_combination_adapted_receipt
from evaluation.modular.scorer_process import (CombinationScorerProcessClient, parse_combination_panel,
    parse_server_config, serialize_combination_panel)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, OBLIGATION
from research_loop.modular.joint_train_panel import JointTrainPanel, history_build_id, target_arm
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.ontology import ContractError, canonical, digest
from test_joint_train_protocol import fixture, H
from test_scorer_process import _command, _store
from test_train_adapted_selection import EXEC, SCORER

R = FrozenRecord.from_dict


def panel_fixture(root, patch):
    args, originals, logs = fixture(root, patch)
    protocol = FrozenJointTrainProtocol.freeze(**args)
    body = protocol.record.data()
    recipes = [row['recipe'] for row in body['catalogue']['recipes']]
    builds = {history_build_id(protocol, r): digest({'synthetic_build': history_build_id(protocol, r)}) for r in recipes}
    manifest = TrainingManifest.freeze([args['history'].identity])
    packages = {r['id']: CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={'prompt': {'instructions': history_build_id(protocol, r)}}, search_cost=1) for r in recipes}
    cells = tuple(PanelCell(OBLIGATION, task.identity, 'r1', 'combination', r['id'], target_arm(protocol, r),
        task.content_hash, digest({'synthetic_scenario': task.content_hash, 'protocol': protocol.digest}),
        packages[r['id']].digest, args['scorer'].digest) for r in recipes for task in args['targets'])
    provenance = R({'schema': 'c5-common-history-build-exposure-v1', 'protocol_digest': protocol.digest,
        'runtime_plan_digest': 'b'*64, 'barrier_digest': 'c'*64, 'build_receipts': builds,
        'candidate_selections': {k: v.digest for k, v in packages.items()}})
    panel = JointTrainPanel('synthetic-common-train', 'train', H, OBLIGATION, 'joint_bundle', protocol.record,
        R({'schema': 'c5-common-procedure-package-bundle-v1', 'packages': {k: v.record.data() for k,v in packages.items()}}),
        R({'schema': 'c5-common-train-measurement-criteria-v1', 'train_adapted_selection': body['selection_rule'],
           'scientific_acceptance_authorized': False, 'validation_access_authorized': False}), cells,
        training_provenance=provenance)
    return panel, args, originals, logs


def test_complete_common_panel_roundtrip_preserves_all_candidates(tmp_path, monkeypatch):
    panel, args, _, logs = panel_fixture(tmp_path, monkeypatch)
    wire = serialize_combination_panel(panel, joint_train=True)
    rebuilt = parse_combination_panel(wire, joint_train=True)
    assert type(rebuilt) is JointTrainPanel and rebuilt == panel and rebuilt.digest == panel.digest
    assert len(panel.cells) == len(panel.protocol.record.data()['catalogue']['recipes']) * 3
    assert panel.structurally_unavailable and panel.interaction_status == 'not_identified_by_common_train_ranking'
    assert 'B0' not in panel.acceptance_criteria.data()['train_adapted_selection']['tie_break_order']
    assert len(panel.protocol.record.data()['issue_contracts']) == 48 and not logs
    for flags in ({}, {'full_loo': True}, {'joint_train': True, 'full_loo': True}):
        with pytest.raises(ContractError): serialize_combination_panel(panel, **flags)


@pytest.mark.parametrize('fault', ['validation','missing','duplicate','scorer','runtime_arm',
    'scenario','rule','build_reuse','package_exposure','protocol','shared_build'])
def test_coherent_panel_changes_are_rejected(tmp_path, monkeypatch, fault):
    panel, args, _, logs = panel_fixture(tmp_path, monkeypatch)
    changes = {}
    if fault == 'validation': changes['domain'] = 'validation'
    elif fault == 'missing': changes['cells'] = panel.cells[:-1]
    elif fault == 'duplicate': changes['cells'] = panel.cells[:-1] + (panel.cells[0],)
    elif fault in ('scorer','runtime_arm','scenario'):
        cell = panel.cells[0]
        key, value = {'scorer': ('scorer_digest','e'*64), 'runtime_arm': ('runtime_arm',R({'enabled':[]})),
                      'scenario': ('scenario_digest','f'*64)}[fault]
        changes['cells'] = (replace(cell, **{key:value}), *panel.cells[1:])
    elif fault == 'rule':
        b = panel.acceptance_criteria.data(); b['train_adapted_selection']['tie_break_order'].pop()
        changes['acceptance_criteria'] = R(b)
    elif fault in ('build_reuse','protocol'):
        b = panel.training_provenance.data()
        if fault == 'protocol': b['protocol_digest'] = 'f'*64
        else:
            keys = list(b['build_receipts']); b['build_receipts'][keys[1]] = b['build_receipts'][keys[0]]
        changes['training_provenance'] = R(b)
    elif fault == 'package_exposure':
        b = panel.package_bundle.data(); key = next(iter(b['packages']))
        p = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([args['targets'][0].identity]),
            changes={'prompt':{'instructions':'invalid target exposure'}}, search_cost=1)
        b['packages'][key] = p.record.data(); changes['package_bundle'] = R(b)
    else:
        b = panel.package_bundle.data(); p = panel.training_provenance.data()
        # B0 and ordinary-control have exactly the same frozen history procedure.
        package = CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([args['history'].identity]),
            changes={'prompt':{'instructions':'different shared history package'}},search_cost=1)
        b['packages']['B0'] = package.record.data(); p['candidate_selections']['B0'] = package.digest
        changes.update(package_bundle=R(b), training_provenance=R(p), cells=tuple(
            replace(c,package_digest=package.digest) if c.arm_id=='B0' else c for c in panel.cells))
    with pytest.raises(ContractError): replace(panel, **changes)
    assert not logs


def synthetic_signed_input(panel, cell):
    candidate = {'analysis':'Synthetic analysis only', 'program':'print(1)', 'answer':'中文 fixture only',
                 'execution_feedback':{'status':'succeeded','exit_code':0,'stdout':'1','stderr':''}}
    body = {'schema':'combination-benchmark-score-input-v1', 'panel_digest':panel.digest,
        'design_digest':panel.design.content_hash, 'obligation_id':panel.obligation_id,
        'cell_key':list(cell.key),'identity':cell.identity.data(),'panel_cell_digest':_panel_cell_digest(cell),
        'task_digest':cell.task_digest,'scenario_digest':cell.scenario_digest,'package_digest':cell.package_digest,
        'arm_digest':cell.runtime_arm.content_hash,'scorer_digest':cell.scorer_digest,
        'candidate':candidate,'candidate_digest':digest(candidate),'status':'combination_execution_succeeded',
        'scientific_validity':'not_measured'}
    for key in ('objective_digest','runtime_trace_digest','runtime_output_digest','joint_mechanism_digest',
                'solver_trace_digest','analysis_digest','answer_digest','execution_digest','executed_program_sha256'):
        body[key] = digest({'synthetic':key,'cell':cell.key})
    return EXEC.issue(body)


def test_actual_common_scorer_process_both_benchmarks_and_closed_scope(tmp_path, monkeypatch):
    panel, args, _, logs = panel_fixture(tmp_path, monkeypatch)
    store, handles, manifest = _store(tmp_path, {'tasks':{t.content_hash:t for t in args['targets']}})
    (tmp_path/'exec.key').write_bytes(EXEC.key); (tmp_path/'scorer.key').write_bytes(SCORER.key)
    config = {'schema':'c5-common-train-scorer-process-config-v1', 'panel':serialize_combination_panel(panel,joint_train=True),
        'scorer_config':args['scorer'].record.data(),'scorer_config_digest':args['scorer'].digest,
        'train_reference_store':{'root':str(store.resolve()),'manifest_sha256':manifest,
            'inventory_digest':panel.cells[0].identity.dataset_version,'split_digest':panel.split_digest},
        'task_handles':handles,'execution_authority_key_files':{EXEC.authority_id:str(tmp_path/'exec.key')},
        'scorer_authority':{'id':SCORER.authority_id,'key_file':str(tmp_path/'scorer.key')},'evaluator':{'synthetic_mode':'normal'}}
    assert type(parse_server_config(config).panel) is JointTrainPanel
    with pytest.raises(ContractError): parse_server_config(dict(config,schema='c4-full-loo-scorer-process-config-v1'))
    path=tmp_path/'server.json';path.write_text(canonical(config),encoding='utf-8')
    worker=tmp_path/'worker.jsonl';client_log=tmp_path/'client.jsonl'
    command=_command(path,worker);command[1]=str(Path(__file__).parent/'helpers/joint_train_scorer_process_helper.py')
    client=CombinationScorerProcessClient(panel=panel,config=args['scorer'],joint_train=True,
        command=command,journal_path=client_log,task_handle_bindings={k:digest(v) for k,v in handles.items()},
        execution_authority_keys={EXEC.authority_id:EXEC.key},scorer_authority_keys={SCORER.authority_id:SCORER.key},
        environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    try:
        chosen=[next(c for c in panel.cells if c.identity.benchmark==b and c.arm_id=='ordinary-control')
                for b in ('blade','discoverybench')]
        for cell in chosen:
            score_input=synthetic_signed_input(panel,cell)
            receipt=client.score_combination(panel=panel,cell=cell,score_input=score_input)
            verify_combination_adapted_receipt(receipt,authority_keys={SCORER.authority_id:SCORER.key},config=args['scorer'],
                panel=panel,cell=cell,score_input=score_input,execution_authority_keys={EXEC.authority_id:EXEC.key})
            assert client.score_combination(panel=panel,cell=cell,score_input=score_input)==receipt
    finally: client.close()
    assert client.process.poll() is not None and not logs
    assert len(worker.read_text().splitlines())==4
    assert 'PRIVATE-REFERENCE-SENTINEL' not in client_log.read_text(encoding='utf-8')
    assert 'PRIVATE-REFERENCE-SENTINEL' not in worker.read_text(encoding='utf-8')
