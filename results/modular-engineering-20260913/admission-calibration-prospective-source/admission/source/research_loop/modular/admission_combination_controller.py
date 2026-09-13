"""Closed three-panel M1 controller sharing the established lineage kernel."""
from research_loop.modular.lineage_combination_controller import (
    FrozenLineageTrainConfig, compile_lineage_train_panels, run_lineage_train_panels)


class FrozenAdmissionTrainConfig(FrozenLineageTrainConfig):
    def __post_init__(self):
        super().__post_init__()
        from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
        from research_loop.ontology import ContractError
        if len(self.data()['item_ids']) != 2 or len(self.data()['replicates']) != 1:
            raise ContractError('admission pilot freezes exactly two tasks and one replicate: 24 cells')
        if self.data()['scorer']['rubric_digest'] != FrozenBenchmarkRubricEndpoint.rubric_digest():
            raise ContractError('admission controller requires the exact frozen primary rubric')


def compile_admission_train_panels(config, packets):
    from research_loop.ontology import ContractError
    if type(config) is not FrozenAdmissionTrainConfig:
        raise ContractError('admission compiler requires its exact frozen configuration')
    return compile_lineage_train_panels(config, packets)


def run_admission_train_panels(config, **kwargs):
    from research_loop.ontology import ContractError
    if type(config) is not FrozenAdmissionTrainConfig:
        raise ContractError('admission controller requires its exact frozen configuration')
    return run_lineage_train_panels(config, **kwargs)
