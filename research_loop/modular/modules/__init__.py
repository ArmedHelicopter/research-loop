"""Independently testable research modules with explicit provenance boundaries."""

from .admission import (
    AuditItem,
    EvidenceAdmission,
    EvidenceDisposition,
    ExplorationPermit,
    ExplorationPolicy,
    ScientificState,
)
from .context import ContextBuilder, ContextBundle, ContextCache
from .evidence import ClaimLedger, ClaimRecord, ClaimRevision, EvidenceLedger, EvidenceRecord
from .predictions import HypothesisBranch, OperationalPrediction, PredictionPlan, PredictionRegistry, PredictionUpdate
from .review import ReviewEngine, ReviewRevision, ReviewRole, ReviewScoreReceipt, ReviewSession, ReviewSubmission

__all__ = [
    "AuditItem", "EvidenceAdmission", "EvidenceDisposition", "ExplorationPermit",
    "ExplorationPolicy", "ScientificState", "ContextBuilder", "ContextBundle",
    "ContextCache", "ClaimLedger", "ClaimRecord", "ClaimRevision", "EvidenceLedger",
    "EvidenceRecord",
    "HypothesisBranch", "OperationalPrediction", "PredictionPlan", "PredictionRegistry", "PredictionUpdate",
    "ReviewEngine", "ReviewRevision", "ReviewRole", "ReviewScoreReceipt", "ReviewSession", "ReviewSubmission",
]
