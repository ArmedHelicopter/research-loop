"""Integrate the explicit shared-candidate family while preserving prior scopes."""
import ast, subprocess
from pathlib import Path
root=Path('E:/_ryanDev/AI/research-loop-modular/integration')
name='evaluation/modular/scorer_process.py'
s=subprocess.check_output(['git','show','HEAD:'+name],cwd=root).decode()
def replace(old,new,count):
    global s
    assert s.count(old)==count,(old,s.count(old),count)
    s=s.replace(old,new)
replace('mechanism_scheduling: bool = False','mechanism_scheduling: bool = False, mechanism_improvement: bool = False',3)
replace('mechanism_exploration, mechanism_scheduling)','mechanism_exploration, mechanism_scheduling, mechanism_improvement)',1)
replace('    flags = (lineage,', '    from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel, DESIGNS as MECHANISM_IMPROVEMENT_DESIGNS\n    flags = (lineage,',1)
replace('permitted = (MECHANISM_SCHEDULING_DESIGNS','permitted = (MECHANISM_IMPROVEMENT_DESIGNS if mechanism_improvement else MECHANISM_SCHEDULING_DESIGNS',1)
replace('    if state_improvement and type(panel)',"    if mechanism_improvement and type(panel) is not MechanismImprovementPanel:\n        raise ContractError('exact versioned mechanism improvement panel required')\n    if state_improvement and type(panel)",1)
replace('and not mechanism_scheduling:', 'and not mechanism_scheduling and not mechanism_improvement:',1)
replace('if state_improvement else {})', 'if state_improvement or mechanism_improvement else {})',2)
replace('if state_improvement else set()', 'if state_improvement or mechanism_improvement else set()',1)
replace('        cls = StateImprovementPanel if state_improvement else CombinationPanel','        from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel\n        cls = MechanismImprovementPanel if mechanism_improvement else StateImprovementPanel if state_improvement else CombinationPanel',1)
replace('mechanism_scheduling=mechanism_scheduling)', 'mechanism_scheduling=mechanism_scheduling, mechanism_improvement=mechanism_improvement)',2)
replace("    mechanism_scheduling_schema = 'mechanism-scheduling-scorer-process-config-v1'","    mechanism_scheduling_schema = 'mechanism-scheduling-scorer-process-config-v1'\n    mechanism_improvement_schema = 'mechanism-improvement-scorer-process-config-v1'",1)
replace('mechanism_exploration_schema, mechanism_scheduling_schema}', 'mechanism_exploration_schema, mechanism_scheduling_schema, mechanism_improvement_schema}',2)
replace("mechanism_scheduling=value['schema']==mechanism_scheduling_schema)","mechanism_scheduling=value['schema']==mechanism_scheduling_schema, mechanism_improvement=value['schema']==mechanism_improvement_schema)",1)
replace('        self.mechanism_scheduling = mechanism_scheduling','        self.mechanism_scheduling = mechanism_scheduling\n        self.mechanism_improvement = mechanism_improvement',1)
ast.parse(s)
(root/name).write_text(s,encoding='utf-8')
print('Merged mechanism improvement with exact panel type and training provenance; all prior family flags retained.')
