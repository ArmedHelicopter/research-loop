"""Snapshot projection checks; full authenticated integration is in the controller test."""
import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_panel import history_build_id
from research_loop.modular.joint_selected_snapshot import _project, freeze_selected_joint_snapshot
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.ontology import ContractError
from test_joint_train_panel import panel_fixture

R = FrozenRecord.from_dict


def fixture(root, patch):
    panel, args, originals, logs = panel_fixture(root, patch)
    p = panel.protocol.record.data()
    recipe = next(row['recipe'] for row in p['catalogue']['recipes'] if all(row['recipe']['arm_bits'].values()))
    templates = {name: JointComponentVersion(R(v)) for name, v in p['component_templates'].items()}
    package = CandidatePackage(R(panel.package_bundle.data()['packages'][recipe['id']]))
    build = history_build_id(panel.protocol, recipe)
    subject = R({'protocol_digest': panel.protocol.digest, 'recipe': recipe,
        'component_templates': {k: v.digest for k, v in templates.items()}, 'history_build_id': build,
        'history_receipt_digest': panel.training_provenance.data()['build_receipts'][build],
        'panel_digest': panel.digest, 'package_digest': package.digest})
    # This is explicitly a pure projection fixture, not a forged authenticated
    # complete run or a public selection API input.
    choice = R({'schema': 'c5-common-train-selection-v1', 'protocol_digest': panel.protocol.digest,
        'selected_arm': recipe['id'], 'selected_package_digest': package.digest,
        'panel_digest': panel.digest, 'selected_subject': subject.data(),
        'selected_subject_digest': subject.content_hash})
    parent = JointDeploymentBundle.create(parent_digest=None, baseline_digest=p['baseline_digest'],
        p0_digest=p['p0_digest'], resource_schedule=R({'stage': 'synthetic_preceding_snapshot'}), components=templates)
    return panel, choice, package, parent, originals, logs


def test_projection_keeps_all_slots_and_records_selection_target_exposure(tmp_path, monkeypatch):
    panel, choice, package, parent, originals, logs = fixture(tmp_path, monkeypatch)
    snapshot = _project(panel.protocol, choice, package, parent, 20).data()
    bundle = JointDeploymentBundle(R(snapshot['bundle']))
    bundle.verify_sources(originals['component_roots'])
    assert len(bundle.components()) == 9
    expected = {DataIdentity.parse(row['identity']) for row in
                [panel.protocol.record.data()['history'], *panel.protocol.record.data()['targets']]}
    for name, component in bundle.components().items():
        body = component.record.data()
        assert set(TrainingManifest(R(body['training_manifest'])).identities()) == expected
        assert body['state']['selected_package'] == package.record.data()
        assert body['config']['module_id'] == name
    m9 = bundle.components()['M9'].record.data()['config']
    assert m9['history_build_level'] == 1 and m9['target_level'] == 0
    assert bundle.parent_digest == parent.digest and snapshot['bundle_digest'] == bundle.digest
    assert snapshot['validation_access_authorized'] is snapshot['deployment_authorized'] is False
    assert snapshot['acceptance_verified'] is False and not logs


@pytest.mark.parametrize('fault', ['recipe', 'template', 'package', 'baseline', 'p0'])
def test_projection_rejects_subject_or_parent_substitution(tmp_path, monkeypatch, fault):
    panel, choice, package, parent, _, logs = fixture(tmp_path, monkeypatch)
    body = choice.data()
    if fault in ('recipe', 'template'):
        if fault == 'recipe': body['selected_subject']['recipe']['target_levels']['M4'] = 0
        else: body['selected_subject']['component_templates']['M4'] = 'f' * 64
        body['selected_subject_digest'] = R(body['selected_subject']).content_hash
        choice = R(body)
    elif fault == 'package':
        package = CandidatePackage.create(parent_digest=None,
            manifest=TrainingManifest(R(package.record.data()['training_manifest'])),
            changes={'prompt': {'instructions': 'different synthetic package'}}, search_cost=1)
    else:
        changed = parent.record.data(); changed[fault + '_digest'] = 'f' * 64
        parent = JointDeploymentBundle(R(changed))
    with pytest.raises(ContractError): _project(panel.protocol, choice, package, parent, 20)
    assert not logs


def test_projection_result_cannot_substitute_for_original_authenticated_run(tmp_path, monkeypatch):
    panel, choice, package, parent, _, logs = fixture(tmp_path, monkeypatch)
    snapshot = _project(panel.protocol, choice, package, parent, 20)
    with pytest.raises(ContractError, match='original complete common TRAIN'):
        freeze_selected_joint_snapshot(snapshot, parent=parent,
            execution_authority_keys={}, scorer_authority_keys={})
    assert not logs
