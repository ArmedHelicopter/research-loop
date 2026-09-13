"""Exact M3/M6/M9 public composition; no prediction or reviewer calls."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.metaprogram_training import metaprogram_schemas, _projection
from research_loop.modular.mechanism_improvement_modules import execute_retrieval, _verify_sources, public_retrieval
from research_loop.ontology import ContractError


def slots(triple):
    if triple != 'triple:M3+M6+M9': raise ContractError('exact required triple only')
    return ('analysis_program','final_answer')


def model_schemas():
    return metaprogram_schemas()


def target_joint(cell,task,package,transition,retrieval):
    slots(cell.coverage_id)
    if retrieval is None: raise ContractError('useful retrieval required at both M6 levels')
    return FrozenRecord.from_dict({'schema':'lineage-retrieval-improvement-public-joint-v1',
        'panel_cell':opaque_panel_cell_binding(cell),'public_task':task.data(),
        'candidate_context':_projection(package).data(),
        'state_projection':transition.data()['public'],'retrieval':retrieval})
