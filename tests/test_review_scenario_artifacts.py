from research_loop.modular.review_scenario_artifacts import verify_review_artifacts
from research_loop.modular.scenarios_review import run_review_scenario
from test_modular_review_scenarios import task,controls,responder
import pytest
from research_loop.ontology import ContractError

_VARIANTS = [("Q4.1", "single"), ("Q4.1", "independent_samples"), ("Q4.1", "roles"),
    ("Q4.2", "mechanism"), ("Q4.2", "alternative"), ("Q4.2", "measurement"), ("Q4.2", "experiment"), ("Q4.2", "generic"),
    ("Q4.3", "sealed_then_exchange"), ("Q4.3", "sequential"), ("Q4.4", "none_valid"), ("Q4.4", "defective"),
    ("Q4.5", "right_to_wrong"), ("Q4.5", "wrong_to_right"), ("Q4.5", "heterogeneous")]


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), _VARIANTS)
def test_every_registered_variant_has_a_strict_durable_round_trip(tmp_path, adapter, experiment_id, variant):
    public = task(adapter); root = tmp_path / "review"
    identities = None if variant != "heterogeneous" else {"reviewer_one": {"reviewer_id": "a", "model_id": "m1", "provider": "p1", "provenance": "fixture A"}, "reviewer_two": {"reviewer_id": "b", "model_id": "m2", "provider": "p2", "provenance": "fixture B"}}
    result = run_review_scenario(experiment_id, variant, task=public, frozen_controls=controls(public), review_callback=responder, artifact_root=root, reviewer_identities=identities)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id=experiment_id, variant=variant, result=result, reviewer_identities=identities).data()["status"] == "succeeded"


def test_strict_reader_rejects_coherent_content_attack_without_a_callback(tmp_path):
    public = task("blade"); root = tmp_path / "review"
    result = run_review_scenario("Q4.3", "sequential", task=public, frozen_controls=controls(public), review_callback=responder, artifact_root=root)
    attempt = root / "review-attempts.jsonl"
    text = attempt.read_text(encoding="utf-8").replace('"invocation":"revision"', '"invocation":"initial"')
    attempt.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(ContractError):
        verify_review_artifacts(root, task=public, controls=controls(public), experiment_id="Q4.3", variant="sequential", result=result)


def test_callback_failure_closes_a_partial_audit(tmp_path):
    public = task("blade"); root = tmp_path / "failed"
    def fail(_): raise RuntimeError("fixture callback failed")
    with pytest.raises(RuntimeError, match="fixture callback failed"):
        run_review_scenario("Q4.1", "single", task=public, frozen_controls=controls(public), review_callback=fail, artifact_root=root)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id="Q4.1", variant="single").data()["status"] == "failed"

def test_review_artifact_round_trip(tmp_path):
    public=task('blade'); root=tmp_path/'review'
    result=run_review_scenario('Q4.3','sequential',task=public,frozen_controls=controls(public),review_callback=responder,artifact_root=root)
    assert verify_review_artifacts(root, task=public, controls=controls(public), experiment_id='Q4.3', variant='sequential', result=result).data()['status']=='succeeded'
