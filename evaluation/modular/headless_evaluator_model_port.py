"""Closed headless native port for frozen, private rubric evaluation calls."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import MODEL, diagnostic_config
from research_loop.modular.grok_headless_transport import HeadlessResult, run_headless_diagnostic, verify_headless_request_binding
from research_loop.modular.grok_native_deployment import checked_headless_train_deployment
from research_loop.modular.model_port import _validate_schema
from research_loop.ontology import ContractError, canonical


RECOVERY = {"schema": "headless-account-read-recovery-v1", "max_attempts": 2}
_REQUEST_SCHEMA = "frozen-independent-evaluator-call-v1"
_PROMPT_PREFIX = "Return only JSON conforming to the supplied schema.\n"
_MAIN_OUTPUT_CAP = 2048
_OBSERVED_MAIN_TOKEN_CAP = 131072
_INPUT_BYTE_CAP = 262144


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object) -> str:
    return _sha(canonical(value).encode("utf-8"))


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _exclusive(path: Path):
    acquired = False
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        acquired = True
        yield
    except FileExistsError as exc:
        raise ContractError("headless evaluator allocator is already in use") from exc
    finally:
        if acquired:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _source_pins(rubric_mode: str, deployment=None) -> dict[str, str]:
    """Pin every local implementation that interprets this private contract."""
    import evaluation.modular.headless_evaluator_model_port as port
    import evaluation.modular.scoring_service as scoring
    import research_loop.modular.contracts as contracts
    import research_loop.modular.grok_acp_transport as acp
    import research_loop.modular.grok_cli_protocol as protocol
    import research_loop.modular.grok_headless_transport as transport
    import research_loop.modular.model_port as model_port
    import research_loop.ontology as ontology

    paths = [Path(port.__file__).resolve(), Path(scoring.__file__).resolve(), Path(contracts.__file__).resolve(),
             Path(acp.__file__).resolve(), Path(protocol.__file__).resolve(), Path(transport.__file__).resolve(),
             Path(model_port.__file__).resolve(), Path(ontology.__file__).resolve()]
    if rubric_mode == "lineage_v1":
        import evaluation.modular.lineage_rubric as lineage
        paths.append(Path(lineage.__file__).resolve())
    if deployment is not None:
        paths.extend(Path(path) for path in checked_headless_train_deployment(deployment).source_pins())
    return {str(path): _sha(path.read_bytes()) for path in paths}


class GrokHeadlessEvaluatorModelPort:
    """One private frozen-rubric reservation per call; any uncertainty closes it."""

    provider_kind = "grok-headless-frozen-evaluator-v1"

    @property
    def config(self) -> dict[str, Any]:
        """Compatibility view; every access gets a fresh immutable-record projection."""
        return self._config_record.data()

    def __init__(self, *, executable: Path | str, work_root: Path, private_home: Path, private_profile: Path,
                 public_cwd: Path, frozen_files: Mapping[str, str], evaluator_id: str, evaluator_version: str,
                 rubric_mode: str = "primary_v1", max_calls: int, max_tokens: int,
                 timeout_seconds: int = 60, account_read_recovery: Mapping[str, Any] = RECOVERY,
                 deployment=None) -> None:
        if (rubric_mode not in {"primary_v1", "lineage_v1"} or not isinstance(evaluator_id, str) or not evaluator_id
                or not isinstance(evaluator_version, str) or not evaluator_version or type(max_calls) is not int
                or max_calls < 1 or type(max_tokens) is not int or max_tokens < 1
                or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 240
                or not isinstance(account_read_recovery, Mapping) or dict(account_read_recovery) != RECOVERY
                or type(account_read_recovery.get("max_attempts")) is not int):
            raise ContractError("invalid headless evaluator configuration")
        if rubric_mode == "lineage_v1":
            from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint
            self.endpoint_type = FrozenLineageRubricEndpoint
        else:
            self.endpoint_type = FrozenBenchmarkRubricEndpoint
        self.native_deployment = None if deployment is None else checked_headless_train_deployment(deployment)
        self.executable = str(Path(executable).resolve())
        self.root = Path(work_root).resolve()
        self.private_home = Path(private_home).resolve()
        self.private_profile = Path(private_profile).resolve()
        self.public_cwd = Path(public_cwd).resolve()
        supplied = dict(frozen_files)
        executable_sha256 = _sha(Path(self.executable).read_bytes())
        if self.native_deployment is not None:
            self.native_deployment.verify_executable(self.executable)
        if supplied.get(self.executable) != executable_sha256:
            raise ContractError("supplied evaluator executable pin differs")
        generated = (_source_pins(rubric_mode) if self.native_deployment is None
                     else _source_pins(rubric_mode, self.native_deployment))
        if any(path in supplied and supplied[path] != digest for path, digest in generated.items()):
            raise ContractError("supplied evaluator source pin differs")
        supplied.update(generated)
        if any(not isinstance(path, str) or _digest(value, "frozen file") != value for path, value in supplied.items()):
            raise ContractError("invalid evaluator frozen file pin")
        self.frozen_files = json.loads(canonical(supplied))
        self.evaluator_id, self.evaluator_version, self.rubric_mode = evaluator_id, evaluator_version, rubric_mode
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.timeout_seconds, self.account_read_recovery = timeout_seconds, json.loads(canonical(RECOVERY))
        self.model, self.effort = MODEL, "low"
        self.schemas = {benchmark: self.endpoint_type._output_schema(benchmark)
                        for benchmark in ("discoverybench", "blade")}
        self.rubric_digest = self.endpoint_type.rubric_digest()
        self.root.mkdir(parents=True, exist_ok=True)
        self.calls_root = self.root / "calls"
        self.calls_root.mkdir(exist_ok=True)
        self.ledger_path = self.root / "ledger.json"
        self.lock_path = self.root / "allocator.lock"
        config = {"schema": "grok-headless-evaluator-port-v1", "provider_kind": self.provider_kind,
                  "request_contract": _REQUEST_SCHEMA, "evaluator_id": evaluator_id,
                  "evaluator_version": evaluator_version, "rubric_mode": rubric_mode,
                  "rubric_digest": self.rubric_digest, "model": MODEL, "reasoning_effort": "low",
                  "timeout_seconds": self.timeout_seconds, "max_retries": 0, "paid_fallback": False,
                  "main_opportunities_per_request": 1, "max_calls": max_calls, "max_tokens": max_tokens,
                  "main_output_cap": _MAIN_OUTPUT_CAP, "observed_main_token_cap": _OBSERVED_MAIN_TOKEN_CAP,
                  "input_byte_cap": _INPUT_BYTE_CAP, "account_read_recovery": self.account_read_recovery,
                  "schemas": self.schemas, "executable": self.executable,
                  "executable_sha256": executable_sha256, "private_home": str(self.private_home),
                  "private_profile_root": str(self.private_profile), "public_cwd_root": str(self.public_cwd),
                  "frozen_files": self.frozen_files}
        if self.native_deployment is not None:
            config.update(native_deployment=self.native_deployment.record.data(),
                          native_deployment_digest=self.native_deployment.digest)
        self._config_record = FrozenRecord.from_dict(config)
        config = self._config_record.data()
        with _exclusive(self.lock_path):
            if self.ledger_path.exists():
                raw = self.ledger_path.read_bytes()
                try:
                    self.ledger = json.loads(raw)
                    if self.ledger.get("config") != config:
                        raise ContractError("existing headless evaluator ledger differs")
                    replay_headless_evaluator_ledger(self, preserve_failure=True)
                except Exception as exc:
                    fault = self.root / "ledger.constructor-fault.json"
                    if not fault.exists():
                        fault.write_bytes(raw)
                    raise ContractError("existing headless evaluator ledger is not replayable") from exc
            else:
                self.ledger = {"config": config, "calls": [], "known_main_tokens": 0, "tokens": 0,
                               "usage_incomplete": False}
                _write(self.ledger_path, self.ledger)

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        _verify_live_config(self)
        _, benchmark, schema, prompt = self._verify_request(request)
        with _exclusive(self.lock_path):
            if json.loads(self.ledger_path.read_text(encoding="utf-8")) != self.ledger:
                raise ContractError("headless evaluator ledger changed by another allocator")
            if self.ledger["usage_incomplete"] or len(self.ledger["calls"]) >= self.max_calls:
                raise ContractError("headless evaluator ledger is closed")
            replay_headless_evaluator_ledger(self)
            if self.ledger["known_main_tokens"] >= self.max_tokens:
                raise ContractError("headless evaluator token allocation is exhausted")
            raw_prompt = prompt.encode("utf-8")
            if len(raw_prompt) > _INPUT_BYTE_CAP:
                raise ContractError("private evaluator prompt exceeds frozen input cap")
            number = len(self.ledger["calls"]) + 1
            directory = self.calls_root / f"{number:04d}-{benchmark}"
            directory.mkdir()
            request_path = directory / "request.private.json"
            request_path.write_bytes(request.encoded.encode("utf-8"))
            private_path = directory / "headless-request.private.json"
            private_path.write_bytes(canonical({"prompt": prompt, "output_schema": schema}).encode("utf-8"))
            row = {"id": number, "benchmark": benchmark, "request_sha256": request.content_hash,
                   "opportunity_id": f"headless-evaluator-{number:04d}-{benchmark}",
                   "request": {"path": str(request_path), "sha256": _sha(request_path.read_bytes())},
                   "private_request": {"path": str(private_path), "sha256": _sha(private_path.read_bytes())},
                   "status": "reserved", "main_opportunity": 1, "known_headless_main_usage": None,
                   "main_dispatch_state": "unknown"}
            self.ledger["calls"].append(row)
            _write(self.ledger_path, self.ledger)
            try:
                home = directory / "native-home"
                home.mkdir()
                shutil.copyfile(self.private_home / "auth.json", home / "auth.json")
                config_path = home / "config.toml"
                config_path.write_bytes(diagnostic_config(_MAIN_OUTPUT_CAP).encode("utf-8"))
                profile = directory / "native-profile"
                cwd = directory / "public-cwd"
                profile.mkdir()
                cwd.mkdir()
                frozen = {**self.frozen_files, str(config_path): _sha(config_path.read_bytes()),
                          str(private_path): row["private_request"]["sha256"]}
                context = _expected_context(self, row)
                row.update(frozen_files=frozen, native_context=context, config_path=str(config_path),
                           private_directory=str(directory / "native"))
                _write(self.ledger_path, self.ledger)
                result = run_headless_diagnostic(executable=self.executable, cwd=str(cwd), private_home=str(home),
                    private_profile=str(profile), private_dir=str(directory / "native"),
                    reservation=str(directory / "native-reservation.json"), frozen_files=frozen, prompt=prompt,
                    schema=schema, main_output_cap=_MAIN_OUTPUT_CAP, observed_main_token_cap=_OBSERVED_MAIN_TOKEN_CAP,
                    input_byte_cap=_INPUT_BYTE_CAP, timeout=self.timeout_seconds, reasoning_effort="low",
                    account_read_recovery=self.account_read_recovery, deployment=self.native_deployment)
                if not isinstance(result, HeadlessResult):
                    raise ContractError("headless evaluator native result differs")
                receipt = result.receipt.data()
                receipt_path = directory / "observer-receipt.private.json"
                receipt_path.write_bytes(result.receipt.encoded.encode("utf-8"))
                inspection = receipt.get("stream_inspection")
                usage = inspection.get("usage") if isinstance(inspection, dict) else None
                if isinstance(usage, dict) and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0:
                    row["known_headless_main_usage"] = usage
                    self.ledger["known_main_tokens"] += usage["total_tokens"]
                    self.ledger["tokens"] += usage["total_tokens"]
                reservation = directory / "native-reservation.json"
                row.update(native_receipt_sha256=_sha(receipt_path.read_bytes()),
                           reservation_sha256=_sha(reservation.read_bytes()),
                           accepted=receipt.get("accepted") is True,
                           main_dispatch_state=("possibly_dispatched" if receipt.get("prompt_process_launched") is True
                                                else "not_dispatched"))
                _write(self.ledger_path, self.ledger)
                binding = _verify_row(self, row, result)
                if not (receipt.get("accepted") is True and result.response is not None
                        and binding.data().get("accepted") is True):
                    raise ContractError("headless evaluator result rejected")
                _validate_schema(schema, result.response.data())
                (directory / "response.private.json").write_bytes(result.response.encoded.encode("utf-8"))
                if self.ledger["known_main_tokens"] > self.max_tokens:
                    raise ContractError("headless evaluator token allocation exceeded")
                row.update(status="succeeded", response_sha256=result.response.content_hash,
                           headless_binding=binding.data())
                _write(self.ledger_path, self.ledger)
                replay_headless_evaluator_ledger(self)
                _verify_live_config(self)
                return result.response
            except Exception as exc:
                row.update(status="unknown_or_failed", error_type=type(exc).__name__)
                self.ledger["usage_incomplete"] = True
                _write(self.ledger_path, self.ledger)
                raise ContractError("headless evaluator request is terminal; do not retry") from exc

    def _verify_request(self, request: FrozenRecord):
        if not isinstance(request, FrozenRecord):
            raise ContractError("headless evaluator accepts immutable requests only")
        body = request.data()
        required = {"schema", "evaluator_id", "evaluator_version", "benchmark", "prompt", "output_schema",
                    "prompt_digest", "schema_digest", "reference_digest", "rubric_digest"}
        if set(body) != required or body.get("schema") != _REQUEST_SCHEMA:
            raise ContractError("unexpected private evaluator request")
        benchmark = body.get("benchmark")
        if (body.get("evaluator_id") != self.evaluator_id or body.get("evaluator_version") != self.evaluator_version
                or benchmark not in self.schemas or not isinstance(body.get("prompt"), str) or not body["prompt"]):
            raise ContractError("private evaluator identity or prompt differs")
        for field in ("prompt_digest", "schema_digest", "reference_digest", "rubric_digest"):
            _digest(body.get(field), field)
        schema = self.schemas[benchmark]
        if (body["output_schema"] != schema or body["schema_digest"] != _hash(schema)
                or body["prompt_digest"] != _hash(body["prompt"]) or body["rubric_digest"] != self.rubric_digest
                or self.endpoint_type.rubric_digest() != self.rubric_digest):
            raise ContractError("private evaluator frozen rubric binding differs")
        self._verify_prompt_template(benchmark, body["prompt"])
        return body, benchmark, schema, _PROMPT_PREFIX + body["prompt"]

    def _verify_prompt_template(self, benchmark: str, prompt: str) -> None:
        if (prompt.count("\nTASK=") != 1 or prompt.count("\nREFERENCE=") != 1
                or prompt.count("\nANONYMOUS_CANDIDATE=") != 1):
            raise ContractError("private evaluator prompt delimiters differ")
        try:
            _, material = prompt.split("\nTASK=", 1)
            task, material = material.split("\nREFERENCE=", 1)
            reference, candidate = material.split("\nANONYMOUS_CANDIDATE=", 1)
            values = tuple(json.loads(value) for value in (task, reference, candidate))
            if any(canonical(value) != source for value, source in zip(values, (task, reference, candidate), strict=True)):
                raise ValueError("noncanonical material")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ContractError("private evaluator material is not canonical") from exc
        rubric = (self.endpoint_type._DISCOVERY_RUBRIC if benchmark == "discoverybench"
                  else self.endpoint_type._BLADE_RUBRIC)
        if prompt != self.endpoint_type._prompt(benchmark, rubric, *values):
            raise ContractError("private evaluator prompt template differs")


def _verify_live_config(port: GrokHeadlessEvaluatorModelPort) -> dict[str, Any]:
    if type(port.timeout_seconds) is not int or not 1 <= port.timeout_seconds <= 240:
        raise ContractError("headless evaluator timeout drifted")
    frozen = port._config_record.data()
    expected = {"provider_kind": port.provider_kind, "request_contract": _REQUEST_SCHEMA,
                "evaluator_id": port.evaluator_id, "evaluator_version": port.evaluator_version,
                "rubric_mode": port.rubric_mode, "rubric_digest": port.rubric_digest, "model": port.model,
                "reasoning_effort": port.effort, "max_calls": port.max_calls, "max_tokens": port.max_tokens,
                "timeout_seconds": port.timeout_seconds, "account_read_recovery": port.account_read_recovery,
                "schemas": port.schemas, "executable": port.executable, "private_home": str(port.private_home),
                "private_profile_root": str(port.private_profile), "public_cwd_root": str(port.public_cwd),
                "frozen_files": port.frozen_files}
    if port.native_deployment is None:
        if "native_deployment" in frozen or "native_deployment_digest" in frozen:
            raise ContractError("legacy headless evaluator deployment drifted")
    else:
        expected.update(native_deployment=port.native_deployment.record.data(),
                        native_deployment_digest=port.native_deployment.digest)
    if any(frozen.get(name) != value for name, value in expected.items()):
        raise ContractError("live headless evaluator configuration drifted")
    if _sha(Path(port.executable).read_bytes()) != frozen["executable_sha256"]:
        raise ContractError("live headless evaluator executable drifted")
    current_sources = (_source_pins(port.rubric_mode) if port.native_deployment is None
                       else _source_pins(port.rubric_mode, port.native_deployment))
    if any(port.frozen_files.get(path) != digest for path, digest in current_sources.items()):
        raise ContractError("live headless evaluator source drifted")
    if port.ledger.get("config") != frozen:
        raise ContractError("headless evaluator ledger configuration drifted")
    return frozen


def _directory(port: GrokHeadlessEvaluatorModelPort, row: Mapping[str, Any]) -> Path:
    return port.calls_root / f"{row['id']:04d}-{row['benchmark']}"


def _expected_context(port: GrokHeadlessEvaluatorModelPort, row: Mapping[str, Any]) -> dict[str, Any]:
    directory = _directory(port, row)
    context = {"executable": port.executable, "cwd": str(directory / "public-cwd"),
            "private_home": str(directory / "native-home"), "private_profile": str(directory / "native-profile"),
            "reasoning_effort": "low", "account_read_recovery": port.account_read_recovery}
    if port.native_deployment is not None:
        context["native_deployment"] = port.native_deployment.record.data()
    return context


def _expected_private(port: GrokHeadlessEvaluatorModelPort, row: Mapping[str, Any]) -> dict[str, Any]:
    directory = _directory(port, row)
    private_path = directory / "headless-request.private.json"
    descriptor = row.get("private_request")
    raw = private_path.read_bytes()
    if descriptor != {"path": str(private_path), "sha256": _sha(raw)}:
        raise ContractError("private evaluator request descriptor differs")
    private = json.loads(raw)
    schema = port.schemas.get(row.get("benchmark"))
    if (raw != canonical(private).encode("utf-8") or set(private) != {"prompt", "output_schema"}
            or private["output_schema"] != schema or not isinstance(private["prompt"], str)
            or not private["prompt"].startswith(_PROMPT_PREFIX)):
        raise ContractError("private evaluator request shape differs")
    request_path = directory / "request.private.json"
    request_raw = request_path.read_bytes()
    if row.get("request") != {"path": str(request_path), "sha256": _sha(request_raw)}:
        raise ContractError("private evaluator frozen request descriptor differs")
    request = FrozenRecord.from_dict(json.loads(request_raw))
    if request_raw != request.encoded.encode("utf-8") or request.content_hash != row.get("request_sha256"):
        raise ContractError("private evaluator frozen request bytes differ")
    _, benchmark, expected_schema, prompt = port._verify_request(request)
    if benchmark != row.get("benchmark") or expected_schema != schema or private["prompt"] != prompt:
        raise ContractError("private evaluator request binding differs")
    return private


def _expected_frozen(port: GrokHeadlessEvaluatorModelPort, row: Mapping[str, Any]) -> dict[str, str]:
    directory = _directory(port, row)
    _expected_private(port, row)
    config_path = directory / "native-home" / "config.toml"
    return {**port.frozen_files, str(config_path): _sha(config_path.read_bytes()),
            str(directory / "headless-request.private.json"): row["private_request"]["sha256"]}


def _verify_row(port: GrokHeadlessEvaluatorModelPort, row: Mapping[str, Any], result: HeadlessResult | None = None) -> FrozenRecord:
    if (not isinstance(row.get("id"), int) or row["id"] < 1 or row.get("benchmark") not in port.schemas
            or row.get("main_opportunity") != 1):
        raise ContractError("malformed headless evaluator row")
    directory = _directory(port, row)
    private = _expected_private(port, row)
    frozen = _expected_frozen(port, row)
    context = _expected_context(port, row)
    if row.get("frozen_files") != frozen or row.get("native_context") != context:
        raise ContractError("headless evaluator native authority differs")
    receipt_path = directory / "observer-receipt.private.json"
    reservation_path = directory / "native-reservation.json"
    if (_sha(receipt_path.read_bytes()) != row.get("native_receipt_sha256")
            or _sha(reservation_path.read_bytes()) != row.get("reservation_sha256")):
        raise ContractError("headless evaluator native artifact hash differs")
    receipt = FrozenRecord.from_dict(json.loads(receipt_path.read_text(encoding="utf-8")))
    response_path = directory / "response.private.json"
    if result is None:
        if receipt.data().get("accepted") is not True:
            raise ContractError("rejected headless response cannot be replayed")
        raw_response = response_path.read_bytes()
        response = FrozenRecord.from_dict(json.loads(raw_response))
        if raw_response != response.encoded.encode("utf-8") or _sha(raw_response) != row.get("response_sha256"):
            raise ContractError("headless evaluator response original bytes differ")
        result = HeadlessResult(receipt, response)
    elif result.receipt != receipt:
        raise ContractError("persisted headless evaluator receipt differs")
    prompt = private["prompt"].encode("utf-8")
    entry = {"opportunity_id": row["opportunity_id"], "private_request": row["private_request"],
             "prompt_sha256": _sha(prompt), "schema_digest": _hash(port.schemas[row["benchmark"]]),
             "input_bytes": len(prompt)}
    spec = {"native_context": context, "reasoning_effort": "low",
            "account_read_recovery": port.account_read_recovery, "main_output_cap": _MAIN_OUTPUT_CAP,
            "observed_main_token_cap": _OBSERVED_MAIN_TOKEN_CAP, "max_input_bytes": _INPUT_BYTE_CAP,
            "timeout_seconds": port.timeout_seconds}
    binding = verify_headless_request_binding(result, entry, directory, spec, frozen,
                                              deployment=port.native_deployment)
    if row.get("known_headless_main_usage") != binding.data().get("usage", {}).get("main"):
        raise ContractError("headless evaluator known MAIN usage differs")
    return binding


def replay_headless_evaluator_ledger(port: GrokHeadlessEvaluatorModelPort, *, preserve_failure: bool = False) -> None:
    try:
        frozen = _verify_live_config(port)
        disk = json.loads(port.ledger_path.read_text(encoding="utf-8"))
        if disk != port.ledger or disk.get("config") != frozen:
            raise ContractError("headless evaluator ledger drifted")
        for path, digest in frozen["frozen_files"].items():
            if _sha(Path(path).read_bytes()) != digest:
                raise ContractError("headless evaluator source pin drifted")
        rows = port.ledger.get("calls")
        if (not isinstance(rows, list) or len(rows) > port.max_calls or port.ledger.get("usage_incomplete")
                or any(row.get("status") != "succeeded" for row in rows)
                or [row.get("id") for row in rows] != list(range(1, len(rows) + 1))):
            raise ContractError("headless evaluator ledger contains unresolved opportunity")
        total = 0
        for row in rows:
            if row.get("opportunity_id") != f"headless-evaluator-{row['id']:04d}-{row['benchmark']}":
                raise ContractError("headless evaluator opportunity allocation differs")
            binding = _verify_row(port, row)
            response = FrozenRecord.from_dict(json.loads((_directory(port, row) / "response.private.json").read_text(encoding="utf-8")))
            if (binding.data() != row.get("headless_binding") or response.content_hash != row.get("response_sha256")
                    or binding.data().get("accepted") is not True):
                raise ContractError("headless evaluator replay binding differs")
            _validate_schema(port.schemas[row["benchmark"]], response.data())
            total += binding.data()["usage"]["main"]["total_tokens"]
        if total != port.ledger.get("known_main_tokens") or total != port.ledger.get("tokens") or total > port.max_tokens:
            raise ContractError("headless evaluator known MAIN accounting differs")
    except Exception as exc:
        if not preserve_failure:
            port.ledger["usage_incomplete"] = True
            port.ledger["terminal_reason"] = "headless_evaluator_provenance_replay_failed"
            _write(port.ledger_path, port.ledger)
        raise ContractError("headless evaluator provenance replay failed; ledger closed") from exc
