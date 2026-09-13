"""Explicit history-trained candidate provenance; ordinary panels stay unchanged."""
from dataclasses import dataclass

from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, canonical

DESIGNS = {'pair:M1+M9': ('M1','M9'), 'pair:M2+M9': ('M2','M9'), 'pair:M3+M9': ('M3','M9')}


def registered_design(pair, baseline):
    if pair not in DESIGNS: raise ContractError('unimplemented state improvement pair')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[pair])


@dataclass(frozen=True, kw_only=True)
class StateImprovementPanel(CombinationPanel):
    training_provenance: FrozenRecord

    def _training_identities(self, panel_identities):
        if type(self) is not StateImprovementPanel or not isinstance(self.training_provenance,FrozenRecord):
            raise ContractError('exact versioned state improvement panel required')
        p=self.training_provenance.data()
        if (set(p)!={'schema','history_identity','history_binding_digest','target_identities','barrier_digest','outer_plan_digest'}
                or p['schema']!='state-improvement-exposure-v1'
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
        for key in ('history_binding_digest','barrier_digest','outer_plan_digest'):
            value=p[key]
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ContractError('provenance digest malformed')
        return {canonical(identity.data())}

    @property
    def digest(self):
        return FrozenRecord.from_dict({'schema':'state-improvement-panel-v1','base_panel_digest':super().digest,
            'training_provenance':self.training_provenance.data()}).content_hash
