"""Public execution outputs joined to immutable candidate and qualified state."""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import metaprogram_schemas, _projection
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.exploration_scheduler_combination import _joint


def slots(design):
    from research_loop.modular.execution_improvement_panel import DESIGNS
    if design not in DESIGNS: raise ValueError('unregistered execution improvement design')
    return ('analysis_program','final_answer')


def model_schemas(): return metaprogram_schemas()


def joint_context(cell,task,package,transition,phase,material):
    public=_joint(phase,material).data()['material']
    return FrozenRecord.from_dict({'schema':'public-combination-context-v1',
        'panel_cell':opaque_panel_cell_binding(cell),'public_task':task.data(),
        'candidate_context':_projection(package).data(),'state_projection':transition.data()['public'],
        'execution_observations':public['observations']})
