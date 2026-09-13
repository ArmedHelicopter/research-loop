"""Explicit legacy/prospective TRAIN sources shared by combination controllers."""
from __future__ import annotations

import json

from evaluation.modular.custody import CustodyStore
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
from evaluation.modular.prospective_train_exporter import _concrete
from evaluation.modular.train_io import PublicTrainPacket, TrainPacketExporter
from research_loop.modular.contracts import DataIdentity
from research_loop.ontology import ContractError


PROSPECTIVE = "primary_prospective"


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
            _concrete(packet.csv_path)
        else:
            item = f"{identity.benchmark}:{identity.task_id}"
        if item in by_item:
            raise ContractError("duplicate exported task or token")
        by_item[item] = packet
    if set(by_item) != set(body["item_ids"]):
        raise ContractError("exported packets differ from the frozen source allowlist")
    if len({p.task.identity for p in packets}) != len(packets):
        raise ContractError("different export tokens cannot duplicate one task identity")
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
        return packets
