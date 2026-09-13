"""Prospective train reference bridge; frozen contract introduced before implementation."""
from dataclasses import dataclass
from research_loop.ontology import ContractError

@dataclass(frozen=True)
class PrimaryReferenceItem:
    item: object
    task_sha256: str
    public_sha256: str
    csv_sha256: str
    receipt_sha256: str

class PrimaryProspectiveReferenceBridge:
    def __init__(self, *, exporter, export_receipt_sha256, store_root, audit_root, discovery_answer_keys):
        self.exporter = exporter
        self.store_root, self.audit_root = store_root, audit_root
    def prepare(self, requests, packets):
        raise ContractError("prospective train reference bridge is not implemented")
