"""Scoped CSV measurement authorities for M1 admission qualification.

The two workers deliberately inspect one shared, public TRAIN CSV with
different parsers. Agreement is reproducible descriptive measurement evidence
only; it is neither independent data nor scientific-hypothesis evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from evaluation.modular.combination_scoring import _signed_body
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.admission_combination import AdmissionMaterialVerifier, FrozenAdmissionMaterial, _assessment
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_material import MaterialAuthority
from research_loop.ontology import ContractError


_OPS = {"row_count", "nonempty_count", "decimal_sum"}
_GROUPS = ("csv-reader-aggregate-v2", "csv-dictreader-aggregate-v2")
_WORKERS = {
    _GROUPS[0]: Path(__file__).with_name("csv_reader_measurement_worker.py"),
    _GROUPS[1]: Path(__file__).with_name("csv_dictreader_measurement_worker.py"),
}


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _original_digest(row: object) -> str:
    if not isinstance(row, dict) or set(row) != {"key", "root_material", "content", "subject_bindings"}:
        raise ContractError("CSV measurement must bind one typed original observation")
    return FrozenRecord.from_dict(row).content_hash


def _canonical_decimal_text(value: str) -> bool:
    """A bounded canonical plain decimal without using Decimal arithmetic context."""
    import re
    return len(value) <= 4096 and value not in {"-0", "+0"} and bool(
        re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", value))


@dataclass(frozen=True)
class CsvMeasurementSpec:
    """A frozen aggregate bound to original observation bytes, never model prose."""

    record: FrozenRecord

    def __post_init__(self) -> None:
        if type(self.record) is not FrozenRecord:
            raise ContractError("frozen CSV measurement specification required")
        b = self.record.data()
        if (set(b) != {"schema", "original_key", "original_observation_digest", "operation", "column", "expected"}
                or b["schema"] != "admission-csv-measurement-spec-v2"
                or not isinstance(b["original_key"], str) or not b["original_key"]
                or not _digest(b["original_observation_digest"])
                or b["operation"] not in _OPS
                or (b["operation"] == "row_count") != (b["column"] is None)
                or (b["operation"] != "row_count" and (not isinstance(b["column"], str) or not b["column"].strip()))
                or not isinstance(b["expected"], str) or not b["expected"]):
            raise ContractError("exact CSV measurement specification required")
        if len(self.record.encoded.encode('utf-8')) > 2048:
            raise ContractError('CSV measurement specification exceeds subprocess argument bound')
        if b["operation"] in {"row_count", "nonempty_count"} and not b["expected"].isdigit():
            raise ContractError("CSV count expectation must be an integer string")
        if b["operation"] == "decimal_sum" and not _canonical_decimal_text(b["expected"]):
            raise ContractError("CSV decimal expectation must be canonical and finite")

    @property
    def key(self) -> str:
        return self.record.data()["original_key"]


@dataclass(frozen=True)
class CsvMeasurementDataset:
    """One immutable CSV byte parent and its exact original-bound measurements."""

    csv_path: Path
    specs: Mapping[str, CsvMeasurementSpec]

    def __post_init__(self) -> None:
        path = Path(self.csv_path)
        specs = dict(self.specs)
        if (not path.is_file() or path.is_symlink() or not specs or len(specs) > 32
                or any(type(spec) is not CsvMeasurementSpec for spec in specs.values())
                or set(specs) != {spec.key for spec in specs.values()}):
            raise ContractError("one regular CSV and keyed frozen measurements are required")
        object.__setattr__(self, "csv_path", path.resolve())
        object.__setattr__(self, "specs", specs)

    def binding(self) -> dict:
        return {"csv_sha256": _sha(self.csv_path), "csv_byte_count": self.csv_path.stat().st_size,
                "specifications": {key: spec.record.data() for key, spec in sorted(self.specs.items())}}


def _dataset_for_request(datasets: Mapping[str, CsvMeasurementDataset], request: FrozenRecord) -> tuple[str, CsvMeasurementDataset]:
    task_digest = request.data()["material"]["task_digest"]
    dataset = datasets.get(task_digest)
    if dataset is None:
        raise ContractError("CSV measurement has no dataset for this exact material task")
    return task_digest, dataset


def _validate_dataset_material(dataset: CsvMeasurementDataset, material: FrozenAdmissionMaterial) -> None:
    originals = {row["key"]: row for row in material.data()["originals"]}
    if set(dataset.specs) != set(originals):
        raise ContractError("CSV specifications must cover each exact original once")
    for key, spec in dataset.specs.items():
        b = spec.record.data()
        if (b["original_observation_digest"] != _original_digest(originals[key])
                or originals[key]['content'] != {'measurement': {'operation': b['operation'], 'column': b['column'], 'expected': b['expected']}}):
            raise ContractError("CSV specification is not bound to original observation bytes")


def _worker_results(stdout: bytes, *, dataset: CsvMeasurementDataset, csv_sha256: str, specifications_digest: str) -> dict[str, dict]:
    try:
        batch = FrozenRecord(stdout.decode('utf-8').strip()).data()
    except Exception as exc:
        raise ContractError("CSV worker did not emit one canonical batch result") from exc
    if (set(batch) != {"schema", "csv_sha256", "specifications_digest", "results"}
            or batch["schema"] != "admission-csv-measurement-batch-result-v2"
            or batch["csv_sha256"] != csv_sha256 or batch["specifications_digest"] != specifications_digest
            or not isinstance(batch["results"], dict) or set(batch["results"]) != set(dataset.specs)):
        raise ContractError("CSV worker batch does not bind its exact CSV/specifications")
    expected = {"schema", "csv_sha256", "spec_digest", "operation", "value", "matches_expected"}
    for key, spec in dataset.specs.items():
        result, b = batch["results"][key], spec.record.data()
        if (not isinstance(result, dict) or set(result) != expected or result["schema"] != "admission-csv-measurement-result-v2"
                or result["csv_sha256"] != batch["csv_sha256"] or result["spec_digest"] != spec.record.content_hash
                or result["operation"] != b["operation"] or not isinstance(result["value"], str)
                or type(result["matches_expected"]) is not bool
                or result["matches_expected"] is not (result["value"] == b["expected"])):
            raise ContractError("CSV worker result does not bind its exact specification")
    return batch["results"]


def _unknown_assessments(request: FrozenRecord) -> dict:
    return {phase: {key: {"subject_digest": subject,
                           "state": {"validity": "unknown", "support": "undetermined", "novelty": "unknown", "investment": "repair"},
                           "outcome": "negative", "execution_success": False,
                           "audit": [{"name": "measurement", "executed": False, "passed": False}]}
                    for key, subject in subjects.items()}
            for phase, subjects in request.data()["subjects"].items()}


def _assessments(request: FrozenRecord, executions: list[dict]) -> dict:
    by_key = {row["original_key"]: row for row in executions}
    values = {}
    for phase, subjects in request.data()["subjects"].items():
        values[phase] = {}
        for key, subject in subjects.items():
            execution = by_key[key]
            result = execution["result"]
            passed = execution["outcome"] == "completed" and result is not None and result["matches_expected"] is True
            values[phase][key] = {"subject_digest": subject,
                "state": {"validity": "valid" if passed else "unknown", "support": "undetermined", "novelty": "unknown", "investment": "explore" if passed else "repair"},
                "outcome": "positive" if passed else "negative", "execution_success": execution["outcome"] == "completed",
                "audit": [{"name": "measurement", "executed": execution["outcome"] == "completed", "passed": passed}]}
    return values


class CsvMeasurementAdmissionMaterialVerifier(AdmissionMaterialVerifier):
    """Admission consumer that replays signed qualification and raw CSV workers."""

    def __init__(self, authorities: tuple[MaterialAuthority, MaterialAuthority], *, datasets: Mapping[str, CsvMeasurementDataset], receipt_root: Path):
        super().__init__(authorities)
        data, root = dict(datasets), Path(receipt_root)
        if (not data or any(not _digest(key) or type(value) is not CsvMeasurementDataset for key, value in data.items())
                or root.is_symlink()):
            raise ContractError("regular receipt root and task-keyed CSV datasets are required")
        for worker in _WORKERS.values():
            if not worker.is_file() or worker.is_symlink():
                raise ContractError("two regular pinned CSV worker sources are required")
        self.datasets, self.receipt_root = data, root.resolve()
        manifest = FrozenRecord.from_dict({'schema': 'admission-csv-measurement-receipt-root-v2', 'binding': self.binding().data()})
        manifest_path = self.receipt_root / 'authority-manifest.json'
        if root.exists():
            if (not root.is_dir() or root.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink()
                    or FrozenRecord(manifest_path.read_text(encoding='utf-8')) != manifest):
                raise ContractError('existing CSV receipt root has a different authority manifest')
        else:
            root.mkdir(parents=True, exist_ok=False)
            with manifest_path.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(manifest.encoded)
                stream.flush()
                os.fsync(stream.fileno())

    def binding(self) -> FrozenRecord:
        b = super().binding().data()
        b["csv_measurement"] = {"schema": "admission-csv-measurement-authorities-v2",
            "datasets": {key: value.binding() for key, value in sorted(self.datasets.items())},
            "worker_sources": {group: {"path_name": _WORKERS[group].name, "sha256": _sha(_WORKERS[group])} for group in _GROUPS},
            "receipt_layout": "per-cell-request-authority-v2"}
        return FrozenRecord.from_dict(b)

    def request(self, material, cell_binding):
        request = super().request(material, cell_binding)
        if type(material) is not FrozenAdmissionMaterial:
            raise ContractError("CSV measurements require typed admission material")
        task_digest, dataset = _dataset_for_request(self.datasets, request)
        _validate_dataset_material(dataset, material)
        b = request.data()
        b.update(schema="admission-csv-measurement-request-v2", csv_measurement={"task_digest": task_digest, **dataset.binding()})
        return FrozenRecord.from_dict(b)

    def _receipt_path(self, request: FrozenRecord, authority: MaterialAuthority) -> Path:
        cell_digest = request.data()["cell_binding"]["cell_digest"]
        return self.receipt_root / cell_digest / (authority.authority.authority_id + "-" + request.content_hash + ".json")

    def _response(self, authority, request, response):
        b = _signed_body(response, {authority.authority.authority_id: authority.authority.key}, message="admission qualification")
        required = {"schema", "authority", "request_digest", "material_digest", "identity", "source_group", "verdict", "cost_units", "assessments", "measurement_receipt_digest"}
        if (set(b) != required or b["schema"] != "admission-material-response-v1" or b["request_digest"] != request.content_hash
                or b["material_digest"] != request.data()["material_digest"] or b["identity"] != request.data()["material"]["identity"]
                or b["source_group"] != authority.source_group or b["verdict"] not in {"verified", "rejected", "unknown"}
                or not _digest(b["measurement_receipt_digest"])
                or b["cost_units"] is not None and (type(b["cost_units"]) is not int or not 0 <= b["cost_units"] <= self.cost_limit_per_call)):
            raise ContractError("CSV qualification authority subject or receipt binding drift")
        subjects = request.data()["subjects"]
        if not isinstance(b["assessments"], dict) or set(b["assessments"]) != set(subjects):
            raise ContractError("CSV qualification phases missing")
        for phase, originals in subjects.items():
            if not isinstance(b["assessments"][phase], dict) or set(b["assessments"][phase]) != set(originals):
                raise ContractError("CSV qualification originals missing")
            for key, subject in originals.items():
                _assessment(b["assessments"][phase][key], subject)
        return b

    def _verify_receipt(self, material, path, *, cell_binding):
        digest = super()._verify_receipt(material, path, cell_binding=cell_binding)
        request = self.request(material, cell_binding)
        task_digest, dataset = _dataset_for_request(self.datasets, request)
        if request.data()["csv_measurement"] != {"task_digest": task_digest, **dataset.binding()}:
            raise ContractError("CSV request dataset binding drift")
        sidecar = json.loads(Path(path).read_text(encoding="utf-8"))
        for authority, call in zip(self.authorities, sidecar["calls"], strict=True):
            signed = self._response(authority, request, FrozenRecord.from_dict(call["response"]))
            receipt_path = self._receipt_path(request, authority)
            if not receipt_path.is_file() or receipt_path.is_symlink():
                raise ContractError("per-cell CSV worker receipt missing")
            raw = FrozenRecord(receipt_path.read_text(encoding="utf-8"))
            if raw.content_hash != signed["measurement_receipt_digest"]:
                raise ContractError("signed qualification does not bind raw CSV worker receipt bytes")
            self._verify_raw_receipt(raw.data(), request, authority, dataset)
        return digest

    def _verify_raw_receipt(self, raw: dict, request: FrozenRecord, authority: MaterialAuthority, dataset: CsvMeasurementDataset) -> None:
        required = {"schema", "request_digest", "material_digest", "cell_binding", "authority", "source_group", "csv", "worker", "process", "executions", "cost_units", "cost_unknown"}
        if (set(raw) != required or raw["schema"] != "admission-csv-measurement-process-receipt-v2"
                or raw["request_digest"] != request.content_hash or raw["material_digest"] != request.data()["material_digest"]
                or raw["cell_binding"] != request.data()["cell_binding"] or raw["authority"] != authority.authority.authority_id
                or raw["source_group"] != authority.source_group or raw["csv"] != dataset.binding()
                or raw["csv"] != {key: value for key, value in request.data()["csv_measurement"].items() if key != "task_digest"}
                or raw["cost_units"] != 1 or raw["cost_unknown"] is not False):
            raise ContractError("raw CSV receipt subject, lineage, or cost drift")
        worker, source = raw["worker"], _WORKERS.get(authority.source_group)
        if (source is None or not isinstance(worker, dict) or set(worker) != {"source_name", "source_sha256", "python_executable_sha256"}
                or worker["source_name"] != source.name or worker["source_sha256"] != _sha(source)
                or worker["python_executable_sha256"] != _sha(Path(sys.executable))):
            raise ContractError("CSV worker source or Python executable drift")
        process = raw['process']
        fields = {'command', 'pid', 'started_at_ns', 'finished_at_ns', 'timeout_seconds', 'exit_code', 'timed_out',
                  'stdout_b64', 'stdout_sha256', 'stderr_b64', 'stderr_sha256', 'timeout_partial_stdout_b64',
                  'timeout_partial_stdout_sha256', 'timeout_partial_stderr_b64', 'timeout_partial_stderr_sha256',
                  'outcome', 'error_type', 'return_pins'}
        bundle = FrozenRecord.from_dict({'specifications': [spec.record.data() for _, spec in sorted(dataset.specs.items())]})
        expected_command = [str(Path(sys.executable)), str(source), '--csv', str(dataset.csv_path), '--specs', bundle.encoded]
        expected_pins = {'csv_sha256': raw['csv']['csv_sha256'], 'source_sha256': worker['source_sha256'],
                         'python_executable_sha256': worker['python_executable_sha256'], 'specifications_digest': bundle.content_hash}
        if (not isinstance(process, dict) or set(process) != fields or process['command'] != expected_command
                or type(process['pid']) is not int or process['pid'] <= 0
                or type(process['started_at_ns']) is not int or type(process['finished_at_ns']) is not int
                or process['finished_at_ns'] < process['started_at_ns'] or process['timeout_seconds'] != 20
                or type(process['timed_out']) is not bool or not _digest(process['stdout_sha256']) or not _digest(process['stderr_sha256'])
                or process['return_pins'] != expected_pins):
            raise ContractError('raw CSV worker process receipt fields drift')
        try:
            stdout, stderr = b64decode(process['stdout_b64'], validate=True), b64decode(process['stderr_b64'], validate=True)
            partial_stdout = b64decode(process['timeout_partial_stdout_b64'], validate=True)
            partial_stderr = b64decode(process['timeout_partial_stderr_b64'], validate=True)
        except Exception as exc:
            raise ContractError('raw CSV worker stream encoding drift') from exc
        if (hashlib.sha256(stdout).hexdigest() != process['stdout_sha256'] or hashlib.sha256(stderr).hexdigest() != process['stderr_sha256']
                or hashlib.sha256(partial_stdout).hexdigest() != process['timeout_partial_stdout_sha256']
                or hashlib.sha256(partial_stderr).hexdigest() != process['timeout_partial_stderr_sha256']):
            raise ContractError('raw CSV worker stream bytes drift')
        executions = raw["executions"]
        if not isinstance(executions, list) or len(executions) != len(dataset.specs):
            raise ContractError("raw CSV receipt must retain every original measurement")
        seen = set()
        for execution in executions:
            fields = {"original_key", "original_observation_digest", "spec_digest", "outcome", "result"}
            if not isinstance(execution, dict) or set(execution) != fields or execution["original_key"] in seen:
                raise ContractError("raw CSV execution receipt fields drift")
            seen.add(execution["original_key"])
            spec = dataset.specs.get(execution["original_key"])
            if (spec is None or execution["original_observation_digest"] != spec.record.data()["original_observation_digest"]
                    or execution["spec_digest"] != spec.record.content_hash):
                raise ContractError("raw CSV execution identity or accounting drift")
            if (process['outcome'] != 'completed' or process['timed_out'] or type(process['exit_code']) is not int
                    or process['exit_code'] != 0 or process['error_type'] is not None or execution["outcome"] != "completed"):
                raise ContractError("CSV source failure remains unknown and cannot verify provenance")
        if _worker_results(stdout, dataset=dataset, csv_sha256=raw['csv']['csv_sha256'], specifications_digest=bundle.content_hash) != {row['original_key']: row['result'] for row in executions}:
            raise ContractError("raw CSV worker stdout/result mismatch")


def _run_worker(request: FrozenRecord, dataset: CsvMeasurementDataset, authority: MaterialAuthority) -> tuple[dict, dict, dict, list[dict]]:
    source = _WORKERS[authority.source_group]
    bundle = FrozenRecord.from_dict({'specifications': [spec.record.data() for _, spec in sorted(dataset.specs.items())]})
    launch_csv = dataset.binding()
    launch_worker = {'source_sha256': _sha(source), 'python_executable_sha256': _sha(Path(sys.executable))}
    command = [str(Path(sys.executable)), str(source), '--csv', str(dataset.csv_path), '--specs', bundle.encoded]
    started = time.time_ns()
    stdout = stderr = b''
    partial_stdout = partial_stderr = b''
    exit_code = None
    pid = None
    timed_out = False
    error_type = None
    results = None
    try:
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(__file__).parents[2]) + os.pathsep + environment.get('PYTHONPATH', '')
        proc = subprocess.Popen(command, cwd=str(source.parents[2]), env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid = proc.pid
        try:
            stdout, stderr = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            partial_stdout = exc.output if isinstance(exc.output, bytes) else b''
            partial_stderr = exc.stderr if isinstance(exc.stderr, bytes) else b''
            proc.kill()
            stdout, stderr = proc.communicate()
            error_type = 'TimeoutExpired'
        exit_code = proc.returncode
        if proc.returncode == 0:
            return_csv = dataset.binding()
            return_worker = {'source_sha256': _sha(source), 'python_executable_sha256': _sha(Path(sys.executable))}
            if return_csv != launch_csv or return_worker != launch_worker:
                error_type = 'InputDrift'
            else:
                results = _worker_results(stdout, dataset=dataset, csv_sha256=launch_csv['csv_sha256'], specifications_digest=bundle.content_hash)
        elif error_type is None:
            error_type = 'WorkerExit'
    except Exception as exc:
        error_type = type(exc).__name__
    finished = time.time_ns()
    outcome = 'completed' if results is not None else 'unknown'
    process = {'command': command, 'pid': pid, 'started_at_ns': started, 'finished_at_ns': finished, 'timeout_seconds': 20,
               'exit_code': exit_code, 'timed_out': timed_out, 'stdout_b64': b64encode(stdout).decode('ascii'),
               'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_b64': b64encode(stderr).decode('ascii'),
               'stderr_sha256': hashlib.sha256(stderr).hexdigest(), 'timeout_partial_stdout_b64': b64encode(partial_stdout).decode('ascii'),
               'timeout_partial_stdout_sha256': hashlib.sha256(partial_stdout).hexdigest(), 'timeout_partial_stderr_b64': b64encode(partial_stderr).decode('ascii'),
               'timeout_partial_stderr_sha256': hashlib.sha256(partial_stderr).hexdigest(), 'outcome': outcome, 'error_type': error_type,
               'return_pins': {'csv_sha256': dataset.binding()['csv_sha256'], 'source_sha256': _sha(source),
                   'python_executable_sha256': _sha(Path(sys.executable)), 'specifications_digest': bundle.content_hash}}
    executions = [{'original_key': key, 'original_observation_digest': spec.record.data()['original_observation_digest'],
                   'spec_digest': spec.record.content_hash, 'outcome': outcome,
                   'result': results[key] if results is not None else None}
                  for key, spec in sorted(dataset.specs.items())]
    return launch_csv, launch_worker, process, executions


def build_csv_measurement_admission_verifier(*, authorities: tuple[LinkedExecutionAuthority, LinkedExecutionAuthority],
        datasets: Mapping[str, CsvMeasurementDataset], receipt_root: Path) -> CsvMeasurementAdmissionMaterialVerifier:
    """Build two source-pinned callbacks plus the replaying admission consumer."""
    if (type(authorities) is not tuple or len(authorities) != 2
            or any(type(authority) is not LinkedExecutionAuthority for authority in authorities)):
        raise ContractError("two exact linked CSV worker authorities are required")
    holder: dict[str, CsvMeasurementAdmissionMaterialVerifier] = {}

    def callback(authority: LinkedExecutionAuthority, group: str):
        def verify(request: FrozenRecord) -> FrozenRecord:
            verifier = holder["verifier"]
            if type(request) is not FrozenRecord:
                raise ContractError("CSV worker requires frozen request")
            _, dataset = _dataset_for_request(verifier.datasets, request)
            if request.data()['csv_measurement'] != {'task_digest': request.data()['material']['task_digest'], **dataset.binding()}:
                raise ContractError('CSV worker request no longer binds current CSV/specification bytes')
            material_authority = next(item for item in verifier.authorities if item.authority == authority)
            receipt_path = verifier._receipt_path(request, material_authority)
            if receipt_path.parent.exists() and receipt_path.parent.is_symlink():
                raise ContractError('CSV receipt cell directory must not be a link')
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            if receipt_path.parent.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
                raise ContractError("CSV worker opportunity already used for this exact cell/request/authority")
            launch_csv, launch_worker, process, executions = _run_worker(request, dataset, material_authority)
            raw = FrozenRecord.from_dict({"schema": "admission-csv-measurement-process-receipt-v2", "request_digest": request.content_hash,
                "material_digest": request.data()["material_digest"], "cell_binding": request.data()["cell_binding"], "authority": authority.authority_id,
                "source_group": group, "csv": launch_csv, "worker": {"source_name": _WORKERS[group].name, **launch_worker},
                "process": process, "executions": executions, "cost_units": 1 if process['pid'] is not None else None,
                "cost_unknown": process['pid'] is None})
            with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(raw.encoded)
                stream.flush()
                os.fsync(stream.fileno())
            complete = len(executions) == len(dataset.specs) and all(row["outcome"] == "completed" for row in executions)
            return authority.issue({"schema": "admission-material-response-v1", "request_digest": request.content_hash,
                "material_digest": request.data()["material_digest"], "identity": request.data()["material"]["identity"], "source_group": group,
                "verdict": "verified" if complete else "unknown", "cost_units": 1 if process['pid'] is not None else None,
                "assessments": _assessments(request, executions) if complete else _unknown_assessments(request),
                "measurement_receipt_digest": raw.content_hash})
        return verify

    material_authorities = tuple(MaterialAuthority(authority, group, callback(authority, group))
        for authority, group in zip(authorities, _GROUPS, strict=True))
    verifier = CsvMeasurementAdmissionMaterialVerifier(material_authorities, datasets=datasets, receipt_root=receipt_root)
    holder["verifier"] = verifier
    return verifier
