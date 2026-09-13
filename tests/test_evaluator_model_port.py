import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def _probe(argv, **kwargs):
    assert argv[1:3] == ["debug", "prompt-input"]
    return SimpleNamespace(returncode=0, stdout='[{"role":"developer","content":[{"type":"input_text","text":"base"}]}]', stderr="")


def _runner(argv, *, input, **kwargs):
    assert "evaluation material are unavailable" not in input
    assert "fixed adapted evaluator" in input
    assert "private-reference-sentinel" in input
    assert "--output-schema" in argv and "shell_tool" in argv
    Path(argv[argv.index("-o") + 1]).write_text(json.dumps({"context": 1, "variable_f1": 0.5, "relation": 1, "reason": "bounded"}), encoding="utf-8")
    return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":3,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}\n', stderr="")


class _Resolver:
    def __call__(self, handle, benchmark):
        assert handle == "synthetic-handle" and benchmark == "discoverybench"
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(), "identity_digest": "a" * 64,
            "task_context": {"question": "private-task-sentinel"},
            "references": [{"answer": "private-reference-sentinel"}]})


def _request():
    candidate = {"analysis": "candidate"}
    return FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": "p" * 64,
        "scorer_config_digest": "c" * 64, "benchmark": "discoverybench", "task_handle": "synthetic-handle",
        "identity_digest": "a" * 64, "candidate": candidate,
        "candidate_digest": FrozenRecord.from_dict(candidate).content_hash})


def _port(tmp_path):
    return CodexEvaluatorModelPort("codex", tmp_path / "evaluator", evaluator_id="frozen-rubric-v1",
        evaluator_version="v1", max_calls=2, max_tokens=20, process_runner=_runner,
        context_probe_runner=_probe, allow_mock_context=True)


def test_endpoint_to_evaluator_port_to_provider_receipt(tmp_path):
    port = _port(tmp_path)
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=_Resolver(), evaluator=port,
        evaluator_id="frozen-rubric-v1", evaluator_version="v1")
    response = endpoint(_request())
    assert response.data()["dimensions"] == {"context": 1.0, "variable_f1": 0.5, "relation": 1.0}
    ledger = json.loads((tmp_path / "evaluator" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["config"]["purpose"] == "frozen-independent-evaluator-call-v1"
    assert ledger["config"]["request_contract"] == "frozen-independent-evaluator-call-v1"
    assert ledger["calls"][0]["purpose"] == "frozen-independent-evaluator-call-v1"
    assert ledger["calls"][0]["request_contract"] == "frozen-independent-evaluator-call-v1"
    prompt = next((tmp_path / "evaluator" / "calls").glob("*/prompt.txt")).read_text(encoding="utf-8")
    assert "private-reference-sentinel" in prompt
    assert "public-model-request-v1" not in prompt


def test_evaluator_rejects_prompt_or_schema_contract_drift_before_provider(tmp_path):
    invoked = []
    def forbidden(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("provider must not run")
    port = CodexEvaluatorModelPort("codex", tmp_path / "evaluator", evaluator_id="frozen-rubric-v1",
        evaluator_version="v1", max_calls=1, max_tokens=20, process_runner=forbidden,
        context_probe_runner=_probe, allow_mock_context=True)
    schema = FrozenBenchmarkRubricEndpoint._output_schema("discoverybench")
    prompt = FrozenBenchmarkRubricEndpoint._prompt("discoverybench", FrozenBenchmarkRubricEndpoint._DISCOVERY_RUBRIC,
        {"task": "x"}, [{"reference": "y"}], {"candidate": "z"})
    body = {"schema": "frozen-independent-evaluator-call-v1", "evaluator_id": "frozen-rubric-v1", "evaluator_version": "v1",
        "benchmark": "discoverybench", "prompt": prompt + " altered", "output_schema": schema,
        "prompt_digest": hashlib.sha256(json.dumps(prompt + " altered", sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "schema_digest": hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "reference_digest": "b" * 64, "rubric_digest": FrozenBenchmarkRubricEndpoint.rubric_digest()}
    with pytest.raises(ContractError, match="noncanonical"):
        port(FrozenRecord.from_dict(body))
    assert not invoked



def test_public_port_prompt_and_historical_ledger_shape_are_unchanged(tmp_path):
    from research_loop.modular.model_port import CodexModelPort
    captured = []
    def runner(argv, *, input, **kwargs):
        captured.append(input)
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ok"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}', stderr="")
    request = FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": {"identity": {"domain": "train"}},
        "lock_digest": "lock", "objective": {}, "slot": "plan", "instruction": "public instruction",
        "context": {}, "module_context": {}, "execution_feedback": []})
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
    root = tmp_path / "public"
    port = CodexModelPort("codex", root, max_calls=2, max_tokens=10, schema_by_slot={"plan": schema},
        process_runner=runner, context_probe_runner=_probe, allow_mock_context=True)
    assert port(request).data() == {"answer": "ok"}
    assert captured == ["Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n" + request.encoded]
    config = json.loads((root / "ledger.json").read_text(encoding="utf-8"))["config"]
    assert "purpose" not in config and "request_contract" not in config
    CodexModelPort("codex", root, max_calls=2, max_tokens=10, schema_by_slot={"plan": schema},
        process_runner=runner, context_probe_runner=_probe, allow_mock_context=True)

