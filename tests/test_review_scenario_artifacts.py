from research_loop.modular.review_scenario_artifacts import verify_review_artifacts
from research_loop.modular.scenarios_review import run_review_scenario
from test_modular_review_scenarios import task,controls,responder

def test_review_artifact_round_trip(tmp_path):
    public=task('blade'); root=tmp_path/'review'
    result=run_review_scenario('Q4.3','sequential',task=public,frozen_controls=controls(public),review_callback=responder,artifact_root=root)
    assert verify_review_artifacts(root,task=public,controls=controls(public),result=result).data()['status']=='succeeded'
