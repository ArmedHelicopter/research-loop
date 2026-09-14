"""Real projection-to-subject seam; authentication remains the controller's job."""
import pytest

from research_loop.modular.artifact_subjects import JointBundleSubject
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_selected_snapshot import _project
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.ontology import ContractError
from test_joint_selected_snapshot import fixture

R=FrozenRecord.from_dict


def test_subject_uses_actual_snapshot_projection_and_all_selection_data(tmp_path,monkeypatch):
    panel,choice,package,parent,_,logs=fixture(tmp_path,monkeypatch)
    snapshot=_project(panel.protocol,choice,package,parent,20)
    subject=JointBundleSubject.from_selected_snapshot(snapshot,panel.protocol,parent=parent,timeout_seconds=20)
    p=panel.protocol.record.data()
    assert subject.train_identities=={DataIdentity.parse(row['identity']) for row in [p['history'],*p['targets']]}
    assert subject.digest==snapshot.data()['bundle_digest'] and not logs


@pytest.mark.parametrize('fault',['selection','protocol','bundle','component','provenance','flags','consumer'])
def test_selected_subject_rejects_substitution_in_real_projection(tmp_path,monkeypatch,fault):
    panel,choice,package,parent,_,logs=fixture(tmp_path,monkeypatch)
    data=_project(panel.protocol,choice,package,parent,20).data()
    if fault in ('selection','protocol','bundle'):
        data[fault+'_digest']='f'*64
    elif fault=='component':
        data['component_digests']['M4']='f'*64
    elif fault=='provenance':
        history=DataIdentity.parse(panel.protocol.record.data()['history']['identity'])
        data['training_provenance']=TrainingManifest.freeze([history]).record.data()
    elif fault=='flags':
        data['acceptance_verified']=True
    else:
        original=JointDeploymentBundle(R(data['bundle']))
        components=original.components();body=components['M4'].record.data()
        body['config']['target_level']=1-body['config']['target_level']
        components['M4']=JointComponentVersion(R(body))
        bundle_body=original.record.data()
        altered=JointDeploymentBundle.create(parent_digest=original.parent_digest,
            baseline_digest=bundle_body['baseline_digest'],p0_digest=bundle_body['p0_digest'],
            resource_schedule=R(bundle_body['resource_schedule']),components=components)
        data.update(bundle=altered.record.data(),bundle_digest=altered.digest,
                    component_digests={name:component.digest for name,component in components.items()})
    with pytest.raises(ContractError):
        JointBundleSubject.from_selected_snapshot(R(data),panel.protocol,parent=parent,timeout_seconds=20)
    assert not logs
