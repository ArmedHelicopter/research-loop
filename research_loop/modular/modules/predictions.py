"""M4: frozen, operational competing predictions.

This module records declared mechanism distinctions; it deliberately does not
infer scientific sameness from wording.  A caller must supply stable mechanism
and discriminator keys, then an independent evaluator can record outcomes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text, strict_bool
from research_loop.ontology import ContractError, canonical, digest


def _mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a mapping")
    return {required_text(k, f"{field} key"): required_text(v, f"{field} value") for k, v in value.items()}


def _same_identity(value: Any, identity: DataIdentity) -> None:
    if value != identity.data():
        raise ContractError("prediction event has a different data identity")


class _JsonlLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

    def append(self, event: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(dict(event)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def events(self) -> list[dict[str, Any]]:
        if self.path is None:
            return []
        result: list[dict[str, Any]] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or canonical(item) != line:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ContractError(f"invalid canonical prediction event at line {number}") from exc
            result.append(item)
        return result


@dataclass(frozen=True)
class OperationalPrediction:
    prediction_id: str
    discriminator_id: str
    observable: str
    direction: str | None
    value_range: tuple[float, float] | None
    failure_condition: str

    def data(self) -> dict[str, Any]:
        return {"prediction_id": self.prediction_id, "discriminator_id": self.discriminator_id,
                "observable": self.observable, "direction": self.direction,
                "value_range": list(self.value_range) if self.value_range is not None else None,
                "failure_condition": self.failure_condition}


@dataclass(frozen=True)
class HypothesisBranch:
    hypothesis_id: str
    mechanism_key: str
    mechanism: str
    intervention: str
    predictions: tuple[OperationalPrediction, ...]
    elimination_condition: str

    def data(self) -> dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "mechanism_key": self.mechanism_key,
                "mechanism": self.mechanism, "intervention": self.intervention,
                "predictions": [item.data() for item in self.predictions],
                "elimination_condition": self.elimination_condition}


@dataclass(frozen=True)
class PredictionPlan:
    plan_id: str
    identity: DataIdentity
    question: str
    branches: tuple[HypothesisBranch, ...]
    budget_units: int
    frozen: bool
    payload: FrozenRecord

    def data(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "identity": self.identity.data(), "question": self.question,
                "branches": [item.data() for item in self.branches], "budget_units": self.budget_units,
                "frozen": self.frozen, "payload": self.payload.data()}


@dataclass(frozen=True)
class PredictionUpdate:
    plan_id: str
    discriminator_id: str
    outcome_id: str
    per_hypothesis: tuple[tuple[str, str], ...]
    evaluator: str

    def data(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "discriminator_id": self.discriminator_id, "outcome_id": self.outcome_id,
                "per_hypothesis": dict(self.per_hypothesis), "evaluator": self.evaluator}


def _prediction(value: Any) -> OperationalPrediction:
    if not isinstance(value, Mapping) or set(value) != {"prediction_id", "discriminator_id", "observable", "direction", "value_range", "failure_condition"}:
        raise ContractError("prediction requires its complete operational fields")
    direction = value["direction"]
    numeric_range = value["value_range"]
    if (direction is None) == (numeric_range is None):
        raise ContractError("prediction requires exactly one of direction or value range")
    if direction is not None:
        direction = required_text(direction, "prediction direction")
    parsed_range: tuple[float, float] | None = None
    if numeric_range is not None:
        if not isinstance(numeric_range, Sequence) or isinstance(numeric_range, (str, bytes)) or len(numeric_range) != 2:
            raise ContractError("prediction value range must have two numeric endpoints")
        low, high = numeric_range
        if type(low) not in {int, float} or type(high) not in {int, float} or low > high:
            raise ContractError("prediction value range is invalid")
        parsed_range = (float(low), float(high))
    return OperationalPrediction(required_text(value["prediction_id"], "prediction id"),
                                 required_text(value["discriminator_id"], "discriminator id"),
                                 required_text(value["observable"], "prediction observable"), direction, parsed_range,
                                 required_text(value["failure_condition"], "prediction failure condition"))


class PredictionRegistry:
    """Append-only plans and evaluator-originated per-hypothesis updates."""

    def __init__(self, identity: DataIdentity, *, storage_path: Path | None = None) -> None:
        self.identity = identity
        self._plans: dict[str, PredictionPlan] = {}
        self._updates: dict[tuple[str, str], PredictionUpdate] = {}
        self._log = _JsonlLog(storage_path)
        for event in self._log.events():
            self._apply(event, persist=False)

    def freeze(self, question: str, branches: Sequence[Mapping[str, Any]], *, budget_units: int) -> PredictionPlan:
        if type(budget_units) is not int or budget_units <= 0:
            raise ContractError("prediction budget must be a positive integer")
        if not isinstance(branches, Sequence) or isinstance(branches, (str, bytes)) or len(branches) < 2:
            raise ContractError("a competing prediction plan requires at least two hypotheses")
        parsed: list[HypothesisBranch] = []
        for value in branches:
            if not isinstance(value, Mapping) or set(value) != {"hypothesis_id", "mechanism_key", "mechanism", "intervention", "predictions", "elimination_condition"}:
                raise ContractError("hypothesis requires complete branch fields")
            raw_predictions = value["predictions"]
            if not isinstance(raw_predictions, Sequence) or isinstance(raw_predictions, (str, bytes)) or not raw_predictions:
                raise ContractError("hypothesis requires one or more predictions")
            predictions = tuple(_prediction(item) for item in raw_predictions)
            if len({item.prediction_id for item in predictions}) != len(predictions):
                raise ContractError("duplicate prediction id within hypothesis")
            parsed.append(HypothesisBranch(required_text(value["hypothesis_id"], "hypothesis id"),
                                           required_text(value["mechanism_key"], "mechanism key"),
                                           required_text(value["mechanism"], "mechanism"),
                                           required_text(value["intervention"], "intervention"), predictions,
                                           required_text(value["elimination_condition"], "elimination condition")))
        if len({item.hypothesis_id for item in parsed}) != len(parsed) or len({item.mechanism_key for item in parsed}) != len(parsed):
            raise ContractError("hypothesis ids and declared mechanism keys must be distinct")
        self._validate_shared_discriminators(parsed)
        question = required_text(question, "research question")
        payload = FrozenRecord.from_dict({"question": question, "branches": [item.data() for item in parsed], "budget_units": budget_units})
        plan_id = digest({"identity": self.identity.data(), "payload": payload.data()})
        return self._apply({"event": "freeze", "identity": self.identity.data(), "plan_id": plan_id,
                            "question": question, "branches": [item.data() for item in parsed], "budget_units": budget_units}, persist=True)

    def record_outcome(self, plan_id: str, discriminator_id: str, outcome_id: str,
                       classifications: Mapping[str, str], evaluator_receipt: Mapping[str, Any]) -> PredictionUpdate:
        plan = self.plan(plan_id)
        discriminator_id = required_text(discriminator_id, "discriminator id")
        required_text(outcome_id, "outcome id")
        if set(evaluator_receipt) != {"trusted_evaluator", "verified"}:
            raise ContractError("evaluator receipt requires trusted evaluator and verified")
        evaluator = required_text(evaluator_receipt["trusted_evaluator"], "trusted evaluator")
        if not strict_bool(evaluator_receipt["verified"], "evaluator verified"):
            raise ContractError("outcome update requires a verified evaluator receipt")
        expected = {item.hypothesis_id for item in plan.branches}
        if set(classifications) != expected or any(value not in {"consistent", "failed", "unknown"} for value in classifications.values()):
            raise ContractError("shared discriminator needs one valid update per hypothesis")
        for branch in plan.branches:
            if discriminator_id not in {item.discriminator_id for item in branch.predictions}:
                raise ContractError("discriminator is not shared by every hypothesis")
        return self._apply({"event": "outcome", "identity": self.identity.data(), "plan_id": plan_id,
                            "discriminator_id": discriminator_id, "outcome_id": outcome_id,
                            "classifications": dict(classifications), "evaluator": evaluator}, persist=True)

    def plan(self, plan_id: str) -> PredictionPlan:
        try:
            return self._plans[required_text(plan_id, "plan id")]
        except KeyError as exc:
            raise ContractError("unknown prediction plan") from exc

    def updates(self, plan_id: str) -> tuple[PredictionUpdate, ...]:
        self.plan(plan_id)
        return tuple(sorted((item for (saved_plan, _), item in self._updates.items() if saved_plan == plan_id), key=lambda item: item.discriminator_id))

    def _validate_shared_discriminators(self, branches: Sequence[HypothesisBranch]) -> None:
        shared = set.intersection(*({item.discriminator_id for item in branch.predictions} for branch in branches))
        if not shared:
            raise ContractError("competing hypotheses require a shared discriminator")
        for discriminator in shared:
            signatures = []
            for branch in branches:
                prediction = next(item for item in branch.predictions if item.discriminator_id == discriminator)
                signatures.append((prediction.observable, prediction.direction, prediction.value_range, prediction.failure_condition))
            if len(set(signatures)) == 1:
                raise ContractError("shared discriminator has identical declared predictions")

    def _apply(self, event: Mapping[str, Any], *, persist: bool) -> PredictionPlan | PredictionUpdate:
        _same_identity(event.get("identity"), self.identity)
        if event.get("event") == "freeze":
            branches = event.get("branches")
            if not isinstance(branches, list):
                raise ContractError("persisted plan branches invalid")
            # Reuse public validation, then assert its deterministic id.
            parsed = []
            for item in branches:
                if not isinstance(item, Mapping):
                    raise ContractError("persisted hypothesis invalid")
                parsed.append(HypothesisBranch(required_text(item.get("hypothesis_id"), "hypothesis id"), required_text(item.get("mechanism_key"), "mechanism key"), required_text(item.get("mechanism"), "mechanism"), required_text(item.get("intervention"), "intervention"), tuple(_prediction(x) for x in item.get("predictions", [])), required_text(item.get("elimination_condition"), "elimination condition")))
            if len(parsed) < 2:
                raise ContractError("persisted plan needs competitors")
            self._validate_shared_discriminators(parsed)
            budget = event.get("budget_units")
            if type(budget) is not int or budget <= 0:
                raise ContractError("persisted prediction budget invalid")
            question = required_text(event.get("question"), "research question")
            payload = FrozenRecord.from_dict({"question": question, "branches": [item.data() for item in parsed], "budget_units": budget})
            expected = digest({"identity": self.identity.data(), "payload": payload.data()})
            if event.get("plan_id") != expected:
                raise ContractError("prediction plan id does not bind its frozen payload")
            plan = PredictionPlan(expected, self.identity, question, tuple(parsed), budget, True, payload)
            existing = self._plans.get(expected)
            if existing is not None and existing != plan:
                raise ContractError("prediction plan id collision")
            self._plans[expected] = plan
            if persist:
                self._log.append(event)
            return plan
        if event.get("event") != "outcome":
            raise ContractError("unknown prediction event")
        plan = self.plan(event.get("plan_id"))
        discriminator = required_text(event.get("discriminator_id"), "discriminator id")
        if any(discriminator not in {prediction.discriminator_id for prediction in branch.predictions}
               for branch in plan.branches):
            raise ContractError("persisted outcome discriminator is not shared")
        expected_ids = {item.hypothesis_id for item in plan.branches}
        classifications = event.get("classifications")
        if not isinstance(classifications, Mapping) or set(classifications) != expected_ids or any(item not in {"consistent", "failed", "unknown"} for item in classifications.values()):
            raise ContractError("persisted outcome classifications invalid")
        update = PredictionUpdate(plan.plan_id, discriminator, required_text(event.get("outcome_id"), "outcome id"), tuple(sorted(classifications.items())), required_text(event.get("evaluator"), "trusted evaluator"))
        key = (plan.plan_id, discriminator)
        existing = self._updates.get(key)
        if existing is not None and existing != update:
            raise ContractError("a frozen discriminator already has a different outcome")
        self._updates[key] = update
        if persist:
            self._log.append(event)
        return update


def freeze_shared_experiment(registry: PredictionRegistry, question: str,
                             branches: Sequence[Mapping[str, Any]], *, budget_units: int) -> PredictionPlan:
    """Freeze a competing plan only when every branch names one intervention."""
    if not branches or any(not isinstance(item, Mapping) for item in branches):
        raise ContractError("shared experiment requires branch mappings")
    interventions = {required_text(item.get("intervention"), "intervention") for item in branches}
    if len(interventions) != 1:
        raise ContractError("shared experiment requires one common intervention")
    return registry.freeze(question, branches, budget_units=budget_units)


def deduplicate_mechanism_predictions(proposals: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Deduplicate only equal declared mechanism-and-prediction signatures."""
    seen: set[tuple[str, str]] = set(); kept: list[str] = []; removed: list[str] = []
    for proposal in proposals:
        if not isinstance(proposal, Mapping) or set(proposal) != {"proposal_id", "mechanism_key", "prediction_signature", "title"}:
            raise ContractError("dedup proposal requires title, mechanism, and prediction signature")
        proposal_id = required_text(proposal["proposal_id"], "proposal id")
        signature = (required_text(proposal["mechanism_key"], "mechanism key"),
                     required_text(proposal["prediction_signature"], "prediction signature"))
        (removed if signature in seen else kept).append(proposal_id)
        seen.add(signature)
    return tuple(kept), tuple(removed)


def deduplicate_titles(proposals: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Title-only baseline retained solely for a declared dedup comparison."""
    seen: set[str] = set(); kept: list[str] = []; removed: list[str] = []
    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            raise ContractError("title dedup proposal must be a mapping")
        proposal_id = required_text(proposal.get("proposal_id"), "proposal id")
        title = required_text(proposal.get("title"), "proposal title")
        (removed if title in seen else kept).append(proposal_id)
        seen.add(title)
    return tuple(kept), tuple(removed)
