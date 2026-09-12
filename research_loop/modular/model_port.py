"""Bounded, no-tools Codex CLI model port.

The port is deliberately only a ``RunSession.invoke`` callable.  It does not
read datasets, produce evaluation metadata, or interpret a model response as a
score.  Its append-only reservation ledger makes an interrupted invocation
terminal for this port instance rather than something that can be replayed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical, digest


ProcessRunner = Callable[..., Any]
_PRIVATE_WORDS = ("gold", "label", "scorer", "reference", "validation")


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_schema(schema: Any, value: Any) -> None:
    """Small closed JSON Schema subset used for model response slots."""
    if not isinstance(schema, Mapping) or set(schema) - {"type", "properties", "required", "additionalProperties", "items", "enum"}:
        raise ContractError("unsupported output schema")
    kind = schema.get("type")
    if kind not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
        raise ContractError("output schema requires a supported type")
    if kind == "object":
        properties, required = schema.get("properties", {}), schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list) or any(not isinstance(k, str) for k in properties) or any(not isinstance(k, str) for k in required):
            raise ContractError("invalid object output schema")
        if schema.get("additionalProperties", False) is not False or not isinstance(value, dict) or not set(required) <= set(value) or not set(value) <= set(properties):
            raise ContractError("model output violates object schema")
        for key, child in properties.items():
            if key in value:
                _validate_schema(child, value[key])
    elif kind == "array":
        if not isinstance(value, list) or "items" not in schema:
            raise ContractError("model output violates array schema")
        for child in value:
            _validate_schema(schema["items"], child)
    elif kind == "string" and not isinstance(value, str):
        raise ContractError("model output violates string schema")
    elif kind == "number" and (type(value) not in {int, float} or isinstance(value, bool)):
        raise ContractError("model output violates number schema")
    elif kind == "integer" and type(value) is not int:
        raise ContractError("model output violates integer schema")
    elif kind == "boolean" and type(value) is not bool:
        raise ContractError("model output violates boolean schema")
    elif kind == "null" and value is not None:
        raise ContractError("model output violates null schema")
    if "enum" in schema and (not isinstance(schema["enum"], list) or value not in schema["enum"]):
        raise ContractError("model output violates enum schema")


class CodexModelPort:
    """A persistent call-budgeted port that returns validated ``FrozenRecord`` values."""

    def __init__(self, executable: Path | str, work_root: Path, *, model: str = "gpt-5.6-luna",
                 effort: str = "low", max_calls: int, max_tokens: int,
                 schema_by_slot: Mapping[str, Mapping[str, Any]], timeout_seconds: int = 180,
                 process_runner: ProcessRunner | None = None) -> None:
        if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
            raise ContractError("model and effort must be nonempty")
        if type(max_calls) is not int or max_calls < 1 or type(max_tokens) is not int or max_tokens < 1:
            raise ContractError("positive model budgets required")
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ContractError("positive timeout required")
        if not isinstance(schema_by_slot, Mapping) or not schema_by_slot or any(not isinstance(k, str) or not k or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in k) for k in schema_by_slot):
            raise ContractError("nonempty schema map required")
        for schema in schema_by_slot.values():
            if schema.get("type") != "object":
                raise ContractError("model responses must be JSON objects")
            _validate_schema(schema, _schema_witness(schema))
        self.executable, self.root = str(executable), Path(work_root)
        self.model, self.effort = model, effort
        self.max_calls, self.max_tokens, self.schemas = max_calls, max_tokens, dict(schema_by_slot)
        self.timeout_seconds, self.runner = timeout_seconds, process_runner or subprocess.run
        self.root.mkdir(parents=True, exist_ok=True)
        self.call_root = self.root / "calls"
        self.call_root.mkdir(exist_ok=True)
        self.ledger_path = self.root / "ledger.json"
        config = {"schema": "codex-model-port-v1", "executable": self.executable, "model": model,
                  "effort": effort, "max_calls": max_calls, "max_tokens": max_tokens,
                  "schemas": self.schemas, "timeout_seconds": timeout_seconds}
        if self.ledger_path.exists():
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if self.ledger.get("config") != config:
                raise ContractError("existing model ledger has a different frozen configuration")
        else:
            self.ledger = {"config": config, "calls": [], "tokens": 0, "usage_incomplete": False}
            _atomic(self.ledger_path, self.ledger)

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        if not isinstance(request, FrozenRecord):
            raise ContractError("model port accepts immutable requests only")
        body = request.data()
        required = {"schema", "task", "lock_digest", "objective", "slot", "instruction", "context", "module_context", "execution_feedback"}
        if set(body) != required or body.get("schema") != "public-model-request-v1" or body["slot"] not in self.schemas:
            raise ContractError("unexpected RunSession model request")
        if self.ledger["usage_incomplete"] or len(self.ledger["calls"]) >= self.max_calls or self.ledger["tokens"] >= self.max_tokens:
            raise ContractError("model budget exhausted or usage incomplete")
        call_id = len(self.ledger["calls"]) + 1
        call_dir = self.call_root / f"{call_id:04d}-{body['slot']}"
        call_dir.mkdir()
        schema = self.schemas[body["slot"]]
        schema_path, output_path = call_dir / "schema.json", call_dir / "output.json"
        schema_path.write_text(canonical(schema), encoding="utf-8")
        prompt = "Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n" + request.encoded
        prompt_path = call_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        argv = [self.executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "-C", str(call_dir), "-m", self.model, "-s", "read-only", "--json", "--output-schema", str(schema_path), "-o", str(output_path), "-c", f'model_reasoning_effort="{self.effort}"', "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"', "-c", "features.skip_host_skill_discovery=true"]
        for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "hooks", "browser_use", "browser_use_external", "computer_use", "image_generation", "view_image", "sleep_tool", "workspace_dependencies", "skill_search", "in_app_browser", "goals"):
            argv.extend(("--disable", feature))
        argv.append("-")
        reservation = {"id": call_id, "slot": body["slot"], "request_hash": request.content_hash,
                       "prompt_hash": _sha(prompt.encode()), "status": "reserved", "provider": {"id": "codex-cli", "model": self.model}, "argv": argv}
        self.ledger["calls"].append(reservation)
        _atomic(self.ledger_path, self.ledger)  # Reservation precedes all provider I/O.
        try:
            result = self.runner(argv, input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            reservation.update({"status": "unknown", "error_type": type(exc).__name__})
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model timeout has unknown billing; do not retry") from exc
        except Exception as exc:
            reservation.update({"status": "failed", "error_type": type(exc).__name__})
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model provider failed; usage is incomplete") from exc
        stdout, stderr = result.stdout or "", result.stderr or ""
        (call_dir / "events.jsonl").write_text(stdout, encoding="utf-8")
        (call_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        usage = _usage(stdout)
        reservation.update({"exit_code": result.returncode, "events_hash": _sha(stdout.encode()), "stderr_hash": _sha(stderr.encode()), "usage": usage})
        if usage is None:
            self.ledger["usage_incomplete"] = True
        else:
            self.ledger["tokens"] += usage
        if result.returncode != 0 or not output_path.is_file():
            reservation["status"] = "failed"
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model CLI failed or did not produce output")
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
            _validate_schema(schema, output)
            response = FrozenRecord.from_dict(output)
        except (OSError, ValueError, ContractError) as exc:
            reservation["status"] = "failed"
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model output is not a valid slot response") from exc
        reservation.update({"status": "succeeded", "output_hash": response.content_hash})
        _atomic(self.ledger_path, self.ledger)
        return response


def _usage(events: str) -> int | None:
    totals = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
            usage = event.get("usage") if event.get("type") == "turn.completed" else None
            total = usage.get("total_tokens") if isinstance(usage, Mapping) else None
            if type(total) is int and total >= 0:
                totals.append(total)
        except (ValueError, AttributeError):
            continue
    return totals[-1] if totals else None


def _schema_witness(schema: Mapping[str, Any]) -> Any:
    """Validate schema structure without accepting arbitrary schema extensions."""
    if not isinstance(schema, Mapping):
        return None
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        return {key: _schema_witness(props[key]) for key in required if key in props}
    if kind == "array":
        return []
    if kind == "string": return "x"
    if kind == "number": return 0
    if kind == "integer": return 0
    if kind == "boolean": return False
    if kind == "null": return None
    return None
