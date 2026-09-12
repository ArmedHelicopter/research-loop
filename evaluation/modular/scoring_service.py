"""Independent adapted-metric scoring boundary for the two core benchmarks.

The solver submits an immutable artifact and a cell/runtime binding.  A service
owned task handle selects the benchmark evaluator; reference material never
appears in this request, response, or receipt.  The small HMAC authority is a
testable transport stand-in: deployed keys and reference resolvers must live in
the independently operated scoring service.

This authenticates a score calculation and its provenance.  It does not
calibrate the evaluator, measure a module effect, or establish scientific
validity.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from research_loop.modular.benchmarks.scoring import blade_adapted_score, discovery_adapted_score
from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.modular.panel_receipts import PanelCell, RuntimeReceipt, ScientificScorerReceipt
from research_loop.ontology import ContractError, canonical


_DIMENSIONS = {
    "discoverybench": ("context", "variable_f1", "relation"),
    "blade": ("cvars", "transform", "model"),
}
_METRICS = {"discoverybench": "discovery_adapted_score", "blade": "blade_adapted_score"}


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(f"{field} must be a sha256 digest")
    return value


def _unit(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ContractError(f"{field} must be a finite unit score")
    return float(value)


@dataclass(frozen=True)
class ScorerConfig:
    """Frozen evaluator contract; its digest must be the panel scorer digest."""
    record: FrozenRecord

    @classmethod
    def create(cls, *, benchmark: str, evaluator_id: str, rubric_digest: str, version: str) -> "ScorerConfig":
        if benchmark not in {*_DIMENSIONS, "core_pair"}:
            raise ContractError("unsupported adapted benchmark")
        benchmarks = tuple(_DIMENSIONS) if benchmark == "core_pair" else (benchmark,)
        return cls(FrozenRecord.from_dict({"schema": "adapted-metric-scorer-config-v1", "benchmark": benchmark,
            "evaluator_id": required_text(evaluator_id, "evaluator id"), "rubric_digest": _digest(rubric_digest, "rubric digest"),
            "version": required_text(version, "scorer version"), "benchmarks": list(benchmarks),
            "reference_access": "service_task_handle_only"}))

    @property
    def digest(self) -> str:
        return self.record.content_hash

    @property
    def benchmark(self) -> str:
        return self.record.data()["benchmark"]

    @property
    def benchmarks(self) -> tuple[str, ...]:
        return tuple(self.record.data()["benchmarks"])


class ReferenceEvaluator(Protocol):
    """Service-only evaluator.  Its closure may read a protected task reference."""
    def __call__(self, task_handle: str, submission: FrozenRecord) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ScoringAuthority:
    authority_id: str
    key: bytes

    def __post_init__(self) -> None:
        required_text(self.authority_id, "scoring authority id")
        if not isinstance(self.key, bytes) or len(self.key) < 32:
            raise ContractError("scoring authority key must have at least 32 bytes")

    def issue(self, body: Mapping[str, Any]) -> FrozenRecord:
        material = dict(body)
        material["authority"] = self.authority_id
        return FrozenRecord.from_dict({"body": material,
            "mac": hmac.new(self.key, canonical(material).encode(), hashlib.sha256).hexdigest()})


class IndependentScoringService:
    """Controller/service API.  It is deliberately not a solver-side port."""
    def __init__(self, *, config: ScorerConfig, authority: ScoringAuthority,
                 evaluator: ReferenceEvaluator, allowed_task_handles: Mapping[str, str]):
        if not isinstance(config, ScorerConfig) or not isinstance(authority, ScoringAuthority) or not callable(evaluator):
            raise ContractError("service needs typed config, authority, and evaluator")
        if not isinstance(allowed_task_handles, Mapping) or not allowed_task_handles:
            raise ContractError("service needs a controller-owned task handle map")
        handles = dict(allowed_task_handles)
        for identity_digest, handle in handles.items():
            _digest(identity_digest, "identity digest")
            required_text(handle, "task handle")
        self.config, self.authority, self._evaluator, self._handles = config, authority, evaluator, handles

    def score(self, *, panel_digest: str, cell: PanelCell, runtime: RuntimeReceipt,
              submission: FrozenRecord) -> ScientificScorerReceipt:
        """Compute and sign one receipt from a real evaluator response.

        ``submission`` is immutable candidate material supplied only to this
        service.  It never carries a reference, expected dimensions, or score.
        """
        _digest(panel_digest, "panel digest")
        if not isinstance(submission, FrozenRecord) or runtime.status != "succeeded" or runtime.output_digest is None:
            raise ContractError("only a successful bound runtime and immutable submission may be scored")
        if cell.identity.benchmark not in self.config.benchmarks or cell.scorer_digest != self.config.digest:
            raise ContractError("cell benchmark or scorer configuration is not this service")
        identity_digest = FrozenRecord.from_dict(cell.identity.data()).content_hash
        task_handle = self._handles.get(identity_digest)
        if task_handle is None:
            raise ContractError("task is not delegated to this scoring service")
        benchmark = cell.identity.benchmark
        dimensions = self._dimensions(benchmark, self._evaluator(task_handle, submission))
        aggregate = (discovery_adapted_score if benchmark == "discoverybench" else blade_adapted_score)(
            submission.encoded, dimensions)
        metric = {"name": _METRICS[benchmark], "dimensions": dimensions,
                  "value": aggregate["adapted_score"], "direction": "higher_better",
                  "value_range": [0.0, 1.0], "scale": "unit"}
        body = {"schema": "independent-scored-cell-v2", "panel_digest": panel_digest,
                "cell_key": list(cell.key), "runtime_trace_digest": runtime.trace_digest,
                "runtime_output_digest": runtime.output_digest, "scorer_digest": self.config.digest,
                "scorer_config_digest": self.config.digest, "benchmark": benchmark,
                "task_handle_digest": hashlib.sha256(task_handle.encode()).hexdigest(),
                "submission_digest": submission.content_hash, "metric": metric,
                "status": "scored", "scientific_validity": "not_measured", "calibration": "not_measured"}
        return ScientificScorerReceipt(cell.key, self.authority.issue(body))

    def _dimensions(self, benchmark: str, value: Mapping[str, object]) -> dict[str, float]:
        names = _DIMENSIONS[benchmark]
        if not isinstance(value, Mapping) or set(value) != set(names):
            raise ContractError("evaluator response must contain exactly the configured dimensions")
        return {name: _unit(value[name], name) for name in names}


class AdaptedMetricReceiptVerifier:
    """Verifier for ``IndependentScoringService`` receipts, suitable for a panel."""
    def __init__(self, *, authority_keys: Mapping[str, bytes], config: ScorerConfig):
        if not isinstance(authority_keys, Mapping) or not authority_keys:
            raise ContractError("scorer verifier needs independent authority keys")
        self._keys, self._config = dict(authority_keys), config

    def __call__(self, receipt: ScientificScorerReceipt, cell: PanelCell, panel: object) -> None:
        envelope = receipt.receipt.data()
        if set(envelope) != {"body", "mac"} or not isinstance(envelope["body"], dict) or not isinstance(envelope["mac"], str):
            raise ContractError("malformed adapted scorer receipt")
        body = envelope["body"]
        authority = body.get("authority")
        if authority not in self._keys or not isinstance(self._keys[authority], bytes):
            raise ContractError("untrusted adapted scoring authority")
        expected = hmac.new(self._keys[authority], canonical(body).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(envelope["mac"], expected):
            raise ContractError("adapted scorer receipt signature mismatch")
        required = {"schema", "authority", "panel_digest", "cell_key", "runtime_trace_digest", "runtime_output_digest",
                    "scorer_digest", "scorer_config_digest", "benchmark", "task_handle_digest", "submission_digest",
                    "metric", "status", "scientific_validity", "calibration"}
        if set(body) != required or body["schema"] != "independent-scored-cell-v2" or body["status"] != "scored":
            raise ContractError("invalid adapted scorer receipt contract")
        if (body["panel_digest"] != panel.digest or body["cell_key"] != list(cell.key)
                or body["scorer_digest"] != cell.scorer_digest or body["scorer_config_digest"] != self._config.digest
                or body["benchmark"] != cell.identity.benchmark or body["benchmark"] not in self._config.benchmarks):
            raise ContractError("adapted scorer receipt has panel, cell, or configuration drift")
        for field in ("panel_digest", "runtime_trace_digest", "runtime_output_digest", "scorer_digest", "scorer_config_digest", "task_handle_digest", "submission_digest"):
            _digest(body[field], field)
        metric = body["metric"]
        if not isinstance(metric, Mapping) or set(metric) != {"name", "dimensions", "value", "direction", "value_range", "scale"}:
            raise ContractError("adapted scorer metric is malformed")
        benchmark = body["benchmark"]
        if metric["name"] != _METRICS[benchmark] or metric["direction"] != "higher_better" or metric["value_range"] != [0.0, 1.0] or metric["scale"] != "unit":
            raise ContractError("adapted scorer metric contract drift")
        dimensions = {name: _unit(value, name) for name, value in metric["dimensions"].items()} if isinstance(metric["dimensions"], Mapping) else None
        if dimensions is None or set(dimensions) != set(_DIMENSIONS[benchmark]):
            raise ContractError("adapted scorer dimensions drift")
        actual = (discovery_adapted_score if benchmark == "discoverybench" else blade_adapted_score)("bound", dimensions)["adapted_score"]
        if type(metric["value"]) not in (int, float) or not math.isclose(float(metric["value"]), actual, rel_tol=0.0, abs_tol=1e-12):
            raise ContractError("adapted scorer aggregate does not match dimensions")
