"""Freeze the complete TRAIN-selected recipe as nine atomic component versions.

This produces the candidate subject for independent V_final acceptance. It
cannot authorize validation access, create an acceptance grant, or activate a
store. A component's provenance includes selection targets as well as history.
"""
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.full_loo_modules import slots
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_panel import history_build_id
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict


def _project(protocol, selection, package, parent, timeout_seconds):
    """Pure projection after authentication; never an independent grant API."""
    if (type(protocol) is not FrozenJointTrainProtocol or type(selection) is not FrozenRecord
            or type(package) is not CandidatePackage or type(parent) is not JointDeploymentBundle):
        raise ContractError('typed common selection, package and preceding snapshot required')
    protocol.__post_init__(); parent.__post_init__()
    p = protocol.record.data(); choice = selection.data()
    subject = choice.get('selected_subject', {})
    recipes = {row['recipe']['id']: row['recipe'] for row in p['catalogue']['recipes']}
    recipe = recipes.get(choice.get('selected_arm'))
    templates = {name: JointComponentVersion(R(value)) for name, value in p['component_templates'].items()}
    template_digests = {name: value.digest for name, value in templates.items()}
    if (choice.get('schema') != 'c5-common-train-selection-v1' or recipe is None or recipe['id'] == 'B0'
            or choice.get('protocol_digest') != protocol.digest or subject.get('protocol_digest') != protocol.digest
            or subject.get('recipe') != recipe or subject.get('component_templates') != template_digests
            or choice.get('selected_subject_digest') != R(subject).content_hash
            or subject.get('history_build_id') != history_build_id(protocol, recipe)
            or subject.get('panel_digest') != choice.get('panel_digest')
            or choice.get('selected_package_digest') != package.digest
            or subject.get('package_digest') != package.digest):
        raise ContractError('selected recipe, package or component subject differs')
    if (parent.record.data()['baseline_digest'] != p['baseline_digest']
            or parent.record.data()['p0_digest'] != p['p0_digest']):
        raise ContractError('selected snapshot cannot replace baseline or P0')
    if type(timeout_seconds) is not int or timeout_seconds <= 0:
        raise ContractError('selected target timeout must remain explicit')
    history = DataIdentity.parse(p['history']['identity'])
    if set(TrainingManifest(R(package.record.data()['training_manifest'])).identities()) != {history}:
        raise ContractError('selected package must come from the fixed TRAIN history')
    # Target scores influence the chosen deployment, even though the inner
    # learned package itself was produced from the history task only.
    provenance = TrainingManifest.freeze([history, *[DataIdentity.parse(t['identity']) for t in p['targets']]])
    components = {}
    for name, template in templates.items():
        original = template.record.data()
        components[name] = JointComponentVersion(R({
            **original,
            'config': {'schema': 'c5-selected-component-consumer-v1', 'module_id': name,
                'template_digest': template.digest, 'consumer_config': original['config'],
                'history_build_level': recipe['history_build_levels'][name],
                'target_level': recipe['target_levels'][name]},
            'state': {'schema': 'c5-selected-component-state-v1', 'template_state': original['state'],
                'selected_package': package.record.data(), 'selection_digest': selection.content_hash,
                'history_receipt_digest': subject['history_receipt_digest']},
            'training_manifest': provenance.record.data()}))
    schedule = R({'schema': 'c5-selected-target-schedule-v1', 'recipe': recipe,
        'slots': list(slots(recipe, 'target')), 'context_budget_bytes': p['context_bytes'],
        'timeout_seconds': timeout_seconds})
    bundle = JointDeploymentBundle.create(parent_digest=parent.digest,
        baseline_digest=p['baseline_digest'], p0_digest=p['p0_digest'],
        resource_schedule=schedule, components=components)
    return R({'schema': 'c5-selected-joint-snapshot-v1',
        'protocol_digest': protocol.digest, 'selection': choice, 'selection_digest': selection.content_hash,
        'selected_subject_digest': choice['selected_subject_digest'],
        'package_digest': package.digest, 'parent_digest': parent.digest,
        'bundle': bundle.record.data(), 'bundle_digest': bundle.digest,
        'component_digests': {name: value.digest for name, value in components.items()},
        'training_provenance': provenance.record.data(),
        'status': 'awaiting_independent_v_final', 'validation_access_authorized': False,
        'acceptance_verified': False, 'deployment_authorized': False})


def freeze_selected_joint_snapshot(run, *, parent, execution_authority_keys, scorer_authority_keys):
    """Freshly authenticate and rank the complete run, then freeze all slots.

    The preceding bundle is the expected active parent for a later atomic
    activation. Concurrent changes remain subject to the store's parent check.
    No alternative recipe, score input or candidate package is accepted here.
    """
    from research_loop.modular.joint_train_selection import select_joint_common_train
    selection = select_joint_common_train(run, execution_authority_keys=execution_authority_keys,
                                         scorer_authority_keys=scorer_authority_keys)
    choice = selection.data()
    package = CandidatePackage(R(run.panel.package_bundle.data()['packages'][choice['selected_arm']]))
    return _project(run.plan.protocol, selection, package, parent, run.plan.data()['timeout_seconds'])


def verify_selected_joint_snapshot(snapshot, run, *, parent, execution_authority_keys, scorer_authority_keys):
    """Reconstruct from current complete TRAIN originals; no saved-hash shortcut."""
    if type(snapshot) is not FrozenRecord:
        raise ContractError('exact selected snapshot required')
    expected = freeze_selected_joint_snapshot(run, parent=parent,
        execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
    if snapshot != expected:
        raise ContractError('selected deployment snapshot differs from current TRAIN originals')
    return JointDeploymentBundle(R(snapshot.data()['bundle']))
