"""Merge the new family into HEAD while retaining history panel construction."""
import ast,subprocess
from pathlib import Path
root=Path('E:/_ryanDev/AI/research-loop-modular/integration')
name='evaluation/modular/scorer_process.py'
s=subprocess.check_output(['git','show','HEAD:'+name],cwd=root).decode()
def replace(old,new,count):
 global s
 assert s.count(old)==count,(old,s.count(old),count)
 s=s.replace(old,new)
replace('state_improvement: bool = False','state_improvement: bool = False, mechanism_exploration: bool = False',3)
replace('state_scheduling, state_improvement)','state_scheduling, state_improvement, mechanism_exploration)',1)
replace('    from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS as STATE_IMPROVEMENT_DESIGNS',
 '    from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS as STATE_IMPROVEMENT_DESIGNS\n    from research_loop.modular.mechanism_exploration_combination_driver import DESIGNS as MECHANISM_EXPLORATION_DESIGNS, registered_design as mechanism_exploration_design',1)
replace('permitted = (STATE_SCHEDULING_DESIGNS','permitted = (MECHANISM_EXPLORATION_DESIGNS if mechanism_exploration else STATE_SCHEDULING_DESIGNS',1)
replace('if (state_scheduling and panel.design',"if (mechanism_exploration and panel.design != mechanism_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])\n            or state_scheduling and panel.design",1)
replace('and not state_improvement:', 'and not state_improvement and not mechanism_exploration:',1)
replace('state_improvement=state_improvement)', 'state_improvement=state_improvement, mechanism_exploration=mechanism_exploration)',2)
replace("    state_improvement_schema = 'state-improvement-scorer-process-config-v1'", "    state_improvement_schema = 'state-improvement-scorer-process-config-v1'\n    mechanism_exploration_schema = 'mechanism-exploration-scorer-process-config-v1'",1)
replace('state_scheduling_schema, state_improvement_schema}', 'state_scheduling_schema, state_improvement_schema, mechanism_exploration_schema}',2)
replace("state_improvement=value['schema']==state_improvement_schema)", "state_improvement=value['schema']==state_improvement_schema, mechanism_exploration=value['schema']==mechanism_exploration_schema)",1)
replace('        self.state_improvement = state_improvement','        self.state_improvement = state_improvement\n        self.mechanism_exploration = mechanism_exploration',1)
ast.parse(s)
(root/name).write_text(s,encoding='utf-8')
print('Merged exact family scope and preserved history provenance construction.')
