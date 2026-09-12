"""BLADE public-task preparation, without importing reference analysis paths."""

from __future__ import annotations

from typing import Any, Mapping

from research_loop.modular.contracts import DataIdentity, PublicTask
from research_loop.ontology import ContractError

from ._public import object_only, public_text, reject_private_names


class BladeAdapter:
    benchmark = "blade"

    def prepare(self, identity: DataIdentity, metadata: Mapping[str, Any]) -> PublicTask:
        if identity.benchmark != self.benchmark:
            raise ContractError("BLADE identity benchmark mismatch")
        raw = object_only(metadata, {"task_id", "dataset_id", "research_question", "data_schema", "task_instructions"}, "BLADE metadata")
        if raw.get("task_id") != identity.task_id:
            raise ContractError("BLADE task identity mismatch")
        schema = raw.get("data_schema")
        if not isinstance(schema, list):
            raise ContractError("BLADE data_schema must be a public list")
        fields = []
        for field in schema:
            item = object_only(field, {"name", "description", "dtype"}, "BLADE schema field")
            fields.append({"name": public_text(item.get("name"), "schema.name"),
                           "description": public_text(item.get("description"), "schema.description", optional=True),
                           "dtype": public_text(item.get("dtype"), "schema.dtype", optional=True)})
        payload = {"task_id": identity.task_id,
                   "dataset_id": public_text(raw.get("dataset_id"), "dataset_id"),
                   "research_question": public_text(raw.get("research_question"), "research_question"),
                   "data_schema": fields,
                   "task_instructions": public_text(raw.get("task_instructions"), "task_instructions", optional=True)}
        reject_private_names(payload)
        return PublicTask.create(identity, payload)
