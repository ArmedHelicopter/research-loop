"""Signed final replay of private evaluator originals without model calls."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Mapping, Sequence

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import verify_signed
from research_loop.ontology import ContractError, canonical, digest


_SCHEMA = "headless-evaluator-closure-v1"
_LINEAGE_SCHEMA = "headless-lineage-evaluator-closure-v1"
_LINEAGE_USAGE_DECLARATION_SCHEMA = "lineage-headless-evaluator-usage-declaration-v1"
_LINEAGE_USAGE_CONTRACT = "grok-headless-lineage-usage-v1"
_HEADLESS_PROVIDER_KIND = "grok-headless-frozen-evaluator-v1"


def _digest(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def descriptor(port) -> dict[str, str]:
    from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort
    if not isinstance(port, GrokHeadlessEvaluatorModelPort):
        raise ContractError("headless evaluator closure requires the typed native port")
    return {"kind": port.provider_kind, "configuration_digest": port._config_record.content_hash}


def _successful_journal(path: Path):
    states: dict[tuple[str, ...], Mapping[str, object]] = {}
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError("empty scorer journal")
        for line in lines:
            row = json.loads(line)
            required = {"schema", "cell_key", "request_id", "request_digest", "status"}
            if not isinstance(row, Mapping) or set(row) not in (required, required | {"receipt"}):
                raise ValueError("invalid scorer journal row")
            if (row.get("schema") != "linked-scorer-process-journal-v1" or not isinstance(row.get("cell_key"), list)
                    or len(row["cell_key"]) != 7 or any(not isinstance(value, str) for value in row["cell_key"])
                    or not isinstance(row.get("request_id"), str) or not row["request_id"]):
                raise ValueError("invalid scorer journal reservation")
            _digest(row.get("request_digest"), "scorer journal request")
            key = tuple(row["cell_key"])
            previous = states.get(key)
            if row.get("status") == "reserved":
                if "receipt" in row or previous is not None:
                    raise ValueError("repeated scorer journal reservation")
                states[key] = row
            elif row.get("status") == "succeeded":
                if previous is None or previous.get("status") != "reserved" or set(row) != required | {"receipt"}:
                    raise ValueError("scorer journal success has no reservation")
                if any(row[name] != previous[name] for name in ("cell_key", "request_id", "request_digest")):
                    raise ValueError("scorer journal success differs from reservation")
                receipt = FrozenRecord.from_dict(row["receipt"])
                rows.append((key, receipt))
                states[key] = row
            elif row.get("status") == "unknown":
                if previous is None or "receipt" in row or set(row) != required:
                    raise ValueError("scorer journal unknown has no reservation")
                if any(row[name] != previous[name] for name in ("cell_key", "request_id", "request_digest")):
                    raise ValueError("scorer journal unknown differs from reservation")
                raise ValueError("scorer journal has unknown reservation")
            else:
                raise ValueError("invalid scorer journal state")
        if any(row.get("status") != "succeeded" for row in states.values()):
            raise ValueError("scorer journal has unresolved reservation")
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ContractError("headless evaluator closure journal is unreadable") from exc
    return rows


def _panel_scope(panel, scored_cells: Sequence[tuple[str, ...]]) -> dict[str, object]:
    """Make partial coverage explicit; a successful prefix is not full coverage."""
    expected = sorted(tuple(cell.key) for cell in panel.cells)
    if len(expected) != len(set(expected)) or any(key not in expected for key in scored_cells):
        raise ContractError("headless evaluator closure cell is outside the frozen panel")
    if len(scored_cells) != len(set(scored_cells)):
        raise ContractError("headless evaluator closure duplicates a scored cell")
    return {"schema": "headless-evaluator-closure-scope-v1",
            "expected_panel_cell_keys": [list(key) for key in expected],
            "scored_cell_keys": [list(key) for key in scored_cells],
            "unscored_cell_count": len(expected) - len(scored_cells)}


def finalize(*, service, panel, journal_path: Path, nonce: str, receipt_digests: Sequence[str]) -> FrozenRecord:
    """Replay every original native call and bind it to the ordered scorer journal."""
    from evaluation.modular.headless_evaluator_model_port import replay_headless_evaluator_ledger
    if not isinstance(nonce, str) or not nonce or not isinstance(receipt_digests, Sequence):
        raise ContractError("headless evaluator closure request is malformed")
    expected = [_digest(value, "closure receipt") for value in receipt_digests]
    port = getattr(service, "headless_evaluator_port", None)
    actual_provider = descriptor(port)
    if getattr(service, "evaluator_provider", None) != actual_provider:
        raise ContractError("headless evaluator service binding drift")
    scorer = service.config.record.data()
    if (scorer.get("evaluator_id") != port.evaluator_id or scorer.get("version") != port.evaluator_version
            or scorer.get("rubric_digest") != port.rubric_digest):
        raise ContractError("headless evaluator scorer configuration drift")
    # This reader performs source/config/reservation/request/stream/account replay.
    replay_headless_evaluator_ledger(port)
    journal = _successful_journal(journal_path)
    ledger_raw = port.ledger_path.read_bytes()
    if json.loads(ledger_raw) != port.ledger:
        raise ContractError("headless evaluator closure ledger changed after replay")
    rows = port.ledger.get("calls")
    if (not isinstance(rows, list) or len(rows) != len(journal) or len(rows) != len(expected)
            or port.ledger.get("usage_incomplete") is not False):
        raise ContractError("headless evaluator closure has omitted or extra calls")
    cells = {cell.key: cell for cell in panel.cells}
    calls = []
    known_tokens = 0
    for native, (cell_key, receipt), receipt_digest in zip(rows, journal, expected, strict=True):
        if not isinstance(native, Mapping) or type(native.get("id")) is not int or native["id"] < 1:
            raise ContractError("headless evaluator closure native row is malformed")
        if receipt.content_hash != receipt_digest:
            raise ContractError("headless evaluator closure receipt order differs")
        signed = verify_signed(receipt, {service._authority.authority_id: service._authority.key},
                               schema="combination-adapted-scored-cell-v1")
        evidence = signed.get("evaluator_evidence")
        cell = cells.get(cell_key)
        request_path = Path(native.get("request", {}).get("path", ""))
        request_raw = request_path.read_bytes()
        request_record = FrozenRecord.from_dict(json.loads(request_raw))
        request = request_record.data()
        directory = request_path.parent
        output_raw = (directory / "response.private.json").read_bytes()
        output = FrozenRecord.from_dict(json.loads(output_raw))
        reservation_raw = (directory / "native-reservation.json").read_bytes()
        native_receipt_raw = (directory / "observer-receipt.private.json").read_bytes()
        usage = native.get("known_headless_main_usage")
        tokens = usage.get("total_tokens") if isinstance(usage, Mapping) else None
        if (native.get("id") != len(calls) + 1
                or native.get("opportunity_id") != f"headless-evaluator-{native.get('id'):04d}-{native.get('benchmark')}"
                or native.get("status") != "succeeded" or native.get("request_sha256") != request_record.content_hash
                or native.get("request") != {"path": str(request_path), "sha256": _sha(request_raw)}
                or native.get("response_sha256") != _sha(output_raw)
                or native.get("reservation_sha256") != _sha(reservation_raw)
                or native.get("native_receipt_sha256") != _sha(native_receipt_raw)
                or not isinstance(tokens, int) or tokens < 0
                or cell is None or signed.get("cell_key") != list(cell_key)
                or signed.get("panel_digest") != panel.digest or signed.get("scorer_digest") != service.config.digest
                or signed.get("scorer_config_digest") != service.config.digest
                or cell.scorer_digest != service.config.digest or signed.get("benchmark") != cell.identity.benchmark
                or request.get("benchmark") != signed.get("benchmark")
                or not isinstance(evidence, Mapping) or evidence.get("evaluator_id") != port.evaluator_id
                or evidence.get("evaluator_version") != port.evaluator_version or evidence.get("rubric_digest") != port.rubric_digest
                or evidence.get("prompt_digest") != request.get("prompt_digest") or evidence.get("schema_digest") != request.get("schema_digest")
                or evidence.get("reference_digest") != request.get("reference_digest") or evidence.get("output_digest") != output.content_hash):
            raise ContractError("headless evaluator closure evidence does not match native call")
        known_tokens += tokens
        calls.append({"id": native["id"], "opportunity_id": native["opportunity_id"], "benchmark": native["benchmark"], "cell_key": list(cell_key), "receipt_digest": receipt_digest,
                      "request_digest": native["request_sha256"], "output_digest": output.content_hash,
                      "prompt_digest": request["prompt_digest"], "schema_digest": request["schema_digest"],
                      "native_receipt_sha256": native["native_receipt_sha256"],
                      "reservation_sha256": native["reservation_sha256"], "known_main_tokens": tokens})
    if known_tokens != port.ledger.get("known_main_tokens"):
        raise ContractError("headless evaluator closure known MAIN accounting differs")
    body = {"schema": _SCHEMA, "nonce": nonce, "status": "eligible", "eligible": True,
            "panel_digest": panel.digest, "scorer_config_digest": service.config.digest,
            "evaluator_provider": actual_provider, "receipt_digests": expected, "calls": calls,
            "scope": _panel_scope(panel, [cell for cell, _ in journal]),
            "ledger_sha256": _sha(ledger_raw), "known_main_tokens": known_tokens,
            "title_tokens": None, "settled_additional_charge_usd": None,
            "unknown_title_usage": True, "all_opportunity_tokens": None, "frozen_files": port.frozen_files}
    return service._authority.issue(body)


def verify_closure(record: FrozenRecord, *, authority_keys: Mapping[str, bytes], panel, config, provider, nonce: str,
                   receipt_digests: Sequence[str]) -> FrozenRecord:
    body = verify_signed(record, authority_keys, schema=_SCHEMA)
    expected = [_digest(value, "closure receipt") for value in receipt_digests]
    required = {"schema", "authority", "nonce", "status", "eligible", "panel_digest", "scorer_config_digest",
                "evaluator_provider", "receipt_digests", "calls", "scope", "ledger_sha256", "known_main_tokens",
                "title_tokens", "settled_additional_charge_usd", "unknown_title_usage", "all_opportunity_tokens", "frozen_files"}
    if (set(body) != required or body["nonce"] != nonce or body["status"] != "eligible" or body["eligible"] is not True
            or body["panel_digest"] != panel.digest or body["scorer_config_digest"] != config.digest
            or body["evaluator_provider"] != provider or body["receipt_digests"] != expected
            or not isinstance(body["calls"], list) or len(body["calls"]) != len(expected)
            or not isinstance(body["scope"], Mapping) or _digest(body["ledger_sha256"], "ledger sha256") != body["ledger_sha256"]
            or type(body["known_main_tokens"]) is not int or body["known_main_tokens"] < 0
            or body["title_tokens"] is not None or body["settled_additional_charge_usd"] is not None
            or body["unknown_title_usage"] is not True or body["all_opportunity_tokens"] is not None
            or not isinstance(body["frozen_files"], Mapping)):
        raise ContractError("headless evaluator closure binding differs")
    expected_cells = sorted(tuple(cell.key) for cell in panel.cells)
    scope = body["scope"]
    scored = [tuple(value) for value in scope.get("scored_cell_keys", ())] if isinstance(scope.get("scored_cell_keys"), list) else None
    if (set(scope) != {"schema", "expected_panel_cell_keys", "scored_cell_keys", "unscored_cell_count"}
            or scope.get("schema") != "headless-evaluator-closure-scope-v1"
            or scope.get("expected_panel_cell_keys") != [list(key) for key in expected_cells]
            or scored is None or len(scored) != len(expected) or len(scored) != len(set(scored))
            or any(key not in expected_cells for key in scored)
            or scope.get("unscored_cell_count") != len(expected_cells) - len(scored)):
        raise ContractError("headless evaluator closure scope differs")
    total = 0
    for index, (call, digest) in enumerate(zip(body["calls"], expected, strict=True), start=1):
        if (not isinstance(call, Mapping) or set(call) != {"id", "opportunity_id", "benchmark", "cell_key", "receipt_digest",
                "request_digest", "output_digest", "prompt_digest", "schema_digest", "native_receipt_sha256",
                "reservation_sha256", "known_main_tokens"}
                or call.get("id") != index
                or call.get("receipt_digest") != digest):
            raise ContractError("headless evaluator closure call order differs")
        for field in ("request_digest", "output_digest", "prompt_digest", "schema_digest", "native_receipt_sha256", "reservation_sha256"):
            _digest(call.get(field), field)
        if (call.get("cell_key") != list(scored[index - 1]) or call.get("benchmark") not in {"blade", "discoverybench"}
                or call.get("opportunity_id") != f"headless-evaluator-{call['id']:04d}-{call['benchmark']}"):
            raise ContractError("headless evaluator closure native call binding differs")
        if type(call.get("known_main_tokens")) is not int or call["known_main_tokens"] < 0:
            raise ContractError("headless evaluator closure call usage differs")
        total += call["known_main_tokens"]
    if total != body["known_main_tokens"]:
        raise ContractError("headless evaluator closure known MAIN total differs")
    return FrozenRecord.from_dict(body)


def _lineage_declaration(service, port) -> tuple[dict[str, object], dict[str, str]]:
    """Bind lineage's public declaration to the private, replayable port."""
    binding = getattr(service, "lineage_reference_binding", None)
    declaration = binding.get("evaluator_usage") if isinstance(binding, Mapping) else None
    provider = descriptor(port)
    required = {"schema", "provider_kind", "usage_contract", "evaluator_config_digest"}
    if (not isinstance(declaration, Mapping) or set(declaration) != required
            or declaration.get("schema") != _LINEAGE_USAGE_DECLARATION_SCHEMA
            or declaration.get("provider_kind") != _HEADLESS_PROVIDER_KIND
            or declaration.get("usage_contract") != _LINEAGE_USAGE_CONTRACT):
        raise ContractError("lineage headless evaluator declaration differs")
    _digest(declaration.get("evaluator_config_digest"), "lineage evaluator declaration")
    frozen_declaration = getattr(service, "lineage_evaluator_declaration", None)
    if (not isinstance(frozen_declaration, FrozenRecord)
            or frozen_declaration.content_hash != declaration["evaluator_config_digest"]
            or getattr(service, "evaluator_provider", None) != provider
            or getattr(service, "evaluator_port", None) is not port
            or getattr(service, "headless_evaluator_port", None) is not port):
        raise ContractError("lineage evaluator descriptor/configuration drift")
    return dict(declaration), provider


def _lineage_scope(panel, scored_cells: Sequence[tuple[str, ...]]) -> dict[str, object]:
    scope = _panel_scope(panel, scored_cells)
    return {**scope, "schema": "headless-lineage-evaluator-closure-scope-v1"}


def finalize_lineage(*, service, panel, journal_path: Path, nonce: str,
                     receipt_digests: Sequence[str]) -> FrozenRecord:
    """Replay lineage's one native rubric call for every signed scorer receipt."""
    from evaluation.modular.headless_evaluator_model_port import replay_headless_evaluator_ledger
    if not isinstance(nonce, str) or not nonce or not isinstance(receipt_digests, Sequence):
        raise ContractError("lineage headless evaluator closure request is malformed")
    expected = [_digest(value, "lineage closure receipt") for value in receipt_digests]
    port = getattr(service, "headless_evaluator_port", None)
    declaration, provider = _lineage_declaration(service, port)
    scorer = service.config.record.data()
    if (scorer.get("evaluator_id") != port.evaluator_id or scorer.get("version") != port.evaluator_version
            or scorer.get("rubric_digest") != port.rubric_digest or port.rubric_mode != "lineage_v1"):
        raise ContractError("lineage headless evaluator scorer configuration drift")
    replay_headless_evaluator_ledger(port)
    journal = _successful_journal(journal_path)
    ledger_raw = port.ledger_path.read_bytes()
    if json.loads(ledger_raw) != port.ledger:
        raise ContractError("lineage headless evaluator closure ledger changed after replay")
    rows = port.ledger.get("calls")
    if (not isinstance(rows, list) or len(rows) != len(journal) or len(rows) != len(expected)
            or port.ledger.get("usage_incomplete") is not False):
        raise ContractError("lineage headless evaluator closure has omitted or extra calls")
    cells = {cell.key: cell for cell in panel.cells}
    calls = []
    known_tokens = 0
    endpoint_names = {"root_attribution", "withdrawal_awareness", "context_currency", "review_responsiveness"}
    for native, (cell_key, receipt), receipt_digest in zip(rows, journal, expected, strict=True):
        if not isinstance(native, Mapping) or type(native.get("id")) is not int or native["id"] < 1:
            raise ContractError("lineage headless evaluator closure native row is malformed")
        if receipt.content_hash != receipt_digest:
            raise ContractError("lineage headless evaluator closure receipt order differs")
        signed = verify_signed(receipt, {service._authority.authority_id: service._authority.key},
                               schema="lineage-combination-scored-cell-v1")
        primary_record = FrozenRecord.from_dict(signed.get("primary"))
        primary = verify_signed(primary_record, {service._authority.authority_id: service._authority.key},
                                schema="combination-adapted-scored-cell-v1")
        response = FrozenRecord.from_dict(signed.get("rubric_response"))
        response_data = response.data()
        endpoints = signed.get("endpoints")
        cell = cells.get(cell_key)
        references = service.lineage_reference_binding.get("references") if isinstance(
            getattr(service, "lineage_reference_binding", None), Mapping) else None
        expected_lineage_reference = references.get(digest(cell.identity.data())) if isinstance(references, Mapping) and cell else None
        request_path = Path(native.get("request", {}).get("path", ""))
        request_raw = request_path.read_bytes()
        request_record = FrozenRecord.from_dict(json.loads(request_raw))
        request = request_record.data()
        directory = request_path.parent
        output_raw = (directory / "response.private.json").read_bytes()
        output = FrozenRecord.from_dict(json.loads(output_raw))
        reservation_raw = (directory / "native-reservation.json").read_bytes()
        native_receipt_raw = (directory / "observer-receipt.private.json").read_bytes()
        usage = native.get("known_headless_main_usage")
        tokens = usage.get("total_tokens") if isinstance(usage, Mapping) else None
        if (set(signed) != {"schema", "authority", "primary", "source_digest", "public_context_digest", "endpoints",
                           "rubric_response_digest", "rubric_response", "scorer_digest", "metric", "runtime_trace_digest"}
                or set(primary) != {"schema", "authority", "cell_key", "panel_digest", "design_digest", "obligation_id",
                                    "scorer_digest", "scorer_config_digest", "benchmark", "combination_input_digest",
                                    "runtime_trace_digest", "runtime_output_digest", "joint_mechanism_digest", "solver_trace_digest",
                                    "candidate_digest", "metric", "dimensions", "evaluator_evidence", "scientific_validity", "calibration"}
                or native.get("id") != len(calls) + 1
                or native.get("opportunity_id") != f"headless-evaluator-{native.get('id'):04d}-{native.get('benchmark')}"
                or native.get("status") != "succeeded" or native.get("request_sha256") != request_record.content_hash
                or native.get("request") != {"path": str(request_path), "sha256": _sha(request_raw)}
                or native.get("response_sha256") != _sha(output_raw)
                or native.get("reservation_sha256") != _sha(reservation_raw)
                or native.get("native_receipt_sha256") != _sha(native_receipt_raw)
                or not isinstance(tokens, int) or tokens < 0 or cell is None or cell.scorer_digest != service.config.digest
                or primary.get("cell_key") != list(cell_key) or primary.get("panel_digest") != panel.digest
                or primary.get("scorer_digest") != service.config.digest or primary.get("scorer_config_digest") != service.config.digest
                or primary.get("benchmark") != cell.identity.benchmark or signed.get("scorer_digest") != service.config.digest
                or signed.get("metric") != primary.get("metric") or signed.get("runtime_trace_digest") != primary.get("runtime_trace_digest")
                or not isinstance(endpoints, Mapping) or set(endpoints) != endpoint_names
                or response.content_hash != signed.get("rubric_response_digest")
                or response_data.get("lineage_endpoints") != endpoints
                or output.data().get("lineage_endpoints") != endpoints
                or response_data.get("evidence") != primary.get("evaluator_evidence")
                or not isinstance(response_data.get("lineage_reference_digest"), str)
                or response_data["lineage_reference_digest"] != expected_lineage_reference):
            raise ContractError("lineage closure receipt does not bind the native rubric opportunity")
        evidence = primary["evaluator_evidence"]
        if (not isinstance(evidence, Mapping) or evidence.get("evaluator_id") != port.evaluator_id
                or evidence.get("evaluator_version") != port.evaluator_version or evidence.get("rubric_digest") != port.rubric_digest
                or evidence.get("prompt_digest") != request.get("prompt_digest") or evidence.get("schema_digest") != request.get("schema_digest")
                or evidence.get("reference_digest") != request.get("reference_digest") or evidence.get("output_digest") != output.content_hash):
            raise ContractError("lineage closure evidence does not match native call")
        from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint
        if (response_data.get("dimensions") != FrozenLineageRubricEndpoint._parse(native["benchmark"], output.data())
                or primary.get("dimensions") != response_data.get("dimensions")):
            raise ContractError("lineage closure endpoint response does not derive from native output")
        known_tokens += tokens
        calls.append({"id": native["id"], "opportunity_id": native["opportunity_id"], "benchmark": native["benchmark"],
                      "cell_key": list(cell_key), "lineage_receipt_digest": receipt_digest,
                      "primary_receipt_digest": primary_record.content_hash, "source_digest": signed["source_digest"],
                      "lineage_reference_digest": response_data["lineage_reference_digest"], "endpoints_digest": _sha(canonical(dict(endpoints)).encode("utf-8")),
                      "request_digest": native["request_sha256"], "output_digest": output.content_hash,
                      "prompt_digest": request["prompt_digest"], "schema_digest": request["schema_digest"],
                      "native_receipt_sha256": native["native_receipt_sha256"], "reservation_sha256": native["reservation_sha256"],
                      "known_main_tokens": tokens})
    if known_tokens != port.ledger.get("known_main_tokens"):
        raise ContractError("lineage closure known MAIN accounting differs")
    body = {"schema": _LINEAGE_SCHEMA, "nonce": nonce, "status": "eligible", "eligible": True,
            "panel_digest": panel.digest, "scorer_config_digest": service.config.digest, "evaluator_provider": provider,
            "evaluator_usage_declaration": declaration, "lineage_reference_binding": service.lineage_reference_binding,
            "receipt_digests": expected, "calls": calls, "scope": _lineage_scope(panel, [cell for cell, _ in journal]),
            "ledger_sha256": _sha(ledger_raw), "known_main_tokens": known_tokens, "title_tokens": None,
            "settled_additional_charge_usd": None, "unknown_title_usage": True, "all_opportunity_tokens": None,
            "frozen_files": port.frozen_files}
    return service._authority.issue(body)


def verify_lineage_closure(record: FrozenRecord, *, authority_keys: Mapping[str, bytes], panel, config, provider,
                           reference_binding: Mapping[str, object], nonce: str, receipt_digests: Sequence[str]) -> FrozenRecord:
    body = verify_signed(record, authority_keys, schema=_LINEAGE_SCHEMA)
    expected = [_digest(value, "lineage closure receipt") for value in receipt_digests]
    declaration = reference_binding.get("evaluator_usage") if isinstance(reference_binding, Mapping) else None
    required = {"schema", "authority", "nonce", "status", "eligible", "panel_digest", "scorer_config_digest",
                "evaluator_provider", "evaluator_usage_declaration", "lineage_reference_binding", "receipt_digests",
                "calls", "scope", "ledger_sha256", "known_main_tokens", "title_tokens", "settled_additional_charge_usd",
                "unknown_title_usage", "all_opportunity_tokens", "frozen_files"}
    if (set(body) != required or body["nonce"] != nonce or body["status"] != "eligible" or body["eligible"] is not True
            or body["panel_digest"] != panel.digest or body["scorer_config_digest"] != config.digest
            or body["evaluator_provider"] != provider or body["evaluator_usage_declaration"] != declaration
            or body["lineage_reference_binding"] != reference_binding or body["receipt_digests"] != expected
            or not isinstance(body["calls"], list) or len(body["calls"]) != len(expected)
            or not isinstance(body["scope"], Mapping) or _digest(body["ledger_sha256"], "lineage ledger sha256") != body["ledger_sha256"]
            or type(body["known_main_tokens"]) is not int or body["known_main_tokens"] < 0
            or body["title_tokens"] is not None or body["settled_additional_charge_usd"] is not None
            or body["unknown_title_usage"] is not True or body["all_opportunity_tokens"] is not None
            or not isinstance(body["frozen_files"], Mapping)):
        raise ContractError("lineage headless closure binding differs")
    expected_cells = sorted(tuple(cell.key) for cell in panel.cells)
    scope = body["scope"]
    scored = [tuple(value) for value in scope.get("scored_cell_keys", ())] if isinstance(scope.get("scored_cell_keys"), list) else None
    if (set(scope) != {"schema", "expected_panel_cell_keys", "scored_cell_keys", "unscored_cell_count"}
            or scope.get("schema") != "headless-lineage-evaluator-closure-scope-v1"
            or scope.get("expected_panel_cell_keys") != [list(key) for key in expected_cells]
            or scored is None or len(scored) != len(expected) or len(scored) != len(set(scored))
            or any(key not in expected_cells for key in scored)
            or scope.get("unscored_cell_count") != len(expected_cells) - len(scored)):
        raise ContractError("lineage headless closure scope differs")
    total = 0
    call_fields = {"id", "opportunity_id", "benchmark", "cell_key", "lineage_receipt_digest", "primary_receipt_digest",
                   "source_digest", "lineage_reference_digest", "endpoints_digest", "request_digest", "output_digest",
                   "prompt_digest", "schema_digest", "native_receipt_sha256", "reservation_sha256", "known_main_tokens"}
    for index, (call, receipt_digest) in enumerate(zip(body["calls"], expected, strict=True), start=1):
        if (not isinstance(call, Mapping) or set(call) != call_fields or call.get("id") != index
                or call.get("lineage_receipt_digest") != receipt_digest or call.get("cell_key") != list(scored[index - 1])
                or call.get("benchmark") not in {"blade", "discoverybench"}
                or call.get("opportunity_id") != f"headless-evaluator-{index:04d}-{call['benchmark']}"):
            raise ContractError("lineage headless closure call order differs")
        for field in ("primary_receipt_digest", "source_digest", "lineage_reference_digest", "endpoints_digest", "request_digest",
                      "output_digest", "prompt_digest", "schema_digest", "native_receipt_sha256", "reservation_sha256"):
            _digest(call.get(field), field)
        if type(call.get("known_main_tokens")) is not int or call["known_main_tokens"] < 0:
            raise ContractError("lineage headless closure call usage differs")
        total += call["known_main_tokens"]
    if total != body["known_main_tokens"]:
        raise ContractError("lineage headless closure known MAIN total differs")
    return FrozenRecord.from_dict(body)
