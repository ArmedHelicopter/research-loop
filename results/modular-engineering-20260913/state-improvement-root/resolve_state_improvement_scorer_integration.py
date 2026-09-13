"""Combine the explicit M7/M8 scopes with M9's versioned history panel."""
from pathlib import Path
import subprocess
root=Path('E:/_ryanDev/AI/research-loop-modular/integration')
path='evaluation/modular/scorer_process.py'
text=subprocess.check_output(['git','show','41171aa:'+path],cwd=root).decode('utf-8')
def swap(old,new,n):
    global text
    assert text.count(old)==n,(old,text.count(old),n)
    text=text.replace(old,new)
swap('state_retrieval: bool = False, state_improvement: bool = False',
     'state_retrieval: bool = False, state_exploration: bool = False, state_scheduling: bool = False, state_improvement: bool = False',3)
swap('    from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS as STATE_IMPROVEMENT_DESIGNS',
     '    from research_loop.modular.state_exploration_combination_driver import DESIGNS as STATE_EXPLORATION_DESIGNS, registered_design as state_exploration_design\n'
     '    from research_loop.modular.state_scheduling_combination_driver import DESIGNS as STATE_SCHEDULING_DESIGNS, registered_design as state_scheduling_design\n'
     '    from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS as STATE_IMPROVEMENT_DESIGNS',1)
swap('state_prediction, state_retrieval, state_improvement)',
     'state_prediction, state_retrieval, state_exploration, state_scheduling, state_improvement)',1)
swap('permitted = (STATE_IMPROVEMENT_DESIGNS',
     'permitted = (STATE_SCHEDULING_DESIGNS if state_scheduling else STATE_EXPLORATION_DESIGNS if state_exploration else STATE_IMPROVEMENT_DESIGNS',1)
swap('    if (retrieval_review and panel.design',
     "    if (state_scheduling and panel.design != state_scheduling_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])\n"
     "            or state_exploration and panel.design != state_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])\n"
     '            or retrieval_review and panel.design',1)
swap('and not state_retrieval and not state_improvement:',
     'and not state_retrieval and not state_exploration and not state_scheduling and not state_improvement:',1)
swap('state_retrieval=state_retrieval, state_improvement=state_improvement',
     'state_retrieval=state_retrieval, state_exploration=state_exploration, state_scheduling=state_scheduling, state_improvement=state_improvement',2)
swap("    state_improvement_schema = 'state-improvement-scorer-process-config-v1'",
     "    state_exploration_schema = 'state-exploration-scorer-process-config-v1'\n"
     "    state_scheduling_schema = 'state-scheduling-scorer-process-config-v1'\n"
     "    state_improvement_schema = 'state-improvement-scorer-process-config-v1'",1)
swap('state_retrieval_schema, state_improvement_schema}',
     'state_retrieval_schema, state_exploration_schema, state_scheduling_schema, state_improvement_schema}',2)
swap("state_retrieval=value['schema']==state_retrieval_schema, state_improvement=value['schema']==state_improvement_schema",
     "state_retrieval=value['schema']==state_retrieval_schema, state_exploration=value['schema']==state_exploration_schema, state_scheduling=value['schema']==state_scheduling_schema, state_improvement=value['schema']==state_improvement_schema",1)
swap('        self.state_improvement = state_improvement',
     '        self.state_exploration = state_exploration\n        self.state_scheduling = state_scheduling\n        self.state_improvement = state_improvement',1)
assert not any(mark in text for mark in ('<<<<<<<','=======','>>>>>>>'))
compile(text,str(root/path),'exec')
(root/path).write_text(text,encoding='utf-8',newline='\n')
print('Merged exact independent state exploration, scheduling and improvement scopes; syntax valid.')
