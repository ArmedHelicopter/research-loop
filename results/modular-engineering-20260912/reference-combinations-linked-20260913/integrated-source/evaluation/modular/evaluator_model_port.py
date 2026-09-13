"""Dedicated no-tools provider port for frozen independent rubric evaluation.

The port receives the evaluator endpoint's private, frozen request contract.  It
never converts that request to a solver-facing ``public-model-request-v1``;
the supplied rubric prompt is the model-visible material and remains bound to
the endpoint request hash and evaluator ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy, ProcessRunner
from research_loop.ontology import ContractError, canonical


_REQUEST_SCHEMA = "frozen-independent-evaluator-call-v1"
_PURPOSE = "frozen-independent-evaluator-call-v1"


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class CodexEvaluatorModelPort(CodexModelPort):
    """Run only the endpoint's frozen, train-only evaluator request.

    The base port supplies the reviewed-context preflight, disabled tools,
    reservation-before-I/O ledger, usage accounting, timeout terminalization,
    and JSON-schema validation.  This subclass validates the evaluator's
    distinct private request and keeps its purpose explicit in every ledger
    reservation.
    """

    def __init__(self, executable: Path | str, work_root: Path, *, evaluator_id: str,
                 evaluator_version: str, rubric_mode: str = "primary_v1", model: str = "gpt-5.6-luna", effort: str = "low",
                 max_calls: int, max_tokens: int, timeout_seconds: int = 180,
                 process_runner: ProcessRunner | None = None,
                 context_probe_runner: ProcessRunner | None = None,
                 frozen_base_context: FrozenBaseContextPolicy | None = None,
                 allow_mock_context: bool = False, environment: Mapping[str, str] | None = None) -> None:
        self.evaluator_id = required_text(evaluator_id, "evaluator id")
        self.evaluator_version = required_text(evaluator_version, "evaluator version")
        if rubric_mode not in {"primary_v1", "lineage_v1"}:
            raise ContractError("unknown frozen evaluator rubric mode")
        from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint
        self.endpoint_type = FrozenLineageRubricEndpoint if rubric_mode == "lineage_v1" else FrozenBenchmarkRubricEndpoint
        self.rubric_digest = self.endpoint_type.rubric_digest()
        schemas = {self._slot(benchmark): self.endpoint_type._output_schema(benchmark)
                   for benchmark in ("discoverybench", "blade")}
        super().__init__(executable, work_root, model=model, effort=effort,
                         max_calls=max_calls, max_tokens=max_tokens,
                         schema_by_slot=schemas, timeout_seconds=timeout_seconds,
                         process_runner=process_runner, context_probe_runner=context_probe_runner,
                         frozen_base_context=frozen_base_context,
                         allow_mock_context=allow_mock_context, environment=environment,
                         _ledger_purpose=_PURPOSE, _ledger_request_contract=_REQUEST_SCHEMA,
                         _ledger_contract_binding={"evaluator_id": self.evaluator_id,
                                                   "evaluator_version": self.evaluator_version,
                                                   "rubric_digest": self.rubric_digest})

    @staticmethod
    def _slot(benchmark: str) -> str:
        return f"frozen-rubric.{benchmark}"

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        if not isinstance(request, FrozenRecord):
            raise ContractError("evaluator model port accepts immutable requests only")
        body = request.data()
        required = {"schema", "evaluator_id", "evaluator_version", "benchmark", "prompt", "output_schema",
                    "prompt_digest", "schema_digest", "reference_digest", "rubric_digest"}
        if set(body) != required or body.get("schema") != _REQUEST_SCHEMA:
            raise ContractError("unexpected frozen evaluator request")
        if (body["evaluator_id"] != self.evaluator_id or body["evaluator_version"] != self.evaluator_version
                or body["benchmark"] not in {"discoverybench", "blade"} or not isinstance(body["prompt"], str)
                or not body["prompt"]):
            raise ContractError("frozen evaluator identity or prompt is invalid")
        for field in ("prompt_digest", "schema_digest", "reference_digest", "rubric_digest"):
            _digest(body[field], field)
        benchmark = body["benchmark"]
        schema = self.endpoint_type._output_schema(benchmark)
        if body["output_schema"] != schema or body["schema_digest"] != _hash(schema):
            raise ContractError("frozen evaluator schema does not match the benchmark contract")
        if body["prompt_digest"] != _hash(body["prompt"]):
            raise ContractError("frozen evaluator prompt digest mismatch")
        if (body["rubric_digest"] != self.rubric_digest
                or self.endpoint_type.rubric_digest() != self.rubric_digest):
            raise ContractError("frozen evaluator rubric contract drift")
        self._verify_prompt_template(benchmark, body["prompt"])
        prompt = "Return only JSON conforming to the supplied schema.\n" + body["prompt"]
        return self._invoke_protected(request, slot=self._slot(benchmark), schema=schema, prompt=prompt)

    def _verify_prompt_template(self, benchmark: str, prompt: str) -> None:
        rubric = (FrozenBenchmarkRubricEndpoint._DISCOVERY_RUBRIC if benchmark == "discoverybench"
                  else FrozenBenchmarkRubricEndpoint._BLADE_RUBRIC)
        if prompt.count("\nTASK=") != 1 or prompt.count("\nREFERENCE=") != 1 or prompt.count("\nANONYMOUS_CANDIDATE=") != 1:
            raise ContractError("frozen evaluator prompt has invalid material delimiters")
        _, material = prompt.split("\nTASK=", 1)
        task, material = material.split("\nREFERENCE=", 1)
        reference, candidate = material.split("\nANONYMOUS_CANDIDATE=", 1)
        try:
            values = tuple(json.loads(value) for value in (task, reference, candidate))
            if any(canonical(value) != source for value, source in zip(values, (task, reference, candidate), strict=True)):
                raise ValueError("noncanonical evaluator material")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ContractError("frozen evaluator prompt has noncanonical material") from exc
        if prompt != self.endpoint_type._prompt(benchmark, rubric, *values):
            raise ContractError("frozen evaluator prompt does not exactly match the benchmark template")
