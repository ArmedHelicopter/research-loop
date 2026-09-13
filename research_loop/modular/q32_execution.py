"""Explicit Q3.2 prospective programs, sealed before any derived observation.

This phase does not alter the historical planning-only registry driver. M4 is a
fixed background in this joint/separate comparison. No scientific admission is
issued by numeric range matching or successful execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from evaluation.modular.train_io import PublicTrainPacket, TrainPacketExporter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, validate_artifact
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.runtime import RunSession, AuditVerifier
from research_loop.ontology import ContractError, canonical, digest

SLOTS = ("program_1", "program_2", "program_3", "final")
BUDGET = {"model_calls": 4, "execution_opportunities": 3, "timeout_seconds": 20,
          "cpus": 1, "memory_gib": 1, "max_program_bytes": 12000}
PROGRAM_SCHEMA = {"type": "object", "properties": {"program": {"type": "string"}},
                  "required": ["program"], "additionalProperties": False}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_packet(packet: PublicTrainPacket) -> dict:
    receipt = packet.receipt.data()
    if (packet.task.identity.domain != "train" or receipt["identity"] != packet.task.identity.data()
            or receipt["packet_hash"] != packet.task.content_hash
            or json.loads(packet.packet_path.read_text(encoding="utf-8")) != {"task": packet.task.data(), "receipt": receipt}
            or _sha(packet.csv_path) != receipt["csv_sha256"]):
        raise ContractError("prospective input differs from frozen train export")
    return validate_artifact(packet.task.identity, "public_csv", packet.csv_path).record.data()


def compile_q32_execution(packets, material_by_task: dict, *, image: str) -> FrozenRecord:
    """Freeze the exact caller plans and four-cell conditional contrast pre-I/O."""
    from research_loop.modular.benchmarks.execution import ExecutionRequest
    spec = registry()["Q3.2"]
    if spec.variants != ("joint", "separate") or spec.modules != ("M4",):
        raise ContractError("Q3.2 registry contract changed")
    if len(packets) != 2 or {p.task.identity.benchmark for p in packets} != {"discoverybench", "blade"}:
        raise ContractError("one frozen public task per benchmark required")
    if set(material_by_task) != {p.task.content_hash for p in packets}:
        raise ContractError("exact task-bound caller materials required")
    tasks, cells = {}, []
    for packet in packets:
        input_artifact = checked_packet(packet)
        ExecutionRequest(packet.task.identity, image, packet.csv_path, {"public_csv": packet.csv_path}, BUDGET["timeout_seconds"])
        material = material_by_task[packet.task.content_hash]
        if set(material) != {"joint", "separate", "measurements"} or len(material["separate"]) != 3 or len(material["measurements"]) != 3:
            raise ContractError("one joint, three separate plans and three measurements required")
        register = PredictionRegistry(packet.task.identity)
        plans = [register.freeze(**p) for p in [material["joint"], *material["separate"]]]
        joint = plans[0]
        if joint.budget_units != 3 or len(joint.branches) != 3 or any(p.budget_units != 1 or len(p.branches) != 2 for p in plans[1:]):
            raise ContractError("fixed equal three-unit plan allocation required")
        common = {b.hypothesis_id: b.data() for b in joint.branches}
        pairs = []
        for plan in plans[1:]:
            if any(common.get(b.hypothesis_id) != b.data() for b in plan.branches):
                raise ContractError("paired hypotheses or predictions differ from common plan")
            pairs.append(frozenset(b.hypothesis_id for b in plan.branches))
        if len(set(pairs)) != 3:
            raise ContractError("three distinct pairwise plans required")
        measurements = material["measurements"]
        for i, m in enumerate(measurements):
            if set(m) != {"measurement_id", "discriminator_id", "observable", "instruction"} or any(not isinstance(v, str) or not v.strip() for v in m.values()):
                raise ContractError("closed operational measurement required")
            for plan in (joint, plans[i + 1]):
                for branch in plan.branches:
                    predictions = [p for p in branch.predictions if p.discriminator_id == m["discriminator_id"]]
                    if len(predictions) != 1 or predictions[0].observable != m["observable"] or predictions[0].value_range is None or not all(math.isfinite(v) for v in predictions[0].value_range):
                        raise ContractError("measurement must bind a finite numeric shared prediction")
        if any(len({m[k] for m in measurements}) != 3 for k in ("measurement_id", "discriminator_id", "observable")):
            raise ContractError("three distinct measurements required")
        tasks[packet.task.content_hash] = {"task": packet.task.data(), "receipt": packet.receipt.data(),
            "input_artifact": input_artifact, "plans": [p.data() for p in plans], "measurements": measurements}
        for variant in spec.variants:
            cells.append({"cell_id": digest({"task": packet.task.content_hash, "variant": variant}),
                          "task_digest": packet.task.content_hash, "variant": variant})
    return FrozenRecord.from_dict({"schema": "q32-prospective-execution-v1", "registry": spec.record.data(),
        "fixed_modules": ["M4"], "budget": BUDGET, "slots": list(SLOTS), "image": image,
        "tasks": tasks, "cells": cells, "scientific_validated": False,
        "independent_data_units_per_task": 1, "measurement_calibration": "unverified_caller_definition"})


def _public_plan(plan):
    return {"question": plan["question"], "branches": plan["branches"]}


def public_request(request: dict) -> dict:
    """Closed, non-recursive projection: retain scientific text and raw failures."""
    return {**request, "lock_digest": digest({"task": request["task"], "objective": request["objective"], "slots": list(SLOTS)}),
            "execution_feedback": [{**row, "id": f"measurement_{i + 1}"} for i, row in enumerate(request["execution_feedback"])]}


def observation(receipt: ExecutionReceipt, measurement: dict):
    if receipt.status != "succeeded":
        return None
    try:
        value = json.loads(receipt.record.data().get("stdout", ""))
        if (set(value) != {"observable", "value"} or value["observable"] != measurement["observable"]
                or type(value["value"]) not in {int, float} or not math.isfinite(value["value"])):
            raise ValueError
        return value
    except (ValueError, TypeError):
        return None


def compare(plan, measurement, value):
    result = {}
    for branch in plan["branches"]:
        prediction = next(p for p in branch["predictions"] if p["discriminator_id"] == measurement["discriminator_id"])
        low, high = prediction["value_range"]
        result[branch["hypothesis_id"]] = ("unknown" if value is None else
            "in_declared_range" if low <= value["value"] <= high else "outside_declared_range")
    return result


class Q32ExecutionStage:
    """One fresh owned session; no execution permitted before its complete seal."""
    def __init__(self, compiled: FrozenRecord, cell: dict, packet: PublicTrainPacket, *, sidecar: Path, verifier: AuditVerifier):
        body = compiled.data()
        if cell not in body["cells"] or packet.task.content_hash != cell["task_digest"]:
            raise ContractError("cell/task substitution")
        task = body["tasks"][cell["task_digest"]]
        if checked_packet(packet) != task["input_artifact"] or packet.receipt.data() != task["receipt"]:
            raise ContractError("input export substitution")
        self.compiled, self.cell, self.packet = compiled, FrozenRecord.from_dict(cell), packet
        self._task = FrozenRecord.from_dict(task)
        self._session = RunSession(packet.task, package_digest=compiled.content_hash,
            arm=default_compatibility("a" * 64).arm(("M4",)),
            objective=FrozenRecord.from_dict({"question": "Compare declared predictions with prospectively executed public measurements."}),
            slots=SLOTS, execution_limit=3, sidecar=sidecar, verifier=verifier, required_audit=("independent_scientific_validation",))
        self._registry = PredictionRegistry(packet.task.identity, storage_path=sidecar / "predictions.jsonl")
        self._plans = [task["plans"][0]] * 3 if cell["variant"] == "joint" else task["plans"][1:]
        for plan in self._plans:
            actual = self._registry.freeze(plan["question"], plan["branches"], budget_units=plan["budget_units"])
            if actual.data() != plan:
                raise ContractError("compiled plan does not match registry")
        self._session._record("q32_plans_frozen", {"compiled": compiled.data(), "compiled_digest": compiled.content_hash,
            "cell": cell, "plans": self._plans, "input_artifact": task["input_artifact"]})
        self._programs, self._rows, self._seal = [], [], None

    def _invoke(self, slot, model, context):
        if len(canonical(context).encode()) > 12000:
            raise ContractError("public measurement context exceeds frozen equal allocation")
        def projected(request):
            visible = FrozenRecord.from_dict(public_request(request.data()))
            self._session._record("q32_public_request", {"original_digest": request.content_hash, "request": visible.data()})
            return model(visible)
        return self._session.invoke(slot, projected, instruction="Perform the declared public measurement task. Return only the requested JSON.",
                                    module_context=FrozenRecord.from_dict(context))

    def produce(self, model):
        if self._programs or self._seal is not None or self._session._attempts:
            raise ContractError("production is single-use and precedes observation")
        for i, (plan, measurement) in enumerate(zip(self._plans, self._task.data()["measurements"])):
            response = self._invoke(SLOTS[i], model, {"plan": _public_plan(plan), "measurement": measurement,
                "input": {"mount": "/input/public_csv", "columns": "Use the public task dataset schema"},
                "output": {"observable": measurement["observable"], "value": "finite number"}})
            data = response.data()
            if set(data) != {"program"} or not isinstance(data["program"], str) or not data["program"].strip() or len(data["program"].encode()) > BUDGET["max_program_bytes"]:
                raise ContractError("producer returned an invalid bounded program")
            # Match RunSession's actual platform text write, including Windows EOL.
            code = data["program"].replace("\r\n", "\n").replace("\r", "\n")
            self._programs.append({"ordinal": i, "plan_id": plan["plan_id"], "plan_digest": digest(plan),
                "measurement": measurement, "program": code,
                "program_sha256": hashlib.sha256(code.replace("\n", os.linesep).encode()).hexdigest(),
                "response_digest": response.content_hash, "input_artifact": self._task.data()["input_artifact"]})
        self._seal = FrozenRecord.from_dict({"compiled_digest": self.compiled.content_hash, "jobs": self._programs})
        (self._session.sidecar / "execution-seal.json").write_text(self._seal.encoded, encoding="utf-8")
        self._session._record("q32_execution_seal", self._seal.data())
        return self._seal

    def execute_next(self, *, broker: DockerExecutionBroker, plan_id: str, program: str, csv_path: Path):
        i = len(self._rows)
        if self._seal is None or i >= 3:
            raise ContractError("all programs must be frozen before execution")
        if FrozenRecord((self._session.sidecar / "execution-seal.json").read_text(encoding="utf-8")) != self._seal:
            raise ContractError("durable execution seal was modified")
        job = self._seal.data()["jobs"][i]
        plan = self._registry.plan(plan_id).data()
        if (job["plan_id"] != plan_id or digest(plan) != job["plan_digest"] or program != job["program"]
                or csv_path.resolve() != self.packet.csv_path.resolve() or checked_packet(self.packet) != job["input_artifact"]):
            raise ContractError("frozen plan/program/input substitution before I/O")
        self._session._record("q32_execution_binding", {"seal_digest": self._seal.content_hash, "ordinal": i, "job": job})
        receipt = self._session.execute(program, broker=broker, image=self.compiled.data()["image"],
            inputs={"public_csv": csv_path}, timeout_seconds=BUDGET["timeout_seconds"])
        if (receipt.identity != self.packet.task.identity or receipt.artifact is None or receipt.artifact.sha256 != job["program_sha256"]
                or receipt.record.data().get("input_artifacts") != {"public_csv": job["input_artifact"]}):
            raise ContractError("actual execution receipt lost frozen subject binding")
        value = observation(receipt, job["measurement"])
        row = {"ordinal": i, "plan_id": plan_id, "measurement": job["measurement"], "status": receipt.status,
            "execution_digest": receipt.content_hash, "receipt": receipt.data(), "observation": value,
            "range_membership": compare(plan, job["measurement"], value)}
        self._rows.append(row)
        self._session._record("q32_observation", row)
        return FrozenRecord.from_dict(row)

    def run(self, model, broker):
        failure = None
        try:
            seal = self.produce(model)
            for job in seal.data()["jobs"]:
                self.execute_next(broker=broker, plan_id=job["plan_id"], program=job["program"], csv_path=self.packet.csv_path)
            plans = {p["plan_id"]: p for p in self._plans}
            handles = {pid: f"plan_{i + 1}" for i, pid in enumerate(plans)}
            public_rows = [{"plan": handles[r["plan_id"]], "measurement": r["measurement"], "status": r["status"],
                            "observation": r["observation"], "range_membership": r["range_membership"]} for r in self._rows]
            self._session._record("q32_comparison_ready", {"rows": self._rows, "seal_digest": self._seal.content_hash})
            candidate = self._invoke("final", model, {"plans": {handles[k]: _public_plan(p) for k, p in plans.items()},
                "measurements": public_rows, "required_objective_digest": self._session.objective.content_hash})
        except Exception as exc:
            failure = type(exc).__name__
            self._session._record("q32_phase_failure", {"error_type": failure, "completed_observations": len(self._rows)})
            candidate = FrozenRecord.from_dict({"objective_digest": self._session.objective.content_hash, "outcome": "unknown",
                "evidence_ids": [], "conclusion": "Incomplete prospective execution; retain all allocated measurements.", "programme_complete": False})
        rows = list(self._rows)
        for i in range(len(rows), 3):
            measurement = self._task.data()["measurements"][i]
            rows.append({"ordinal": i, "plan_id": self._plans[i]["plan_id"], "measurement": measurement,
                "status": "blocked", "execution_digest": None, "receipt": None, "observation": None,
                "range_membership": compare(self._plans[i], measurement, None)})
        decision = self._session.finish(candidate)
        result = FrozenRecord.from_dict({"cell": self.cell.data(), "rows": rows, "decision": decision.data(),
            "failure": failure, "allocated": BUDGET, "model_attempts": self._session._next_call,
            "execution_attempts": self._session._attempts, "unattempted_executions": 3 - self._session._attempts,
            "scientific_validated": False, "programme_complete": False, "independent_data_units": 1,
            "measurement_calibration": "unverified_caller_definition"})
        self._session._record("q32_phase_result", result.data())
        (self._session.sidecar / "result.json").write_text(result.encoded, encoding="utf-8")
        return result


def run_q32_execution_panel(*, custody, snapshot_root: Path, export_root: Path, run_root: Path,
                            item_ids, material_by_task, image, model, verifier):
    """Explicit exporter -> compiler -> owned sessions -> real broker entry."""
    if run_root.exists() and any(run_root.iterdir()):
        raise ContractError("execution panel output already used")
    packets = TrainPacketExporter(custody, snapshot_root, export_root).export(item_ids)
    compiled = compile_q32_execution(packets, material_by_task, image=image)
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "compiled.json").write_text(compiled.encoded, encoding="utf-8")
    packet_by_task = {p.task.content_hash: p for p in packets}
    broker = DockerExecutionBroker([export_root, run_root])
    results = []
    for i, cell in enumerate(compiled.data()["cells"]):
        stage = Q32ExecutionStage(compiled, cell, packet_by_task[cell["task_digest"]], sidecar=run_root / str(i), verifier=verifier)
        results.append(stage.run(model, broker))
    result = FrozenRecord.from_dict({"compiled_digest": compiled.content_hash, "cell_count": len(results),
        "measurement_denominator": 3 * len(results), "results": [r.data() for r in results],
        "scientific_validated": False, "programme_complete": False})
    (run_root / "panel-result.json").write_text(result.encoded, encoding="utf-8")
    return result
