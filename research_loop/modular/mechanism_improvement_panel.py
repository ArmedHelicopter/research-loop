"""Explicit history-trained candidate provenance; ordinary panels stay unchanged."""
from dataclasses import dataclass

from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, canonical

DESIGNS = {'pair:M4+M9': ('M4','M9'), 'pair:M5+M9': ('M5','M9'), 'pair:M6+M9': ('M6','M9')}


def registered_design(pair, baseline):
    if pair not in DESIGNS: raise ContractError('unimplemented state improvement pair')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[pair])


@dataclass(frozen=True, kw_only=True)
class MechanismImprovementPanel(CombinationPanel):
    training_provenance: FrozenRecord

    def _training_identities(self, panel_identities):
        if type(self) is not MechanismImprovementPanel or not isinstance(self.training_provenance,FrozenRecord):
            raise ContractError('exact versioned state improvement panel required')
        p=self.training_provenance.data()
        if (set(p)!={'schema','history_identity','history_binding_digest','target_identities','barrier_digest','outer_plan_digest','candidate_selection_digest'}
                or p['schema']!='mechanism-improvement-exposure-v1'
                or self.obligation_id not in DESIGNS
                or self.design!=registered_design(self.obligation_id,self.design.data()['compatibility']['baseline_digest'])):
            raise ContractError('state improvement provenance or design drift')
        identity=DataIdentity.parse(p['history_identity']);identity.require_train()
        targets=[DataIdentity.parse(i) for i in p['target_identities']]
        for target in targets: target.require_train()
        if ({canonical(i.data()) for i in targets}!=panel_identities or len(targets)!=len(panel_identities)
                or canonical(identity.data()) in panel_identities
                or any((identity.benchmark,identity.task_id,identity.group_id)==(t.benchmark,t.task_id,t.group_id) for t in targets)):
            raise ContractError('optimizer history and target roles must be exact and disjoint')
        for key in ('history_binding_digest','barrier_digest','outer_plan_digest','candidate_selection_digest'):
            value=p[key]
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ContractError('provenance digest malformed')
        by_id={c.arm_id:c.package_digest for c in self.cells}
        if by_id.get('00')!=by_id.get('10') or by_id.get('01')!=by_id.get('11'):
            raise ContractError('target-only factor must share its exact M9-level candidate')
        return {canonical(identity.data())}

    @property
    def digest(self):
        return FrozenRecord.from_dict({'schema':'mechanism-improvement-panel-v1','base_panel_digest':super().digest,
            'training_provenance':self.training_provenance.data()}).content_hash
