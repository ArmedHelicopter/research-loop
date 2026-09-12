"""Closed proposal contract for a traced frontier audit, never task admission."""
from __future__ import annotations

from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError


def validate_frontier(response: FrozenRecord, catalog: FrozenRecord, identity: DataIdentity) -> FrozenRecord:
    body, origins = response.data(), catalog.data()
    if set(body) != {"proposals", "empty_reason", "programme_complete"} or body["programme_complete"] is not False:
        raise ContractError("frontier cannot declare programme completion or add authority fields")
    if not isinstance(body["proposals"], list):
        raise ContractError("frontier proposals must be a list")
    if body["proposals"]:
        if body["empty_reason"] is not None:
            raise ContractError("nonempty frontier cannot claim an empty reason")
    else:
        required_text(body["empty_reason"], "empty frontier explanation")
    proposals, signatures = [], set()
    for row in body["proposals"]:
        if not isinstance(row, dict) or set(row) != {"origin_ref", "kind", "question", "observable", "opposing_predictions"}:
            raise ContractError("frontier proposal needs a source and operational discriminator")
        origin = row["origin_ref"]
        if not isinstance(origin, str) or origin not in origins or row["kind"] != origins[origin]["kind"]:
            raise ContractError("frontier proposal is not bound to an available origin")
        for key in ("question", "observable"):
            required_text(row[key], key)
        predictions = row["opposing_predictions"]
        if not isinstance(predictions, list) or len(predictions) != 2:
            raise ContractError("frontier needs two declared opposing predictions")
        for prediction in predictions:
            required_text(prediction, "opposing prediction")
        if predictions[0].strip() == predictions[1].strip():
            raise ContractError("identical predictions cannot discriminate")
        item = FrozenRecord.from_dict(row)
        if item.content_hash in signatures:
            raise ContractError("duplicate frontier proposal")
        signatures.add(item.content_hash)
        proposals.append({**row, "proposal_digest": item.content_hash})
    return FrozenRecord.from_dict({"schema": "research-frontier-proposals-v1", "identity": identity.data(),
        "catalog_digest": catalog.content_hash, "response_digest": response.content_hash,
        "proposals": proposals, "empty_reason": body["empty_reason"], "programme_complete": False,
        "authority": "proposals_only", "benchmark_admission": False, "queue_admission": False,
        "semantic_novelty_and_discriminability": "requires_independent_review"})
