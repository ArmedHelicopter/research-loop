"""Explicit legacy/prospective TRAIN sources shared by combination controllers."""
from __future__ import annotations

import hashlib
import json

from evaluation.modular.custody import CustodyStore
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
from evaluation.modular.prospective_train_exporter import _concrete
from evaluation.modular.train_io import PublicTrainPacket, TrainPacketExporter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, digest


PROSPECTIVE = "primary_prospective"


def _is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _batch_receipt(body, packets):
    if not packets:
        raise ContractError('prospective packet batch is empty')
    roots = {p.packet_path.parent.parent for p in packets}
    if len(roots) != 1:
        raise ContractError('prospective packets belong to different exports')
    root = roots.pop()
    record = FrozenRecord.from_dict(json.loads(_concrete(root/'export-receipt.json').read_bytes()))
    b = record.data()
    fixed = {'schema':'prospective-train-export-receipt-v1', 'public_projection_written':True,
             'typed_public_tasks_available_on_success':True, 'raw_private_payload_returned':False,
             'validation_projection_count':0, 'scientific_execution_qualified':False,
             'legacy_custody_mutated':False, 'model_calls':0, 'network_calls':0, 'known_cost_units':0}
    if (set(b) != set(fixed) | {'split_sha256','audit_sha256','request_sha256','source_receipt_digests','packets','output_root_locator_sha256'}
            or any(type(b[k]) is not type(v) or b[k] != v for k,v in fixed.items())
            or b['output_root_locator_sha256'] != digest(str(root)) or not _is_digest(b['audit_sha256'])):
        raise ContractError('prospective batch receipt contract differs')
    by_token = {p.receipt.data().get('export_token'):p for p in packets}
    if len(by_token) != len(packets) or set(by_token) != set(body['item_ids']):
        raise ContractError('prospective batch token allowlist differs')
    expected = [by_token[token].receipt.data() for token in body['item_ids']]
    sources = {p.task.identity.benchmark for p in packets}
    if (b['packets'] != expected or not isinstance(b['source_receipt_digests'], dict)
            or set(b['source_receipt_digests']) != sources
            or any(not _is_digest(v) for v in b['source_receipt_digests'].values())
            or any(p.task.identity.split_id != b['split_sha256'] for p in packets)):
        raise ContractError('prospective batch differs from original packet receipts')
    request = [{'source':by_token[token].task.identity.benchmark, 'token':token,
                'group_sha256':by_token[token].task.identity.group_id,
                'input_bindings_digest':by_token[token].receipt.data().get('input_bindings_digest')}
               for token in body['item_ids']]
    if digest(request) != b['request_sha256']:
        raise ContractError('prospective batch source request differs')
    return record


def source_schema_matches(body, required, legacy_schema, *, optional=()):
    """A new version selects a new source; v1 does not gain optional flags."""
    fields = set(body) - set(optional)
    legacy = fields == required and body.get("schema") == legacy_schema
    prospective = (fields == required | {"export_mode"}
                   and body.get("schema") == legacy_schema.removesuffix("v1") + "v2"
                   and body.get("export_mode") == PROSPECTIVE)
    return legacy or prospective


def source_item_matches(body, item, identity):
    if body.get("export_mode") == PROSPECTIVE:
        return (isinstance(item, str) and len(item) == 64
                and all(c in "0123456789abcdef" for c in item))
    return item == f"{identity.benchmark}:{identity.task_id}"


def packet_index(body, packets):
    """Bind opaque tokens to complete public identities, never positional order."""
    by_item = {}
    for packet in packets:
        if not isinstance(packet, PublicTrainPacket):
            raise ContractError("typed public train packets required")
        identity = packet.task.identity
        identity.require_train()
        receipt = packet.receipt.data()
        if body.get("export_mode") == PROSPECTIVE:
            fields = {'identity','source_group','official_split','split_digest','csv_sha256','csv_byte_count',
                      'packet_hash','export_token','input_bindings_digest','eligibility_sha256'}
            if identity.benchmark == 'discoverybench': fields.add('source_selector')
            if (set(receipt) != fields or type(receipt.get('csv_byte_count')) is not int
                    or receipt['csv_byte_count'] < 0 or not isinstance(receipt.get('official_split'),str)
                    or not receipt['official_split'] or any(not _is_digest(receipt.get(k))
                        for k in ('csv_sha256','packet_hash','input_bindings_digest','eligibility_sha256'))):
                raise ContractError('prospective packet receipt fields differ')
            item = receipt.get("export_token")
            if (not source_item_matches(body, item, identity)
                    or receipt.get("identity") != identity.data()
                    or receipt.get("source_group") != identity.group_id
                    or receipt.get("split_digest") != identity.split_id):
                raise ContractError("prospective packet token or complete identity differs")
            if (packet.packet_path.name != "public.json" or packet.csv_path.name != "data.csv"
                    or packet.packet_path.parent.name != item or packet.csv_path.parent != packet.packet_path.parent):
                raise ContractError("prospective packet paths differ from token binding")
            if json.loads(_concrete(packet.packet_path).read_bytes()) != {"task": packet.task.data(), "receipt": receipt}:
                raise ContractError("prospective serialized public packet differs")
            if json.loads(_concrete(packet.packet_path.parent/'receipt.json').read_bytes()) != receipt:
                raise ContractError('prospective original packet receipt differs')
            raw = _concrete(packet.csv_path).read_bytes()
            if (len(raw) != receipt['csv_byte_count'] or hashlib.sha256(raw).hexdigest() != receipt['csv_sha256']
                    or packet.task.content_hash != receipt['packet_hash']):
                raise ContractError('prospective packet actual byte binding differs')
        else:
            item = f"{identity.benchmark}:{identity.task_id}"
        if item in by_item:
            raise ContractError("duplicate exported task or token")
        by_item[item] = packet
    if set(by_item) != set(body["item_ids"]):
        raise ContractError("exported packets differ from the frozen source allowlist")
    if len({p.task.identity for p in packets}) != len(packets):
        raise ContractError("different export tokens cannot duplicate one task identity")
    if body.get('export_mode') == PROSPECTIVE:
        _batch_receipt(body, packets)
    return by_item


class CombinationTrainSource:
    """Preflight roots/ports, then export through the original audited broker."""
    def __init__(self, body, *, custody, prospective_exporter, snapshot, exported):
        self.body, self.snapshot, self.exported = body, snapshot, exported
        self.custody, self.prospective_exporter = custody, prospective_exporter
        if body.get("export_mode") == PROSPECTIVE:
            if custody is not None or type(prospective_exporter) is not PrimaryProspectiveTrainExporter:
                raise ContractError("prospective configuration requires exactly its concrete train exporter")
            if (snapshot != _concrete(prospective_exporter.config["snapshot_root"])
                    or exported != prospective_exporter.output_root):
                raise ContractError("prospective exporter roots differ from frozen controller roots")
            identities = [DataIdentity.parse(row["identity"]) for row in body["task_bindings"].values()]
            if any(i.domain != "train" or i.split_id != prospective_exporter.expected_split_digest for i in identities):
                raise ContractError("prospective identities differ from exporter train split")
        else:
            if not isinstance(custody, CustodyStore) or prospective_exporter is not None:
                raise ContractError("legacy configuration requires exactly the legacy custody port")
            train_ids = {f"{i.benchmark}:{i.task_id}": i for i in custody.export_train()}
            if any(item not in train_ids or train_ids[item].data() != body["task_bindings"][item]["identity"]
                   for item in body["item_ids"]):
                raise ContractError("frozen source identity is not in the current custody train allocation")

    def export(self):
        if self.prospective_exporter is None:
            packets = TrainPacketExporter(self.custody, self.snapshot, self.exported).export(self.body["item_ids"])
        else:
            packets = self.prospective_exporter.export_controller_packets(self.body["item_ids"])
            for packet in packets:
                token = packet.receipt.data().get("export_token")
                if (not isinstance(token, str) or packet.packet_path != self.exported / token / "public.json"
                        or packet.csv_path != self.exported / token / "data.csv"):
                    raise ContractError("exporter returned paths outside the frozen token output")
            batch = _batch_receipt(self.body, packets)
            exporter = self.prospective_exporter
            _, audit = exporter._sealed_metadata()
            if (batch.data()['audit_sha256'] != exporter.expected_audit_digest
                    or any(p.receipt.data()['eligibility_sha256'] != exporter.eligibility_sha256
                           or p.receipt.data()['input_bindings_digest'] != digest(audit['input_bindings']) for p in packets)):
                raise ContractError('prospective batch metadata differs from the concrete exporter')
            previous = '0'*64; sequence = 0; last = None
            for line in _concrete(exporter.audit_root/'exports.jsonl').read_bytes().splitlines():
                row = json.loads(line); entry = row.pop('entry_sha256',None)
                if (entry != digest(row) or row.get('sequence') != sequence+1 or row.get('previous_sha256') != previous
                        or row.get('split_sha256') != exporter.expected_split_digest
                        or row.get('audit_sha256') != exporter.expected_audit_digest):
                    raise ContractError('prospective export completion journal differs')
                previous, sequence, last = entry, sequence+1, row
            if (previous != exporter._previous or sequence != exporter._sequence or last is None
                    or last.get('event') != 'export_completed' or last.get('receipt_sha256') != batch.content_hash
                    or last.get('request_sha256') != batch.data()['request_sha256']
                    or last.get('possibly_exposed_tokens') != sorted(self.body['item_ids'])
                    or last.get('source_receipt_digests') != batch.data()['source_receipt_digests']):
                raise ContractError('prospective packets lack the original completed export anchor')
        return packets
