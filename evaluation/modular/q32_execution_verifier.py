"""Read-only original-event verifier for the explicit prospective Q3.2 phase.

Receipt origin and declared-range membership are engineering checks only.
This verifier neither supplies scientific authority nor imports the driver.
"""
import hashlib
import json
import math
import os
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.benchmarks.execution import ExecutionReceipt
from research_loop.modular.runtime import verify_trace
from research_loop.ontology import ContractError, digest


def verify_q32_execution(path: Path, compiled: FrozenRecord) -> FrozenRecord:
    verify_trace(path)
    events = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    plans_event = [e for e in events if e["stage"] == "q32_plans_frozen"]
    if len(plans_event) != 1:
        raise ContractError("unique pre-production plans required")
    p = plans_event[0]
    frozen = p["data"]
    if frozen["compiled"] != compiled.data() or frozen["compiled_digest"] != compiled.content_hash or frozen["cell"] not in compiled.data()["cells"]:
        raise ContractError("external frozen compilation binding lost")
    task = compiled.data()["tasks"][frozen["cell"]["task_digest"]]
    expected_plans = [task["plans"][0]] * 3 if frozen["cell"]["variant"] == "joint" else task["plans"][1:]
    if frozen["plans"] != expected_plans or frozen["input_artifact"] != task["input_artifact"]:
        raise ContractError("frozen plan or input replacement")
    requests = [e for e in events if e["stage"] == "model_request"]
    public = [e for e in events if e["stage"] == "q32_public_request"]
    responses = [e for e in events if e["stage"] == "model_response"]
    slots = ("program_1", "program_2", "program_3", "final")
    if [e["data"]["request"]["slot"] for e in requests] != list(slots[:len(requests)]) or len(requests) > 4 or len(public) != len(requests):
        raise ContractError("producer schedule or public request denominator mismatch")
    for i, (req, visible) in enumerate(zip(requests, public)):
        raw = req["data"]["request"]
        expected = {**raw, "lock_digest": digest({"task": raw["task"], "objective": raw["objective"], "slots": list(slots)}),
                    "execution_feedback": [{**row, "id": f"measurement_{j + 1}"} for j, row in enumerate(raw["execution_feedback"])]}
        if not p["sequence"] < req["sequence"] < visible["sequence"] or visible["data"] != {"original_digest": digest(raw), "request": expected}:
            raise ContractError("public production request binding or chronology mismatch")
        matching = [r for r in responses if r["data"]["request_digest"] == digest(raw)]
        if len(matching) > 1 or (matching and matching[0]["sequence"] <= visible["sequence"]):
            raise ContractError("response is not after its actual public request")
        if i < 3:
            plan = expected_plans[i]
            expected_context = {"plan": {"question": plan["question"], "branches": plan["branches"]},
                "measurement": task["measurements"][i], "input": {"mount": "/input/public_csv", "columns": "Use the public task dataset schema"},
                "output": {"observable": task["measurements"][i]["observable"], "value": "finite number"}}
            if raw["module_context"] != expected_context or raw["execution_feedback"]:
                raise ContractError("producer received replaced material or early observation")
    seals = [e for e in events if e["stage"] == "q32_execution_seal"]
    bindings = [e for e in events if e["stage"] == "q32_execution_binding"]
    executions = [e for e in events if e["stage"] == "execution_request"]
    results = [e for e in events if e["stage"] == "execution_result"]
    observations = [e for e in events if e["stage"] == "q32_observation"]
    if len(seals) > 1 or (not seals and (bindings or executions or observations)):
        raise ContractError("execution before complete program seal")
    if seals:
        seal = seals[0]
        if seal["data"]["compiled_digest"] != compiled.content_hash or len(seal["data"]["jobs"]) != 3:
            raise ContractError("seal compilation or opportunity denominator differs")
        for i, job in enumerate(seal["data"]["jobs"]):
            matching = [r for r in responses if r["data"]["request_digest"] == requests[i]["data"]["request_digest"]]
            if len(matching) != 1 or matching[0]["sequence"] >= seal["sequence"]:
                raise ContractError("all corresponding producer responses must precede the seal")
            response = matching[0]["data"]["response"]
            program = response["program"].replace("\r\n", "\n").replace("\r", "\n")
            expected = {"ordinal": i, "plan_id": expected_plans[i]["plan_id"], "plan_digest": digest(expected_plans[i]),
                "measurement": task["measurements"][i], "program": program,
                "program_sha256": hashlib.sha256(program.replace("\n", os.linesep).encode()).hexdigest(),
                "response_digest": digest(response), "input_artifact": task["input_artifact"]}
            if job != expected:
                raise ContractError("sealed program/plan/input/response binding differs")
        if len(bindings) != len(executions) or len(results) > len(executions) or len(observations) > len(results):
            raise ContractError("execution/failure opportunity denominator mismatch")
        for i, (binding, execution) in enumerate(zip(bindings, executions)):
            job = seal["data"]["jobs"][i]
            prior = seal["sequence"] if i == 0 else results[i - 1]["sequence"]
            if (not prior < binding["sequence"] < execution["sequence"]
                    or binding["data"] != {"ordinal": i, "seal_digest": digest(seal["data"]), "job": job}
                    or execution["data"] != {"attempt": i + 1, "program_sha256": job["program_sha256"]}):
                raise ContractError("actual execution request chronology or seal binding differs")
            if i >= len(results):
                continue
            result = results[i]
            receipt = ExecutionReceipt.parse(result["data"]["receipt"])
            if (result["sequence"] <= execution["sequence"] or receipt.content_hash != result["data"]["execution_digest"]
                    or receipt.identity.data() != task["task"]["identity"] or receipt.artifact.sha256 != job["program_sha256"]
                    or receipt.record.data().get("input_artifacts") != {"public_csv": job["input_artifact"]}):
                raise ContractError("actual receipt does not bind program/input/plan")
            if i >= len(observations):
                continue
            obs = observations[i]
            value = None
            if receipt.status == "succeeded":
                try:
                    candidate = json.loads(receipt.record.data().get("stdout", ""))
                    if set(candidate) == {"observable", "value"} and candidate["observable"] == job["measurement"]["observable"] and type(candidate["value"]) in {int, float} and math.isfinite(candidate["value"]):
                        value = candidate
                except (ValueError, TypeError):
                    pass
            ranges = {}
            for b in expected_plans[i]["branches"]:
                pred = next(p for p in b["predictions"] if p["discriminator_id"] == job["measurement"]["discriminator_id"])
                ranges[b["hypothesis_id"]] = "unknown" if value is None else "in_declared_range" if pred["value_range"][0] <= value["value"] <= pred["value_range"][1] else "outside_declared_range"
            expected_obs = {"ordinal": i, "plan_id": job["plan_id"], "measurement": job["measurement"], "status": receipt.status,
                "execution_digest": receipt.content_hash, "receipt": receipt.data(), "observation": value, "range_membership": ranges}
            if obs["sequence"] <= result["sequence"] or obs["data"] != expected_obs:
                raise ContractError("observation predates execution or differs from actual stdout")
    ready = [e for e in events if e["stage"] == "q32_comparison_ready"]
    if len(requests) == 4:
        if len(ready) != 1 or len(observations) != 3 or not observations[-1]["sequence"] < ready[0]["sequence"] < requests[-1]["sequence"]:
            raise ContractError("comparison must follow all actual observations")
        if ready[0]["data"] != {"rows": [e["data"] for e in observations], "seal_digest": digest(seals[0]["data"])}:
            raise ContractError("comparison replaced observations")
        plan_map = {p["plan_id"]: p for p in expected_plans}
        handles = {pid: f"plan_{i + 1}" for i, pid in enumerate(plan_map)}
        expected_context = {"plans": {handles[k]: {"question": p["question"], "branches": p["branches"]} for k, p in plan_map.items()},
            "measurements": [{"plan": handles[e["data"]["plan_id"]], **{k: e["data"][k] for k in ("measurement", "status", "observation", "range_membership")}} for e in observations],
            "required_objective_digest": digest(requests[-1]["data"]["request"]["objective"])}
        if requests[-1]["data"]["request"]["module_context"] != expected_context:
            raise ContractError("actual final model request lost observation/plan binding")
    finals = [e["data"] for e in events if e["stage"] == "q32_phase_result"]
    if len(finals) != 1 or len(finals[0]["rows"]) != 3 or finals[0]["rows"][:len(observations)] != [e["data"] for e in observations]:
        raise ContractError("final failed/succeeded measurement denominator changed")
    final = finals[0]
    if final["model_attempts"] != len(requests) or final["execution_attempts"] != len(executions) or final["scientific_validated"] is not False:
        raise ContractError("final cost or scientific claim differs")
    for row in final["rows"][len(observations):]:
        if row["status"] != "blocked" or row["observation"] is not None or any(v != "unknown" for v in row["range_membership"].values()):
            raise ContractError("unexecuted measurement promoted or omitted")
    return FrozenRecord.from_dict({"verified": True, "cells": 1, "measurements": 3, "model_attempts": len(requests),
        "execution_attempts": len(executions), "scientific_validated": False})
