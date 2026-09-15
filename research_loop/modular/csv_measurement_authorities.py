"""Deterministic, local CSV measurement authorities for admission qualification.

This is an opt-in v2 producer.  It deliberately distinguishes two validator
implementations from the one shared public TRAIN input; it is not evidence of
independent datasets or scientific effect.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from research_loop.ontology import ContractError
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_material import MaterialAuthority
from research_loop.modular.admission_combination import AdmissionMaterialVerifier

_DIGEST = lambda x: isinstance(x, str) and len(x) == 64 and all(c in '0123456789abcdef' for c in x)
_OPS = {'row_count', 'nonempty_count', 'decimal_sum'}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    return format(value.normalize(), 'f') if value else '0'


@dataclass(frozen=True)
class CsvMeasurementSpec:
    """One public, deterministic aggregate.  No causal interpretation is carried."""
    record: FrozenRecord

    def __post_init__(self):
        b = self.record.data()
        if (type(self.record) is not FrozenRecord or set(b) != {'schema', 'original_key', 'operation', 'column', 'expected'}
                or b['schema'] != 'admission-csv-measurement-spec-v1' or not isinstance(b['original_key'], str)
                or b['operation'] not in _OPS or (b['operation'] == 'row_count') != (b['column'] is None)
                or b['operation'] != 'row_count' and (not isinstance(b['column'], str) or not b['column'])
                or not isinstance(b['expected'], str)):
            raise ContractError('exact deterministic CSV measurement specification required')
        if b['operation'] != 'row_count':
            try: Decimal(b['expected'])
            except InvalidOperation as exc: raise ContractError('measurement expected value is not decimal') from exc
        elif not b['expected'].isdigit():
            raise ContractError('row count expected value must be decimal integer')


def _worker_payload(csv_path: Path, spec: CsvMeasurementSpec, implementation: str) -> dict:
    """Independent algorithms share only this exact CSV byte parent."""
    b = spec.record.data(); rows = list(csv.DictReader(csv_path.open('r', encoding='utf-8', newline='')))
    if b['operation'] == 'row_count': value = str(len(rows))
    elif b['operation'] == 'nonempty_count':
        # Implementation B intentionally traverses a generator; its source pin differs.
        cells = (row.get(b['column'], '') for row in rows)
        value = str(sum(1 for cell in cells if cell.strip()))
    else:
        cells = [row.get(b['column'], '').strip() for row in rows]
        try:
            value = _canonical_decimal(sum((Decimal(cell) for cell in cells if cell), Decimal('0')))
        except InvalidOperation as exc: raise ContractError('CSV decimal measurement input is malformed') from exc
    return {'schema': 'admission-csv-measurement-result-v1', 'implementation': implementation,
            'spec_digest': spec.record.content_hash, 'csv_sha256': _sha(csv_path), 'value': value,
            'matches_expected': value == b['expected']}


class DeterministicCsvAdmissionMaterialVerifier(AdmissionMaterialVerifier):
    """v2 wrapper: receipt evidence is required before it emits verified provenance.

    `source_group` remains validator provenance.  `data_lineage` is a separate,
    shared CSV parent and may intentionally be equal for both authorities.
    """
    def __init__(self, authorities: tuple[MaterialAuthority, MaterialAuthority], *, csv_path: Path,
                 csv_sha256: str, specs: Mapping[str, CsvMeasurementSpec], receipt_root: Path):
        super().__init__(authorities)
        self.csv_path = Path(csv_path); self.csv_sha256 = csv_sha256; self.specs = dict(specs); self.receipt_root = Path(receipt_root)
        if (not self.csv_path.is_file() or _sha(self.csv_path) != csv_sha256 or not _DIGEST(csv_sha256)
                or set(self.specs) != {x.record.data()['original_key'] for x in self.specs.values()}):
            raise ContractError('exact shared public TRAIN CSV and keyed specifications required')

    def binding(self):
        b = super().binding().data()
        b.update(schema='admission-csv-measurement-authorities-v2', data_lineage={
            'kind': 'shared_public_train_csv', 'csv_sha256': self.csv_sha256, 'byte_count': self.csv_path.stat().st_size},
            specifications={key: spec.record.data() for key, spec in sorted(self.specs.items())})
        return FrozenRecord.from_dict(b)

    def request(self, material, cell_binding):
        request = super().request(material, cell_binding).data()
        originals = {x['key'] for x in request['material']['originals']}
        if set(self.specs) != originals:
            raise ContractError('each admission original requires exactly one deterministic CSV measurement')
        request.update(schema='admission-csv-measurement-request-v2', data_lineage=self.binding().data()['data_lineage'],
                       specifications={key: spec.record.data() for key, spec in sorted(self.specs.items())})
        return FrozenRecord.from_dict(request)

    def verify_original_measurements(self, material, path, *, cell_binding):
        """Consumer bridge: replays ordinary signed qualification and every raw receipt."""
        self.replay(material, path, cell_binding=cell_binding)
        request = self.request(material, cell_binding)
        for authority in self.authorities:
            receipt = self.receipt_root / (authority.authority.authority_id + '.jsonl')
            if not receipt.is_file(): raise ContractError('deterministic measurement receipt missing')
            rows = [FrozenRecord(line).data() for line in receipt.read_text(encoding='utf-8').splitlines() if line]
            if len(rows) != len(self.specs) or any(row.get('csv_sha256') != self.csv_sha256 for row in rows):
                raise ContractError('deterministic measurement receipt lineage drift')
            for row in rows:
                key = row.get('original_key'); spec = self.specs.get(key)
                if spec is None or row.get('spec_digest') != spec.record.content_hash or row.get('status') != 'completed':
                    raise ContractError('deterministic measurement receipt spec drift')
                if _worker_payload(self.csv_path, spec, authority.source_group) != row.get('result'):
                    raise ContractError('deterministic measurement replay drift')
        return request.content_hash

def build_local_csv_measurement_authorities(authorities: tuple, *, csv_path: Path,
        specs: Mapping[str, CsvMeasurementSpec], receipt_root: Path) -> tuple[MaterialAuthority, MaterialAuthority]:
    """Build two locally executable verification callbacks.

    The caller supplies two `LinkedExecutionAuthority` values. Each callback
    invokes a fresh Python child and writes one immutable JSONL receipt per
    authority. The two groups name implementations, never data sources.
    """
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority
    if (not isinstance(authorities, tuple) or len(authorities) != 2
            or any(type(a) is not LinkedExecutionAuthority for a in authorities)):
        raise ContractError('two exact local measurement execution authorities required')
    groups = ('csv-reader-aggregate-v1', 'csv-dictreader-aggregate-v1')
    if receipt_root.exists(): raise ContractError('measurement receipt root must be unused')
    csv_path = Path(csv_path); csv_digest = _sha(csv_path)
    receipt_root.mkdir(parents=True)

    def callback(authority, group):
        def verify(request):
            body = request.data(); root = receipt_root / (authority.authority_id + '.jsonl')
            if root.exists(): raise ContractError('measurement opportunity already used')
            source = Path(__file__).resolve(); source_digest = _sha(source)
            rows = []
            error = None
            for key, spec in sorted(specs.items()):
                try:
                    # A child is an owned, bounded execution receipt; it never receives labels.
                    proc = subprocess.run([sys.executable, '-c',
                        'from pathlib import Path; from research_loop.modular.csv_measurement_authorities import CsvMeasurementSpec,_worker_payload; import json,sys; s=CsvMeasurementSpec(__import__("research_loop.modular.contracts",fromlist=["FrozenRecord"]).FrozenRecord.from_dict(json.loads(sys.argv[2]))); print(json.dumps(_worker_payload(Path(sys.argv[1]),s,sys.argv[3]),sort_keys=True))',
                        str(csv_path), spec.record.encoded, group], cwd=str(source.parents[2]), text=True,
                        capture_output=True, timeout=20, check=False)
                    if proc.returncode != 0: raise ContractError('owned CSV measurement child failed')
                    result = FrozenRecord.from_dict(json.loads(proc.stdout)).data()
                    if result['csv_sha256'] != csv_digest: raise ContractError('child CSV binding drift')
                    rows.append(FrozenRecord.from_dict({'schema':'admission-csv-measurement-process-receipt-v1',
                        'original_key':key,'spec_digest':spec.record.content_hash,'csv_sha256':csv_digest,
                        'validator_source_sha256':source_digest,'status':'completed','exit_code':proc.returncode,
                        'result':result,'cost_units':0,'cost_unknown':False}).data())
                except Exception as exc:
                    error = exc
                    rows.append(FrozenRecord.from_dict({'schema':'admission-csv-measurement-process-receipt-v1',
                        'original_key':key,'spec_digest':spec.record.content_hash,'csv_sha256':csv_digest,
                        'validator_source_sha256':source_digest,'status':'unknown','exit_code':None,
                        'result':None,'cost_units':None,'cost_unknown':True,'error_type':type(exc).__name__}).data())
                    break
            with root.open('x',encoding='utf-8',newline='\n') as stream:
                for row in rows: stream.write(FrozenRecord.from_dict(row).encoded+'\n')
                stream.flush(); os.fsync(stream.fileno())
            if error is not None: raise error
            assessments = {}
            for phase, subjects in body['subjects'].items():
                assessments[phase] = {}
                for key, subject in subjects.items():
                    outcome = 'positive' if next(x for x in rows if x['original_key']==key)['result']['matches_expected'] else 'negative'
                    assessments[phase][key] = {'subject_digest':subject,
                        'state':{'validity':'valid' if outcome=='positive' else 'unknown','support':'undetermined','novelty':'unknown','investment':'explore'},
                        'outcome':outcome,'execution_success':True,'audit':[{'name':'measurement','executed':True,'passed':outcome=='positive'}]}
            return authority.issue({'schema':'admission-material-response-v1','request_digest':request.content_hash,
                'material_digest':body['material_digest'],'identity':body['material']['identity'],'source_group':group,
                'verdict':'verified','cost_units':0,'assessments':assessments})
        return verify
    return tuple(MaterialAuthority(a, group, callback(a, group)) for a,group in zip(authorities, groups))
