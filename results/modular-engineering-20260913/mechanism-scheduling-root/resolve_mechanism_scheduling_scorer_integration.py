"""Add the scheduling family without losing merged improvement provenance."""
import ast,subprocess
from pathlib import Path
root=Path('E:/_ryanDev/AI/research-loop-modular/integration')
name='evaluation/modular/scorer_process.py'
s=subprocess.check_output(['git','show','HEAD:'+name],cwd=root).decode()
def replace(old,new,count):
 global s
 assert s.count(old)==count,(old,s.count(old),count)
 s=s.replace(old,new)
replace('mechanism_exploration: bool = False','mechanism_exploration: bool = False, mechanism_scheduling: bool = False',3)
replace('state_improvement, mechanism_exploration)','state_improvement, mechanism_exploration, mechanism_scheduling)',1)
replace('    from research_loop.modular.mechanism_exploration_combination_driver import DESIGNS as MECHANISM_EXPLORATION_DESIGNS, registered_design as mechanism_exploration_design',
 '    from research_loop.modular.mechanism_exploration_combination_driver import DESIGNS as MECHANISM_EXPLORATION_DESIGNS, registered_design as mechanism_exploration_design\n    from research_loop.modular.mechanism_scheduling_combination_driver import DESIGNS as MECHANISM_SCHEDULING_DESIGNS, registered_design as mechanism_scheduling_design',1)
replace('permitted = (MECHANISM_EXPLORATION_DESIGNS','permitted = (MECHANISM_SCHEDULING_DESIGNS if mechanism_scheduling else MECHANISM_EXPLORATION_DESIGNS',1)
replace('if (mechanism_exploration and panel.design',"if (mechanism_scheduling and panel.design != mechanism_scheduling_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])\n            or mechanism_exploration and panel.design",1)
replace('and not mechanism_exploration:', 'and not mechanism_exploration and not mechanism_scheduling:',1)
replace('mechanism_exploration=mechanism_exploration)', 'mechanism_exploration=mechanism_exploration, mechanism_scheduling=mechanism_scheduling)',2)
replace("    mechanism_exploration_schema = 'mechanism-exploration-scorer-process-config-v1'", "    mechanism_exploration_schema = 'mechanism-exploration-scorer-process-config-v1'\n    mechanism_scheduling_schema = 'mechanism-scheduling-scorer-process-config-v1'",1)
replace('state_improvement_schema, mechanism_exploration_schema}', 'state_improvement_schema, mechanism_exploration_schema, mechanism_scheduling_schema}',2)
replace("mechanism_exploration=value['schema']==mechanism_exploration_schema)", "mechanism_exploration=value['schema']==mechanism_exploration_schema, mechanism_scheduling=value['schema']==mechanism_scheduling_schema)",1)
replace('        self.mechanism_exploration = mechanism_exploration','        self.mechanism_exploration = mechanism_exploration\n        self.mechanism_scheduling = mechanism_scheduling',1)
ast.parse(s)
(root/name).write_text(s,encoding='utf-8')
print('Merged mechanism scheduling and retained prior explicit family schemas.')
