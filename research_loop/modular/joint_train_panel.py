"""C5 common TRAIN grid, with a separate identity from the C4 experiment.

This is a scorer input contract. Its build digests name originals that the
owning controller must replay; constructing a panel does not verify execution.
"""
from dataclasses import dataclass

from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.full_loo_composition import candidate_build_key
from research_loop.modular.joint_deployment import _hash
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, OBLIGATION
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict


def history_build_id(protocol, recipe):
    return R({'protocol_digest': protocol.digest,
              'canonical_history_recipe': candidate_build_key(recipe)}).content_hash


def target_arm(protocol, recipe):
    return default_compatibility(protocol.record.data()['baseline_digest']).arm(
        [name for name, level in recipe['target_levels'].items() if level])


@dataclass(frozen=True, kw_only=True)
class JointTrainPanel(CombinationPanel):
    training_provenance: FrozenRecord

    @property
    def protocol(self):
        return FrozenJointTrainProtocol(self.design)

    def __post_init__(self):
        if (type(self) is not JointTrainPanel or type(self.training_provenance) is not FrozenRecord
                or type(self.acceptance_criteria) is not FrozenRecord
                or type(self.package_bundle) is not FrozenRecord):
            raise ContractError('exact common TRAIN panel and frozen records required')
        protocol = self.protocol
        body = protocol.record.data()
        if (self.domain != 'train' or self.obligation_id != OBLIGATION
                or self.estimand != 'joint_bundle' or not isinstance(self.stage, str) or not self.stage
                or self.required_benchmarks != ('discoverybench', 'blade')):
            raise ContractError('common TRAIN panel scope differs')
        history = DataIdentity.parse(body['history']['identity'])
        if self.split_digest != history.split_id:
            raise ContractError('common TRAIN split differs')
        criteria = {'schema': 'c5-common-train-measurement-criteria-v1',
            'train_adapted_selection': body['selection_rule'],
            'scientific_acceptance_authorized': False, 'validation_access_authorized': False}
        if self.acceptance_criteria.data() != criteria:
            raise ContractError('common precommitted ranking rule differs')
        recipes = {row['recipe']['id']: row['recipe'] for row in body['catalogue']['recipes']}
        package_body = self.package_bundle.data()
        if (set(package_body) != {'schema', 'packages'}
                or package_body['schema'] != 'c5-common-procedure-package-bundle-v1'
                or set(package_body['packages']) != set(recipes)):
            raise ContractError('common package inventory differs')
        packages = {key: CandidatePackage(R(value)) for key, value in package_body['packages'].items()}
        for package in packages.values():
            manifest = TrainingManifest(R(package.record.data()['training_manifest']))
            if set(manifest.identities()) != {history}:
                raise ContractError('common package may expose only the fixed TRAIN history')
        provenance = self.training_provenance.data()
        if (set(provenance) != {'schema', 'protocol_digest', 'runtime_plan_digest', 'barrier_digest',
                              'build_receipts', 'candidate_selections'}
                or provenance['schema'] != 'c5-common-history-build-exposure-v1'
                or provenance['protocol_digest'] != protocol.digest
                or provenance['candidate_selections'] != {k: p.digest for k, p in packages.items()}):
            raise ContractError('common original build exposure differs')
        for key in ('runtime_plan_digest', 'barrier_digest'):
            _hash(provenance[key], key)
        build_keys = {history_build_id(protocol, recipe) for recipe in recipes.values()}
        if set(provenance['build_receipts']) != build_keys:
            raise ContractError('common canonical history build inventory differs')
        for value in provenance['build_receipts'].values():
            _hash(value, 'build receipt')
        if len(set(provenance['build_receipts'].values())) != len(build_keys):
            raise ContractError('different canonical builds cannot reuse one receipt')
        shares = {}
        for key, recipe in recipes.items():
            shares.setdefault(history_build_id(protocol, recipe), set()).add(packages[key].digest)
        if any(len(values) != 1 for values in shares.values()):
            raise ContractError('identical history build must select one fixed package')
        targets = {row['task_digest']: row for row in body['targets']}
        if type(self.cells) is not tuple or len(self.cells) != len(recipes) * len(targets):
            raise ContractError('complete common target grid required')
        expected = {(arm, task) for arm in recipes for task in targets}
        pairs, keys, scenarios = set(), set(), {}
        scorer = ScorerConfig(R(body['scorer']))
        for cell in self.cells:
            if type(cell) is not PanelCell or (cell.arm_id, cell.task_digest) not in expected:
                raise ContractError('foreign common TRAIN cell')
            cell.identity.require_train()
            row = targets[cell.task_digest]
            if (cell.identity.data() != row['identity'] or cell.coverage_id != OBLIGATION
                    or cell.variant != 'combination' or cell.replicate != body['replicate']
                    or cell.runtime_arm != target_arm(protocol, recipes[cell.arm_id])
                    or cell.package_digest != packages[cell.arm_id].digest or cell.scorer_digest != scorer.digest
                    or cell.key in keys or (cell.arm_id, cell.task_digest) in pairs):
                raise ContractError('common cell activation, subject or package differs')
            keys.add(cell.key); pairs.add((cell.arm_id, cell.task_digest))
            scenarios.setdefault(cell.task_digest, set()).add(cell.scenario_digest)
        if pairs != expected or any(len(values) != 1 for values in scenarios.values()):
            raise ContractError('common grid must share one frozen scenario for each target')

    @property
    def digest(self):
        return R({'schema': 'c5-common-train-panel-v1', 'base_digest': super().digest,
                  'training_provenance': self.training_provenance.data()}).content_hash

    @property
    def arm_schedule(self):
        return tuple(sorted({OBLIGATION + ':' + c.arm_id for c in self.cells}))

    @property
    def structurally_unavailable(self):
        return tuple(self.protocol.record.data()['catalogue']['structural_origins'])

    @property
    def interaction_status(self):
        return 'not_identified_by_common_train_ranking'
