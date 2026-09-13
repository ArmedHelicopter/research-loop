"""Add the triple scope without discarding merged candidate provenance."""
import ast, subprocess
from pathlib import Path
root=Path('E:/_ryanDev/AI/research-loop-modular/integration')
name='evaluation/modular/scorer_process.py'
s=subprocess.check_output(['git','show','HEAD:'+name],cwd=root).decode()
def replace(old,new,count):
    global s
    assert s.count(old)==count,(old,s.count(old),count)
    s=s.replace(old,new)
replace('mechanism_improvement: bool = False','mechanism_improvement: bool = False, admission_prediction_exploration: bool = False',3)
replace('mechanism_scheduling, mechanism_improvement)','mechanism_scheduling, mechanism_improvement, admission_prediction_exploration)',1)
replace('    flags = (lineage,','    from research_loop.modular.admission_prediction_exploration_driver import DESIGNS as ADMISSION_PREDICTION_EXPLORATION_DESIGNS, registered_design as admission_prediction_exploration_design\n    flags = (lineage,',1)
replace('permitted = (MECHANISM_IMPROVEMENT_DESIGNS','permitted = (ADMISSION_PREDICTION_EXPLORATION_DESIGNS if admission_prediction_exploration else MECHANISM_IMPROVEMENT_DESIGNS',1)
replace('if (mechanism_scheduling and panel.design',"if (admission_prediction_exploration and panel.design != admission_prediction_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])\n            or mechanism_scheduling and panel.design",1)
replace('and not mechanism_improvement:', 'and not mechanism_improvement and not admission_prediction_exploration:',1)
replace('mechanism_improvement=mechanism_improvement)', 'mechanism_improvement=mechanism_improvement, admission_prediction_exploration=admission_prediction_exploration)',2)
replace("    mechanism_improvement_schema = 'mechanism-improvement-scorer-process-config-v1'","    mechanism_improvement_schema = 'mechanism-improvement-scorer-process-config-v1'\n    admission_prediction_exploration_schema = 'admission-prediction-exploration-scorer-process-config-v1'",1)
replace('mechanism_scheduling_schema, mechanism_improvement_schema}', 'mechanism_scheduling_schema, mechanism_improvement_schema, admission_prediction_exploration_schema}',2)
replace("mechanism_improvement=value['schema']==mechanism_improvement_schema)","mechanism_improvement=value['schema']==mechanism_improvement_schema, admission_prediction_exploration=value['schema']==admission_prediction_exploration_schema)",1)
replace('        self.mechanism_improvement = mechanism_improvement','        self.mechanism_improvement = mechanism_improvement\n        self.admission_prediction_exploration = admission_prediction_exploration',1)
ast.parse(s)
(root/name).write_text(s,encoding='utf-8')
print('Merged triple147 with all prior scorer family and provenance contracts.')
