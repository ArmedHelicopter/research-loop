"""C4 joint bundle panel. Its procedure grid is not a factorial design."""
from dataclasses import dataclass
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.full_loo_composition import FrozenFullLooPlan, candidate_build_key
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.ontology import ContractError

OBLIGATION = 'c4-full-loo-joint-v1'


def runtime_arm(plan, recipe, stage='target'):
    return default_compatibility(plan.data()['baseline_digest']).arm(
        [m for m, level in recipe[stage+'_levels' if stage == 'target' else 'history_build_levels'].items() if level])


@dataclass(frozen=True, kw_only=True)
class FullLooPanel(CombinationPanel):
    training_provenance: FrozenRecord

    def __post_init__(self):
        if type(self) is not FullLooPanel or not isinstance(self.training_provenance, FrozenRecord):
            raise ContractError('exact C4 panel required')
        plan = FrozenFullLooPlan(self.design); b = plan.data(); p = self.training_provenance.data()
        if (self.obligation_id != OBLIGATION or self.domain != 'train' or self.estimand != 'joint_bundle'
                or not self.stage or tuple(self.required_benchmarks) != ('discoverybench','blade')
                or set(p) != {'schema','history_identity','history_binding_digest','barrier_digest','outer_plan_digest','candidate_selections'}
                or p['schema'] != 'c4-history-build-exposure-v1'):
            raise ContractError('C4 scope or exposure drift')
        history = DataIdentity.parse(p['history_identity']); history.require_train()
        if p['history_binding_digest'] != b['cells'][0]['history_binding_digest']:
            raise ContractError('C4 history digest differs')
        for key in ('barrier_digest','outer_plan_digest'):
            if not isinstance(p[key], str) or len(p[key]) != 64 or any(c not in '0123456789abcdef' for c in p[key]):
                raise ContractError('C4 provenance digest required')
        recipes = {r['id']: r for r in b['cells'] if r['status'] == 'executable'}
        bundle = self.package_bundle.data()
        if set(bundle) != {'schema','packages'} or bundle['schema'] != 'c4-procedure-package-bundle-v1' or set(bundle['packages']) != set(recipes):
            raise ContractError('C4 package identity must include procedure, including both ordinary controls')
        packages = {k: CandidatePackage(FrozenRecord.from_dict(v)) for k,v in bundle['packages'].items()}
        groups = {}; keys = set(); shares = {}
        if len(self.cells) != 22 or any(type(c) is not PanelCell for c in self.cells):
            raise ContractError('C4 exact 22 executable target cells required')
        for c in self.cells:
            c.identity.require_train()
            if (c.arm_id not in recipes or c.coverage_id != OBLIGATION or c.variant != 'combination' or c.replicate != 'r1'
                    or c.identity.split_id != self.split_digest or c.task_digest not in b['train_task_digests']
                    or c.runtime_arm != runtime_arm(plan, recipes[c.arm_id]) or c.package_digest != packages[c.arm_id].digest
                    or c.key in keys or (c.identity.benchmark,c.identity.task_id,c.identity.group_id) == (history.benchmark,history.task_id,history.group_id)):
                raise ContractError('C4 cell, procedure, package, or history/target isolation drift')
            keys.add(c.key); groups.setdefault(c.task_digest, []).append(c)
            key = candidate_build_key(recipes[c.arm_id]); shares.setdefault(key,set()).add(c.package_digest)
        if (len(groups) != 2 or {c.identity.benchmark for c in self.cells} != {'blade','discoverybench'}
                or len({c.scorer_digest for c in self.cells}) != 1
                or any(len(v) != 1 for v in shares.values())):
            raise ContractError('C4 exact target coverage or shared build drift')
        for rows in groups.values():
            if {c.arm_id for c in rows} != set(recipes) or len({c.identity for c in rows}) != 1 or len({c.scenario_digest for c in rows}) != 1:
                raise ContractError('C4 incomplete matched task grid')
        for package in packages.values():
            if set(TrainingManifest(FrozenRecord.from_dict(package.record.data()['training_manifest'])).identities()) != {history}:
                raise ContractError('C4 optimizer manifest must contain only fixed history')
        expected = {k: v.digest for k,v in packages.items()}
        if p['candidate_selections'] != expected:
            raise ContractError('C4 package exposure differs from candidate selections')

    @property
    def digest(self):
        return FrozenRecord.from_dict({'schema':'c4-full-loo-panel-v1','base':super().digest,
            'training_provenance':self.training_provenance.data()}).content_hash

    @property
    def arm_schedule(self):
        return tuple(sorted({OBLIGATION+':'+c.arm_id for c in self.cells}))

    @property
    def interaction_status(self): return 'not_identifiable'
