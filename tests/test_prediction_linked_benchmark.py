"""Actual prediction artifacts must reach a subsequent benchmark execution."""
import json
from pathlib import Path

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.prediction_panel_drivers import freeze_prediction_bundle
from research_loop.modular.train_controller import FrozenTrainControllerConfig
from test_modular_train_controller import config, snapshot_and_custody, FINAL, SCENARIO
from test_modular_linked_train_controller import ANALYSIS
from test_modular_prediction_panel_drivers import branch, proposal, q32_plan

DEDUP={'type':'object','properties':{'kept_proposal_ids':{'type':'array','items':{'type':'string'}}},
       'required':['kept_proposal_ids'],'additionalProperties':False}

def neutral_material(task):
    a,b,c=branch('h0','m0','positive'),branch('h1','m1','negative'),branch('h2','m2','null')
    q32={'joint':{'plans':[q32_plan(task,'Assess the public observation',[a,b,c],3,'0')]},
         'separate':{'plans':[q32_plan(task,'Assess the public observation',branches,1,str(i))
                             for i,branches in enumerate(([a,b],[a,c],[b,c]))]}}
    q53={}
    for variant, mechanisms, directions, titles in [
        ('same_mechanism',('m0','m0'),('positive','positive'),('Study A','Study B')),
        ('opposite_prediction',('m0','m0'),('positive','negative'),('Study A','Study B')),
        ('title',('m0','m1'),('positive','null'),('Study A','Study A'))]:
        branches=[branch('h'+str(i),mechanisms[i],directions[i]) for i in range(2)]
        q53[variant]={'proposals':[proposal(b,'origin-'+str(i),titles[i]) for i,b in enumerate(branches)],
                     'plan':{'question':'Assess the public observation','branches':branches,'budget_units':2}}
    return freeze_prediction_bundle(task,public_evidence={'schema':'prediction-public-evidence-v1',
        'task_digest':task.content_hash,'source_id':'source-0','observation_id':'observation-0',
        'public_summary':'Recorded public observation'},controller_truth={'schema':'prediction-controller-truth-v1',
        'marker':'CONTROLLER_ONLY_REFERENCE_MARKER'},q32=q32,q53=q53)

def frozen_config(tmp_path):
    snapshot,custody=snapshot_and_custody(tmp_path)
    base=config(custody,snapshot,tmp_path).data()
    packets=TrainPacketExporter(custody,snapshot,tmp_path/'materials').export(base['item_ids'])
    evidence={p.task.content_hash:neutral_material(p.task).data() for p in packets}
    grids=obligation_grids(('Q3.2','Q5.3'),baseline_digest=base['baseline_digest'],
        p0_control=FrozenRecord.from_dict(base['p0_control']))
    package=next(iter(base['packages_by_arm'].values()))
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,'schema':'train-panel-controller-v1',
        'engineering_scope':'train_only_panel_engineering','stage':'prediction-linked-fixture',
        'scope_ids':['Q3.2','Q5.3'],'evidence_by_task':evidence,
        'packages_by_arm':{a.content_hash:package for g in grids.values() for a in executable_arms(g).values()},
        'budget':{'maximum_mechanism_calls':4,'solver_calls':2,'solver_executions':1},
        'max_calls':96,'max_tokens':300,'schemas':{'plan_1':SCENARIO,'plan_2':SCENARIO,'plan_3':SCENARIO,
            'dedup':DEDUP,'final':FINAL,'analysis_program':ANALYSIS,'final_answer':FINAL},
        'scorer':ScorerConfig.create(benchmark='core_pair',evaluator_id='prediction-fixture',version='v1',
            rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest()).record.data(),
        'execution_mode':'linked_benchmark_solve'}))
    return snapshot,custody,frozen,evidence

def test_linked_config_freezes_all_twenty_prediction_cells(tmp_path):
    _,_,frozen,_=frozen_config(tmp_path)
    assert frozen.data()['max_calls']==8*6+12*4
