"""DiscoveryBench public-task preparation.

This captures the public context shape used by the historical runner without
opening its task selection, answer-key, judge, or model-running paths.
"""

from __future__ import annotations

from typing import Any, Mapping

from research_loop.modular.contracts import DataIdentity, PublicTask
from research_loop.ontology import ContractError

from ._public import object_only, public_text, reject_private_names


class DiscoveryBenchAdapter:
    benchmark = "discoverybench_synthetic"

    def prepare(self, identity: DataIdentity, metadata: Mapping[str, Any]) -> PublicTask:
        if identity.benchmark != self.benchmark:
            raise ContractError("DiscoveryBench identity benchmark mismatch")
        raw = object_only(metadata, {"task_id", "question", "difficulty", "dataset"}, "DiscoveryBench metadata")
        if raw.get("task_id") != identity.task_id:
            raise ContractError("DiscoveryBench task identity mismatch")
        question = public_text(raw.get("question"), "question")
        difficulty = public_text(raw.get("difficulty"), "difficulty", optional=True)
        datasets = raw.get("dataset")
        if not isinstance(datasets, list) or not datasets:
            raise ContractError("DiscoveryBench dataset must be a nonempty public descriptor list")
        prepared = []
        for dataset in datasets:
            item = object_only(dataset, {"name", "description", "columns"}, "dataset descriptor")
            name = public_text(item.get("name"), "dataset.name")
            description = public_text(item.get("description"), "dataset.description", optional=True)
            columns = item.get("columns", [])
            if not isinstance(columns, list):
                raise ContractError("dataset.columns must be a list")
            public_columns = []
            for column in columns:
                col = object_only(column, {"name", "description"}, "column descriptor")
                public_columns.append({"name": public_text(col.get("name"), "column.name"),
                                       "description": public_text(col.get("description"), "column.description", optional=True)})
            prepared.append({"name": name, "description": description, "columns": public_columns})
        payload = {"task_id": identity.task_id, "question": question, "difficulty": difficulty, "dataset": prepared}
        reject_private_names(payload)
        return PublicTask.create(identity, payload)
