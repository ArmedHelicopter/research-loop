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
import re
import tomllib
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


DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "multi_agent", "multi_agent_v2", "apps", "plugins",
    "hooks", "browser_use", "browser_use_external", "computer_use", "image_generation",
    "view_image", "sleep_tool", "workspace_dependencies", "skill_search", "memories",
    "in_app_browser", "goals", "code_mode", "code_mode_host", "artifact", "tool_suggest",
    "enable_mcp_apps", "standalone_web_search", "request_permissions_tool",
    "default_mode_request_user_input", "skill_mcp_dependency_install", "remote_plugin",
)


def shared_args(model: str, effort: str, config_overrides: tuple[str, ...] = ()) -> list[str]:
    """The sole source of context-affecting flags, shared by debug and exec.

    Reviewed skill catalog overrides and per-server MCP disabling precede the
    invariant flags, so a policy cannot enable a forbidden execution feature.
    This is a reproducibility controller, not an OS isolation boundary.
    """
    args: list[str] = []
    for override in config_overrides:
        if not (override.startswith("skills.config=") or override.startswith("model_catalog_json=") or re.fullmatch(r'mcp_servers\.[A-Za-z0-9_-]+\.enabled=false', override)):
            raise ContractError("unsupported frozen context override")
        args.extend(("-c", override))
    for setting in (f"model={json.dumps(model)}", f"model_reasoning_effort={json.dumps(effort)}",
                    "project_doc_max_bytes=0", 'web_search="disabled"',
                    'sandbox_mode="read-only"', 'approval_policy="never"'):
        args.extend(("-c", setting))
    for feature in DISABLED_FEATURES:
        args.extend(("--disable", feature))
    args.extend(("--enable", "skip_host_skill_discovery"))
    return args


def _base_context_bytes(raw: bytes) -> bytes:
    """Keep exact model-visible role/content; discard only transport metadata.

    The CLI emits fresh IDs and timestamps for every debug render. They are
    archived in the raw artifact, but are not prompt content. Unknown message
    or content forms fail closed instead of being silently dropped.
    """
    try:
        messages = json.loads(raw)
        if not isinstance(messages, list) or not messages:
            raise ValueError("empty prompt")
        visible = []
        for message in messages:
            if (not isinstance(message, dict) or set(message) - {"type", "id", "role", "content", "internal_chat_message_metadata_passthrough"}
                    or message.get("type", "message") != "message" or message.get("role") not in {"system", "developer", "user"}
                    or not isinstance(message.get("content"), list) or not message["content"]):
                raise ValueError("invalid message")
            for content in message["content"]:
                if (not isinstance(content, dict) or set(content) != {"type", "text"}
                        or content["type"] != "input_text" or not isinstance(content["text"], str) or not content["text"].strip()):
                    raise ValueError("invalid text content")
            visible.append({"role": message["role"], "content": message["content"]})
        return canonical(visible).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ContractError("empty or malformed debug base context") from exc


def context_source_specs(codex_home: Path, fixed_cwd: Path, *, model_catalog_path: Path | None = None,
                         environment: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """Minimum local sources; the reviewer must add external referenced files.

    Glob inventories bind additions/deletions as well as content changes. Auth
    files are neither read nor copied. The default user configuration is used.
    """
    home, cwd = codex_home.resolve(), fixed_cwd.resolve()
    child_environment = dict(os.environ) if environment is None else dict(environment)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in child_environment.items()):
        raise ContractError("context environment must contain string keys and values")
    profile = Path(child_environment.get("USERPROFILE") or child_environment.get("HOME") or str(home.parent)).resolve()
    specs = [{"path": str(home / name)} for name in ("config.toml", "AGENTS.md", "AGENTS.override.md")]
    specs.append({"path": str(model_catalog_path.resolve() if model_catalog_path else home / "models_cache.json")})
    specs += [{"path": str(home / "rules"), "glob": "**/*.rules"},
              {"path": str(home / "skills"), "glob": "**/SKILL.md"},
              {"path": str(profile / ".agents" / "skills"), "glob": "**/SKILL.md"}]
    for ancestor in (cwd, *cwd.parents):
        specs += [{"path": str(ancestor / ".codex" / "config.toml")},
                  {"path": str(ancestor / "AGENTS.md")}, {"path": str(ancestor / "AGENTS.override.md")}]
    return specs


def _source_manifest(specs: list[dict[str, str]]) -> dict[str, Any]:
    if not isinstance(specs, list) or not specs:
        raise ContractError("configuration source inventory required")
    manifest = {}
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) not in ({"path"}, {"path", "glob"}) or not isinstance(spec["path"], str) or not Path(spec["path"]).is_absolute():
            raise ContractError("invalid configuration source inventory")
        path = Path(spec["path"])
        key = canonical(spec)
        if key in manifest:
            raise ContractError("duplicate configuration source")
        if "glob" in spec:
            if not isinstance(spec["glob"], str) or not spec["glob"]:
                raise ContractError("invalid source glob")
            manifest[key] = {str(p.resolve()): _sha(p.read_bytes()) for p in sorted(path.glob(spec["glob"])) if p.is_file()}
        else:
            manifest[key] = _sha(path.read_bytes()) if path.is_file() else None
    return manifest


@dataclass(frozen=True)
class FrozenBaseContextPolicy:
    """A hash-pinned reviewed manifest; a boolean cannot qualify a context."""
    source: Path
    sha256: str

    def data(self) -> dict[str, Any]:
        try:
            raw = Path(self.source).resolve(strict=True).read_bytes()
            if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None or _sha(raw) != self.sha256:
                raise ContractError("frozen context policy source drifted")
            policy = json.loads(raw)
            review = policy.get("review", {})
            if (policy.get("schema") != "frozen-base-context-policy-v2" or policy.get("status") != "REVIEWED"
                    or not isinstance(review, dict) or any(not isinstance(review.get(k), str) or not review[k].strip()
                       for k in ("reviewer", "reviewed_at", "rationale", "source_completeness"))):
                raise ContractError("unqualified frozen context requires material review provenance")
            audit_raw = Path(policy["audit_path"]).read_bytes()
            audit = json.loads(audit_raw)
            if _sha(audit_raw) != policy["audit_sha256"] or policy["binding"] != audit["binding"] or audit.get("paid_call") is not False:
                raise ContractError("frozen context review audit binding mismatch")
            binding = policy["binding"]
            context_raw = Path(audit["raw_context_path"]).read_bytes()
            if _sha(context_raw) != audit["raw_context_sha256"] or _sha(_base_context_bytes(context_raw)) != binding["context_digest"]:
                raise ContractError("frozen context review material drifted")
            notices = policy.get("allowed_startup_notices", [])
            if notices and (not isinstance(review.get("startup_notice_rationale"), str) or not review["startup_notice_rationale"].strip()):
                raise ContractError("startup notices require explicit reviewed rationale")
            _reviewed_notice_messages(binding, notices)
            return policy
        except ContractError:
            raise
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise ContractError("invalid frozen context policy material") from exc


def _expected_startup_notices(binding: Mapping[str, Any]) -> dict[str, str]:
    """Only these known CLI notices describe an already frozen configuration.

    These are not skill catalog/truncation/load notices. No such notice can be
    inferred from a reviewed catalog, and none is eligible for this exception.
    """
    args = binding.get("shared_argv", [])
    pairs = set(zip(args, args[1:]))
    expected = {}
    if ("--enable", "skip_host_skill_discovery") in pairs:
        config = str(Path(binding["codex_home"]) / "config.toml")
        expected["unstable_skip_host_skill_discovery"] = (
            "Under-development features enabled: skip_host_skill_discovery. "
            "Under-development features are incomplete and may behave unpredictably. "
            "To suppress this warning, set `suppress_unstable_features_warning = true` in " + config + ".")
    if all(("--disable", name) in pairs for name in ("code_mode", "code_mode_host")):
        expected["disabled_code_mode_host"] = (
            "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; "
            "enable `features.code_mode_host` and install `codex-code-mode-host`.")
    return expected


def _notice_envelope(event: Mapping[str, Any]) -> str | None:
    item = event.get("item")
    if (set(event) == {"type", "item"} and event["type"] == "item.completed"
            and isinstance(item, dict) and set(item) == {"id", "type", "message"}
            and isinstance(item["id"], str) and item["type"] == "error" and isinstance(item["message"], str)):
        return item["message"]
    return None


def _reviewed_notice_messages(binding: Mapping[str, Any], entries: Any) -> frozenset[str]:
    """Validate exact notices against frozen flags and archived observed events."""
    if not isinstance(entries, list):
        raise ContractError("startup notice allowlist must be a list")
    expected, messages = _expected_startup_notices(binding), set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"kind", "message", "source_events_path", "source_events_sha256"}
                or entry.get("kind") not in expected or entry.get("message") != expected[entry["kind"]]
                or entry["message"] in messages):
            raise ContractError("unrecognized or configuration-mismatched startup notice")
        try:
            source = Path(entry["source_events_path"])
            if not source.is_absolute():
                raise ValueError("absolute archived event path required")
            raw = source.read_bytes()
            if _sha(raw) != entry["source_events_sha256"]:
                raise ValueError("archived notice source hash mismatch")
            # Exact JSONL is required; malformed lines cannot be discarded while
            # deciding whether an archived event is reviewable startup evidence.
            events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
            if not events or any(not isinstance(event, dict) for event in events):
                raise ValueError("invalid archived event stream")
            _, accepted = _context_diagnostics(events, frozenset({entry["message"]}))
            if len(accepted) != 1 or sum(_notice_envelope(event) == entry["message"] for event in events) != 1:
                raise ValueError("exact single startup notice absent from source")
        except (OSError, ValueError, TypeError) as exc:
            raise ContractError("startup notice lacks valid archived provenance") from exc
        messages.add(entry["message"])
    return frozenset(messages)


def _require_empty_public_cwd(cwd: Path) -> None:
    if not cwd.is_absolute() or not cwd.is_dir() or list(cwd.iterdir()):
        raise ContractError("frozen context cwd must be a fixed empty directory")
    if any((ancestor / "data" / "labels").exists() for ancestor in (cwd.resolve(), *cwd.resolve().parents)):
        raise ContractError("frozen context cwd has a private label ancestor")


def _runtime_binding(executable: str, cwd: Path, environment: dict[str, str], args: list[str],
                     specs: list[dict[str, str]], overrides: list[str]) -> dict[str, Any]:
    _require_empty_public_cwd(cwd)
    cli = Path(executable).resolve(strict=True)
    if os.name == "nt" and cli.suffix.lower() != ".exe":
        raise ContractError("reviewed context requires a direct CLI executable, not an unhashed launcher chain")
    home = Path(environment.get("CODEX_HOME") or str(Path(environment.get("USERPROFILE") or environment.get("HOME") or str(Path.home())) / ".codex")).resolve()
    catalogs = [override.split("=", 1)[1] for override in overrides if override.startswith("model_catalog_json=")]
    if len(catalogs) > 1:
        raise ContractError("one frozen model catalog override permitted")
    catalog = None
    if catalogs:
        try:
            catalog_value = json.loads(catalogs[0])
            if not isinstance(catalog_value, str) or not Path(catalog_value).is_absolute():
                raise ValueError("absolute catalog path required")
            catalog = Path(catalog_value).resolve(strict=True)
            catalog_data = json.loads(catalog.read_bytes())
            if not isinstance(catalog_data, dict) or set(catalog_data) != {"models"} or not isinstance(catalog_data["models"], list) or not catalog_data["models"]:
                raise ValueError("nonempty local model catalog required")
        except (ValueError, OSError, TypeError) as exc:
            raise ContractError("invalid frozen local model catalog") from exc
    required = {canonical(spec) for spec in context_source_specs(home, cwd, model_catalog_path=catalog, environment=environment)}
    if not required <= {canonical(spec) for spec in specs}:
        raise ContractError("frozen context omits mandatory default configuration sources")
    sources = _source_manifest(specs)
    for spec in specs:
        source = Path(spec["path"])
        if "glob" not in spec and source.suffix == ".toml" and source.is_file():
            config = tomllib.loads(source.read_text(encoding="utf-8"))
            for name in config.get("mcp_servers", {}):
                if f'mcp_servers.{name}.enabled=false' not in overrides:
                    raise ContractError("every configured MCP server must be explicitly disabled")
    return {"cli_path": str(cli), "cli_sha256": _sha(cli.read_bytes()), "fixed_cwd": str(cwd.resolve()),
            "environment_sha256": _sha(canonical(environment).encode()), "codex_home": str(home),
            "shared_argv": args, "shared_argv_digest": _sha(canonical(args).encode()),
            "config_overrides": list(overrides), "source_specs": specs,
            "config_sources": sources, "config_sources_hash": _sha(canonical(sources).encode())}


def audit_base_context(executable: Path, fixed_cwd: Path, audit_root: Path, *,
                       model: str = "gpt-5.6-luna", effort: str = "low",
                       source_specs: list[dict[str, str]] | None = None,
                       config_overrides: tuple[str, ...] = (),
                       context_probe_runner: ProcessRunner = subprocess.run,
                        environment: Mapping[str, str] | None = None) -> Path:
    """Archive one NO-PAID render and an UNQUALIFIED review candidate.

    This never qualifies itself. A reviewer must inspect the render, source
    inventory, permitted common context and CLI limitations, then write a
    separate REVIEWED manifest with concrete provenance and pin its SHA256.
    """
    cli, cwd, root = executable.resolve(strict=True), fixed_cwd.resolve(strict=True), audit_root.resolve()
    _require_empty_public_cwd(cwd)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ContractError("audit destination must be empty; preserve previous audit evidence")
    environment = dict(os.environ) if environment is None else dict(environment)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
        raise ContractError("context environment must contain string keys and values")
    home = Path(environment.get("CODEX_HOME") or str(Path.home() / ".codex"))
    specs = source_specs if source_specs is not None else context_source_specs(home, cwd, environment=environment)
    overrides = list(config_overrides)
    args = shared_args(model, effort, tuple(overrides))
    binding = _runtime_binding(str(cli), cwd, environment, args, specs, overrides)
    argv = [str(cli), "debug", "prompt-input", *args]
    result = context_probe_runner(argv, text=True, encoding="utf-8", capture_output=True,
                                  timeout=30, cwd=str(cwd), env=dict(environment))
    raw = (result.stdout or "").encode("utf-8")
    raw_path = root / "debug-prompt-input.raw.json"
    raw_path.write_bytes(raw)
    # Do not print or persist stderr values; CLI diagnostics can contain config details.
    if result.returncode != 0:
        _atomic(root / "UNQUALIFIED-BASE-CONTEXT-AUDIT.json", {
            "schema": "base-context-audit-v2", "status": "UNQUALIFIED_DEBUG_FAILED", "paid_call": False,
            "argv": argv, "binding": binding, "raw_context_path": str(raw_path),
            "raw_context_sha256": _sha(raw), "exit_code": result.returncode,
            "stderr_sha256": _sha((result.stderr or "").encode())})
        raise ContractError("no-paid debug render failed; raw artifact preserved")
    visible = _base_context_bytes(raw)
    after = _runtime_binding(str(cli), cwd, environment, args, specs, overrides)
    if after != binding:
        _atomic(root / "UNQUALIFIED-BASE-CONTEXT-AUDIT.json", {
            "schema": "base-context-audit-v2", "status": "UNQUALIFIED_SOURCE_DRIFT", "paid_call": False,
            "argv": argv, "binding": binding, "after_binding": after,
            "changed_fields": [key for key in binding if binding[key] != after[key]],
            "changed_source_paths": [key for key in binding["config_sources"] if binding["config_sources"][key] != after["config_sources"].get(key)],
            "raw_context_path": str(raw_path), "raw_context_sha256": _sha(raw)})
        raise ContractError("configuration changed during no-paid context audit")
    visible_path = root / "base-context.visible.json"
    visible_path.write_bytes(visible)
    binding["context_digest"] = _sha(visible)
    audit = {"schema": "base-context-audit-v2", "status": "UNQUALIFIED_PENDING_REVIEW", "paid_call": False,
             "argv": argv, "binding": binding, "raw_context_path": str(raw_path),
             "raw_context_sha256": _sha(raw), "visible_context_path": str(visible_path),
             "stderr_sha256": _sha((result.stderr or "").encode()), "exit_code": result.returncode,
             "limitations": ["Debug renders base prompt messages, not the full provider request or its tool schema.",
                 "Only transport message IDs and internal metadata are excluded from the visible digest; all role/content text is exact.",
                 "Exec adds request text and the ledger-frozen per-slot response schema.",
                 "Manual review must establish completeness of local and externally referenced configuration sources.",
                 "The environment is identical within each probe/exec pair and hash-bound across ledger reuse; values are not archived.",
                 "This controller does not prove an OS sandbox or atomic protection against concurrent filesystem mutation.",
                 "Remote provider instructions and model deployment changes are outside this local digest."]}
    audit_path = root / "UNQUALIFIED-BASE-CONTEXT-AUDIT.json"
    _atomic(audit_path, audit)
    candidate = {"schema": "frozen-base-context-policy-v2", "status": "UNQUALIFIED", "review": {},
                 "audit_path": str(audit_path), "audit_sha256": _sha(audit_path.read_bytes()), "binding": binding}
    candidate_path = root / "UNQUALIFIED-POLICY.json"
    _atomic(candidate_path, candidate)
    return candidate_path


def _validate_schema(schema: Any, value: Any) -> None:
    """Small closed JSON Schema subset used for model response slots."""
    if not isinstance(schema, Mapping) or set(schema) - {"type", "properties", "required", "additionalProperties", "items", "enum", "minimum", "maximum", "minItems", "maxItems"}:
        raise ContractError("unsupported output schema")
    kind = schema.get("type")
    if isinstance(kind, list):
        if kind != ["string", "null"] or set(schema) != {"type"}:
            if kind != ["object", "null"]:
                raise ContractError("only closed nullable string or object schemas are supported")
            if value is None:
                return
            narrowed = dict(schema)
            narrowed["type"] = "object"
            _validate_schema(narrowed, value)
            return
        if value is not None and not isinstance(value, str):
            raise ContractError("model output violates nullable string schema")
        return
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
        if any(name in schema and (type(schema[name]) is not int or schema[name] < 0) for name in ("minItems", "maxItems")):
            raise ContractError("array item bounds must be nonnegative integers")
        if "minItems" in schema and "maxItems" in schema and schema["minItems"] > schema["maxItems"]:
            raise ContractError("array item bounds are inconsistent")
        if (("minItems" in schema and len(value) < schema["minItems"])
                or ("maxItems" in schema and len(value) > schema["maxItems"])):
            raise ContractError("model output violates array item bounds")
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
    if kind != "array" and ("minItems" in schema or "maxItems" in schema):
        raise ContractError("array item bounds require an array schema")
    if "minimum" in schema or "maximum" in schema:
        if kind not in {"number", "integer"}:
            raise ContractError("numeric bounds require a numeric output schema")
        for name in ("minimum", "maximum"):
            if name in schema and (type(schema[name]) not in {int, float} or isinstance(schema[name], bool)
                    or not math.isfinite(float(schema[name]))):
                raise ContractError("output schema has invalid numeric bounds")
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError("model output violates minimum schema")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError("model output violates maximum schema")
    if "enum" in schema and (not isinstance(schema["enum"], list) or value not in schema["enum"]):
        raise ContractError("model output violates enum schema")


class CodexModelPort:
    """A persistent call-budgeted port that returns validated ``FrozenRecord`` values."""

    def __init__(self, executable: Path | str, work_root: Path, *, model: str = "gpt-5.6-luna",
                 effort: str = "low", max_calls: int, max_tokens: int,
                 schema_by_slot: Mapping[str, Mapping[str, Any]], timeout_seconds: int = 180,
                 process_runner: ProcessRunner | None = None, context_probe_runner: ProcessRunner | None = None,
                 frozen_base_context: FrozenBaseContextPolicy | None = None,
                 allow_mock_context: bool = False, environment: Mapping[str, str] | None = None,
                 _ledger_purpose: str | None = None, _ledger_request_contract: str | None = None,
                 _ledger_contract_binding: Mapping[str, Any] | None = None) -> None:
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
        if (_ledger_purpose is None) != (_ledger_request_contract is None):
            raise ContractError("ledger purpose and request contract must be supplied together")
        if _ledger_purpose is not None and (not isinstance(_ledger_purpose, str) or not _ledger_purpose
                or not isinstance(_ledger_request_contract, str) or not _ledger_request_contract):
            raise ContractError("ledger purpose and request contract must be nonempty")
        if _ledger_contract_binding is not None and (not isinstance(_ledger_contract_binding, Mapping)
                or not _ledger_purpose):
            raise ContractError("ledger contract binding requires a purpose")
        self._ledger_purpose, self._ledger_request_contract = _ledger_purpose, _ledger_request_contract
        self._ledger_contract_binding = (json.loads(canonical(_ledger_contract_binding))
                                         if _ledger_contract_binding is not None else None)
        self.model, self.effort = model, effort
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.schemas = json.loads(canonical(schema_by_slot))
        self.schemas_digest = _sha(canonical(self.schemas).encode())
        self.timeout_seconds, self.runner = timeout_seconds, process_runner or subprocess.run
        self.context_probe_runner = context_probe_runner or subprocess.run
        self.frozen_base_context = frozen_base_context
        # Explicit fixture-only seam: never usable with either real subprocess runner.
        if type(allow_mock_context) is not bool or (allow_mock_context and
                (process_runner is None or context_probe_runner is None or
                 process_runner is subprocess.run or context_probe_runner is subprocess.run)):
            raise ContractError("mock context requires explicit non-subprocess fixture runners")
        if allow_mock_context and frozen_base_context is not None:
            raise ContractError("mock and reviewed contexts are mutually exclusive")
        self.mock_context = allow_mock_context
        self.environment = dict(os.environ) if environment is None else dict(environment)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.environment.items()):
            raise ContractError("model environment must contain string keys and values")
        self.policy_data = frozen_base_context.data() if frozen_base_context else None
        self.context_binding = self.policy_data["binding"] if self.policy_data else None
        self.allowed_startup_notices = self.policy_data.get("allowed_startup_notices", []) if self.policy_data else []
        self.allowed_notice_messages = _reviewed_notice_messages(self.context_binding, self.allowed_startup_notices) if self.context_binding else frozenset()
        self.fixed_cwd = Path(self.context_binding["fixed_cwd"]) if self.context_binding else self.root / "fixture-cwd"
        if self.mock_context:
            self.fixed_cwd.mkdir(parents=True, exist_ok=True)
        overrides = tuple(self.context_binding["config_overrides"]) if self.context_binding else ()
        self.shared = shared_args(self.model, self.effort, overrides)
        self.root.mkdir(parents=True, exist_ok=True)
        self.call_root = self.root / "calls"
        self.call_root.mkdir(exist_ok=True)
        self.ledger_path = self.root / "ledger.json"
        config = {"schema": "codex-model-port-v1", "executable": self.executable, "model": model,
                  "effort": effort, "max_calls": max_calls, "max_tokens": max_tokens,
                  "schemas": self.schemas, "timeout_seconds": timeout_seconds,
                  "context_mode": "mock_fixture" if self.mock_context else "reviewed" if frozen_base_context else "unqualified",
                  "context_policy": {"source": str(Path(frozen_base_context.source).resolve()), "sha256": frozen_base_context.sha256,
                                     "binding": self.context_binding, "allowed_startup_notices": self.allowed_startup_notices} if frozen_base_context else None,
                  "shared_argv": self.shared, "fixed_cwd": str(self.fixed_cwd),
                  "environment_sha256": _sha(canonical(self.environment).encode())}
        if self._ledger_purpose is not None:
            config["purpose"] = self._ledger_purpose
            config["request_contract"] = self._ledger_request_contract
        if self._ledger_contract_binding is not None:
            config["request_contract_binding"] = self._ledger_contract_binding
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
        prompt = "Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n" + request.encoded
        return self._invoke_protected(request, slot=body["slot"], schema=self.schemas[body["slot"]], prompt=prompt)

    def _invoke_protected(self, request: FrozenRecord, *, slot: str, schema: Mapping[str, Any], prompt: str) -> FrozenRecord:
        """Run a prevalidated frozen request through the shared no-tools path.

        Subclasses may use this only after validating their distinct request
        contract. Public RunSession requests continue through ``__call__``.
        """
        if (not isinstance(request, FrozenRecord) or not isinstance(slot, str) or not slot
                or not isinstance(schema, Mapping) or schema != self.schemas.get(slot)
                or not isinstance(prompt, str) or not prompt):
            raise ContractError("protected model invocation has an invalid frozen contract")
        if self.ledger["usage_incomplete"] or len(self.ledger["calls"]) >= self.max_calls or self.ledger["tokens"] >= self.max_tokens:
            raise ContractError("model budget exhausted or usage incomplete")
        self._require_frozen_context()
        call_id = len(self.ledger["calls"]) + 1
        call_dir = self.call_root / f"{call_id:04d}-{slot}"
        call_dir.mkdir()
        schema_path, output_path = call_dir / "schema.json", call_dir / "output.json"
        schema_path.write_text(canonical(schema), encoding="utf-8")
        prompt_path = call_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        argv = [self.executable, "exec", *self.shared, "--ephemeral", "--skip-git-repo-check",
                "--json", "--output-schema", str(schema_path), "-o", str(output_path), "-"]
        reservation = {"id": call_id, "slot": slot, "request_hash": request.content_hash,
                       "prompt_hash": _sha(prompt.encode()), "status": "reserved", "provider": {"id": "codex-cli", "model": self.model}, "argv": argv,
                       "cwd": str(self.fixed_cwd), "environment_sha256": _sha(canonical(self.environment).encode()),
                       "context_policy_sha256": self.frozen_base_context.sha256 if self.frozen_base_context else None,
                       "context_probe": len(self.ledger["context_probes"]), "schema_hash": _sha(schema_path.read_bytes())}
        if self._ledger_purpose is not None:
            reservation["purpose"] = self._ledger_purpose
            reservation["request_contract"] = self._ledger_request_contract
        self._verify_context_binding()
        self.ledger["calls"].append(reservation)
        _atomic(self.ledger_path, self.ledger)
        try:
            result = self.runner(argv, input=prompt, text=True, encoding="utf-8", capture_output=True,
                                 timeout=self.timeout_seconds, cwd=str(self.fixed_cwd), env=dict(self.environment))
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
        faults, notices = _context_diagnostics(events, self.allowed_notice_messages)
        reservation.update({"exit_code": result.returncode, "events_hash": _sha(stdout.encode()), "stderr_hash": _sha(stderr.encode()), "usage": usage, "tool_events": tools, "context_faults": faults,
                            "reviewed_startup_notices": notices})
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

    def _verify_context_binding(self) -> None:
        if _sha(canonical(self.schemas).encode()) != self.schemas_digest:
            raise ContractError("frozen per-slot response schema drifted")
        if self.mock_context:
            if list(self.fixed_cwd.iterdir()):
                raise ContractError("mock fixed cwd is no longer empty")
            return
        if self.frozen_base_context is None:
            raise ContractError("unqualified base context; paid call refused")
        policy = self.frozen_base_context.data()
        binding = policy["binding"]
        _require_empty_public_cwd(self.fixed_cwd)
        if binding != self.context_binding:
            raise ContractError("frozen context policy binding drifted")
        if str(self.fixed_cwd.resolve()) != binding["fixed_cwd"] or self.shared != shared_args(self.model, self.effort, tuple(binding["config_overrides"])):
            raise ContractError("frozen context shared argv or cwd drifted")
        live = _runtime_binding(self.executable, self.fixed_cwd, self.environment,
                                self.shared, binding["source_specs"], binding["config_overrides"])
        if live != {k: v for k, v in binding.items() if k != "context_digest"}:
            raise ContractError("frozen base-context CLI, configuration, environment or shared arguments drifted")

    def _require_frozen_context(self) -> None:
        """Verify reviewed identity and render before any paid reservation."""
        self._verify_context_binding()
        argv = [self.executable, "debug", "prompt-input", *self.shared]
        probe_dir = self.root / "context-probes"
        probe_dir.mkdir(exist_ok=True)
        number = len(self.ledger["context_probes"]) + 1
        raw_path = probe_dir / f"{number:04d}.json"
        receipt = {"status": "rejected", "argv": argv, "cwd": str(self.fixed_cwd),
                   "environment_sha256": _sha(canonical(self.environment).encode()),
                   "raw_path": str(raw_path)}
        try:
            result = self.context_probe_runner(argv, text=True, encoding="utf-8", capture_output=True,
                                               timeout=30, cwd=str(self.fixed_cwd), env=dict(self.environment))
            raw = (result.stdout or "").encode("utf-8")
            raw_path.write_bytes(raw)
            receipt.update({"exit_code": result.returncode, "raw_sha256": _sha(raw)})
            if result.returncode != 0:
                raise ContractError("debug base context render failed")
            visible = _base_context_bytes(raw)
            receipt["context_digest"] = _sha(visible)
            self._verify_context_binding()
            if self.context_binding and receipt["context_digest"] != self.context_binding["context_digest"]:
                raise ContractError("frozen base context drifted before paid call")
            receipt["status"] = "mock_fixture" if self.mock_context else "frozen_matched"
        except Exception as exc:
            receipt["error_type"] = type(exc).__name__
            raise ContractError(f"cannot verify frozen model context: {exc}") from exc
        finally:
            self.ledger["context_probes"].append(receipt)
            _atomic(self.ledger_path, self.ledger)


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
    recorded_policy = config.get("context_policy") or {}
    allowed = _reviewed_notice_messages(recorded_policy.get("binding", {}), recorded_policy.get("allowed_startup_notices", []))
    faults, notices = _context_diagnostics(events, allowed)
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
        "tool_events": tools, "context_faults": faults, "reviewed_startup_notices": notices,
        "reconciled": usage is not None and not tools and not faults and response is not None})
    return TerminalCallInspection(receipt, response)


def _context_diagnostics(events: list[Mapping[str, Any]], allowed: frozenset[str] = frozenset()) -> tuple[list[str], list[dict[str, Any]]]:
    faults, accepted, seen = [], [], set()
    startup = True
    for event in events:
        item = event.get("item")
        kind = item.get("type") if isinstance(item, Mapping) else None
        is_diagnostic = any(isinstance(name, str) and any(marker in name.lower() for marker in ("error", "warning", "failed"))
                            for name in (kind, event.get("type")))
        if is_diagnostic:
            message = item.get("message") if isinstance(item, Mapping) else event.get("message")
            exact = _notice_envelope(event)
            if startup and exact in allowed and exact not in seen:
                seen.add(exact)
                accepted.append({"message_sha256": _sha(exact.encode()), "event_type": event["type"], "phase": "startup"})
            else:
                faults.append("skill_context_detected" if isinstance(message, str) and "skill" in message.lower() else "unreviewed_diagnostic_event")
        elif event.get("type") != "thread.started":
            startup = False
    return faults, accepted


def _context_faults(events: list[Mapping[str, Any]]) -> list[str]:
    """Conservative historical inspection: no implicit notice exceptions."""
    return _context_diagnostics(events)[0]


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
        minimum = schema.get("minItems", 0)
        count = minimum if type(minimum) is int and minimum >= 0 else 0
        return [_schema_witness(schema.get("items", {})) for _ in range(count)]
    if kind == "string": return "x"
    if kind == "number": return schema.get("minimum", 0)
    if kind == "integer": return schema.get("minimum", 0)
    if kind == "boolean": return False
    if kind == "null": return None
    return None
