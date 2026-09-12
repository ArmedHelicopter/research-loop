"""Bounded, no-tools Codex CLI model port.

The port is deliberately only a ``RunSession.invoke`` callable.  It does not
read datasets, produce evaluation metadata, or interpret a model response as a
score.  Its append-only reservation ledger makes an interrupted invocation
terminal for this port instance rather than something that can be replayed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical


ProcessRunner = Callable[..., Any]


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class TerminalCallInspection:
    """Read-only reconstruction of an already-terminal provider call."""

    def __init__(self, receipt: FrozenRecord, response: FrozenRecord | None) -> None:
        self.receipt, self.response = receipt, response


@dataclass(frozen=True)
class FrozenBaseContextPolicy:
    """Manually reviewed, non-secret identity of a matched CLI base context."""
    context_digest: str
    cli_sha256: str
    shared_argv_digest: str
    config_sources_hash: str
    fixed_cwd: Path
    config_sources: tuple[Path, ...]
    reviewed: bool = False

    def __post_init__(self) -> None:
        if self.reviewed is not True or not self.config_sources or any(not isinstance(x, str) or len(x) != 64 for x in (self.context_digest, self.cli_sha256, self.shared_argv_digest, self.config_sources_hash)):
            raise ContractError("reviewed frozen base-context digests required")


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
                 process_runner: ProcessRunner | None = None, context_probe_runner: ProcessRunner | None = None,
                 frozen_base_context: FrozenBaseContextPolicy | None = None) -> None:
        if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
            raise ContractError("model and effort must be nonempty")
        if type(max_calls) is not int or max_calls < 1 or type(max_tokens) is not int or max_tokens < 1:
            raise ContractError("positive model budgets required")
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ContractError("positive timeout required")
        if not isinstance(schema_by_slot, Mapping) or not schema_by_slot or any(not isinstance(k, str) or not k or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in k) for k in schema_by_slot):
            raise ContractError("nonempty schema map required")
        for schema in schema_by_slot.values():
            if not isinstance(schema, Mapping) or schema.get("type") != "object":
                raise ContractError("model responses must be JSON objects")
            _validate_schema(schema, _schema_witness(schema))
        executable_path = Path(executable).expanduser()
        resolved_executable = executable_path.resolve() if executable_path.is_absolute() else shutil.which(str(executable_path))
        if not resolved_executable:
            raise ContractError("Codex executable cannot be resolved")
        self.executable = str(Path(resolved_executable).resolve())
        self.root = Path(work_root).expanduser().resolve()
        self.model, self.effort = model, effort
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.schemas = json.loads(canonical(schema_by_slot))
        self.timeout_seconds, self.runner = timeout_seconds, process_runner or subprocess.run
        self.context_probe_runner = context_probe_runner or subprocess.run
        self.frozen_base_context = frozen_base_context
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
            if type(self.ledger.get("usage_incomplete")) is not bool or self.ledger["usage_incomplete"] or any(call.get("status") != "succeeded" for call in self.ledger.get("calls", [])):
                raise ContractError("existing model ledger has an incomplete call; inspect it instead of continuing")
        else:
            self.ledger = {"config": config, "calls": [], "context_probes": [], "tokens": 0, "usage_incomplete": False}
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
        self._require_no_skill_context()
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
        for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "hooks", "browser_use", "browser_use_external", "computer_use", "image_generation", "view_image", "sleep_tool", "workspace_dependencies", "skill_search", "memories", "in_app_browser", "goals"):
            argv.extend(("--disable", feature))
        argv.extend(("--enable", "skip_host_skill_discovery"))
        argv.append("-")
        if self.frozen_base_context is not None:
            argv = [item for item in argv if item not in {"--ignore-user-config", "--ignore-rules"}]
            argv[argv.index("-C") + 1] = str(self.frozen_base_context.fixed_cwd.resolve(strict=True))
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
        (call_dir / "events.jsonl").write_bytes(stdout.encode("utf-8"))
        (call_dir / "stderr.txt").write_bytes(stderr.encode("utf-8"))
        events = _events(stdout)
        usage = _usage(events)
        tools = _tool_events(events)
        faults = _context_faults(events)
        reservation.update({"exit_code": result.returncode, "events_hash": _sha(stdout.encode()), "stderr_hash": _sha(stderr.encode()), "usage": usage, "tool_events": tools, "context_faults": faults})
        if usage is None or tools or faults:
            reservation["status"] = "failed"
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model event stream has missing usage, forbidden execution, or untrusted context")
        self.ledger["tokens"] += usage["total_tokens"]
        if self.ledger["tokens"] > self.max_tokens:
            reservation["status"] = "over_budget"
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model call exceeded frozen token budget; do not continue")
        if result.returncode != 0 or not output_path.is_file():
            reservation["status"] = "failed"
            self.ledger["usage_incomplete"] = True
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("model CLI failed or did not produce output")
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
            _finite(output)
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

    def _require_no_skill_context(self) -> None:
        """Fail closed before paid I/O if the installed CLI exposes skills."""
        if self.frozen_base_context is not None:
            policy = self.frozen_base_context
            cwd = policy.fixed_cwd.resolve(strict=True)
            shared = ["--disable", "plugins", "--disable", "skill_search", "--disable", "memories", "--enable", "skip_host_skill_discovery", "-c", f'model="{self.model}"', "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"']
            manifest = {str(Path(path).resolve(strict=True)): _sha(Path(path).read_bytes()) for path in policy.config_sources}
            if _sha(canonical(shared).encode()) != policy.shared_argv_digest or _sha(Path(self.executable).read_bytes()) != policy.cli_sha256 or _sha(canonical(manifest).encode()) != policy.config_sources_hash:
                raise ContractError("frozen base-context executable or shared arguments drifted")
            argv = [self.executable, "debug", "prompt-input", *shared, "public context probe"]
            result = self.context_probe_runner(argv, text=True, encoding="utf-8", capture_output=True, timeout=30, cwd=str(cwd))
            raw = (result.stdout or "").encode("utf-8")
            if result.returncode or _sha(raw) != policy.context_digest:
                raise ContractError("frozen base context drifted before paid call")
            self.ledger.setdefault("context_probes", []).append({"status": "frozen_matched", "prompt_hash": _sha(raw)})
            _atomic(self.ledger_path, self.ledger)
            return
        isolated_home = self.root / "context-probe-home"
        isolated_home.mkdir(exist_ok=True)
        argv = [self.executable, "debug", "prompt-input", "--disable", "plugins", "--disable", "skill_search", "--disable", "memories", "--enable", "skip_host_skill_discovery", "public context probe"]
        environment = dict(os.environ)
        environment["CODEX_HOME"] = str(isolated_home)
        try:
            result = self.context_probe_runner(argv, text=True, encoding="utf-8", capture_output=True, timeout=30, env=environment)
            raw = (result.stdout or "").encode("utf-8")
            prompt_input = json.loads(raw.decode("utf-8"))
            rendered = canonical(prompt_input).lower()
            skills_present = any(marker in rendered for marker in ("<skills", "skills_instructions", "skill roots", "available skills"))
            accepted = result.returncode == 0 and isinstance(prompt_input, list) and bool(prompt_input) and not skills_present
        except Exception as exc:
            probe = {"status": "failed", "error_type": type(exc).__name__}
            self.ledger.setdefault("context_probes", []).append(probe)
            _atomic(self.ledger_path, self.ledger)
            raise ContractError("cannot verify no-skills model context") from exc
        probe = {"status": "accepted" if accepted else "rejected", "prompt_hash": _sha(raw), "skill_context_present": skills_present}
        self.ledger.setdefault("context_probes", []).append(probe)
        _atomic(self.ledger_path, self.ledger)
        if not accepted:
            raise ContractError("Codex prompt context contains skills; paid call refused")


def _events(stream: str) -> list[Mapping[str, Any]]:
    events = []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, Mapping):
                events.append(event)
        except ValueError:
            continue
    return events


def _usage(events: list[Mapping[str, Any]]) -> dict[str, int] | None:
    completed = [event.get("usage") for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1 or not isinstance(completed[0], Mapping):
        return None
    usage = completed[0]
    allowed = {"input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"}
    required = {"input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"}
    if set(usage) != required or set(usage) - allowed:
        return None
    if any(type(value) is not int or value < 0 for value in usage.values()):
        return None
    return {key: usage[key] for key in sorted(usage)} | {"total_tokens": usage["input_tokens"] + usage["output_tokens"]}


def _tool_events(events: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    blocked = {"command_execution", "mcp_tool_call", "web_search", "file_change"}
    found = []
    for event in events:
        kind = event.get("type")
        item = event.get("item")
        item_type = item.get("type") if isinstance(item, Mapping) else None
        names = [name for name in (kind, item_type) if isinstance(name, str)]
        if any(name in blocked or any(word in name.lower() for word in ("tool", "execution", "command", "mcp", "web_search", "file_change")) for name in names):
            found.append({"event_type": kind if isinstance(kind, str) else "", "item_type": item_type if isinstance(item_type, str) else ""})
    return found


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("non-finite model output is forbidden")
    if isinstance(value, list):
        for child in value:
            _finite(child)
    elif isinstance(value, dict):
        for child in value.values():
            _finite(child)


def inspect_terminal_call(work_root: Path, call_id: int) -> TerminalCallInspection:
    """Inspect a terminal call without changing its ledger or invoking Codex.

    This is the only recovery path for a parser failure after a provider has
    completed: it verifies on-disk hashes and returns the pre-existing response
    only when the frozen slot schema, single usage record and no-tools event
    stream all validate.
    """
    if type(call_id) is not int or call_id < 1:
        raise ContractError("positive terminal call id required")
    root = Path(work_root).expanduser().resolve(strict=True)
    ledger_path = root / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    calls = ledger.get("calls")
    if not isinstance(calls, list) or call_id > len(calls) or not isinstance(ledger.get("config"), Mapping):
        raise ContractError("terminal call is absent from ledger")
    call, config = calls[call_id - 1], ledger["config"]
    if not isinstance(call, Mapping) or call.get("id") != call_id or not isinstance(config.get("schemas"), Mapping):
        raise ContractError("terminal call receipt is malformed")
    slot = call.get("slot")
    if not isinstance(slot, str) or slot not in config["schemas"]:
        raise ContractError("terminal call has no frozen slot schema")
    call_dir = root / "calls" / f"{call_id:04d}-{slot}"
    events_path, output_path = call_dir / "events.jsonl", call_dir / "output.json"
    events_bytes = events_path.read_bytes()
    events_hash = _sha(events_bytes)
    stored_events_hash = call.get("events_hash")
    legacy_lf_events = _sha(events_bytes.replace(b"\r\n", b"\n"))
    if stored_events_hash is not None and stored_events_hash not in {events_hash, legacy_lf_events}:
        raise ContractError("terminal event hash mismatch")
    events = _events(events_bytes.decode("utf-8"))
    usage, tools = _usage(events), _tool_events(events)
    faults = _context_faults(events)
    response = None
    output_hash = None
    if output_path.is_file():
        output = json.loads(output_path.read_text(encoding="utf-8"))
        _finite(output)
        _validate_schema(config["schemas"][slot], output)
        response = FrozenRecord.from_dict(output)
        output_hash = response.content_hash
        if call.get("output_hash") is not None and call["output_hash"] != output_hash:
            raise ContractError("terminal output hash mismatch")
    receipt = FrozenRecord.from_dict({"schema": "terminal-model-call-inspection-v1", "call_id": call_id,
        "ledger_hash": _sha(ledger_path.read_bytes()), "stored_status": call.get("status"),
        "events_hash": events_hash, "events_hash_legacy_lf_match": stored_events_hash == legacy_lf_events and stored_events_hash != events_hash,
        "output_hash": output_hash, "usage": usage,
        "tool_events": tools, "context_faults": faults,
        "reconciled": usage is not None and not tools and not faults and response is not None})
    return TerminalCallInspection(receipt, response)


def _context_faults(events: list[Mapping[str, Any]]) -> list[str]:
    faults = []
    for event in events:
        item = event.get("item")
        if isinstance(item, Mapping) and item.get("type") == "error":
            message = item.get("message")
            if isinstance(message, str) and "skill" in message.lower():
                faults.append("skill_context_detected")
    return faults


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
