"""ScienceAgentBench public-task projection from custody-filtered metadata."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from research_loop.modular.contracts import DataIdentity, PublicTask
from research_loop.ontology import ContractError

from ._public import object_only, public_text, reject_private_names


def _safe_output_name(value: Any) -> str:
    name = public_text(value, "output_fname")
    if "\\" in name:
        raise ContractError("output_fname must use a safe relative filename")
    path = PurePosixPath(name)
    if (path.is_absolute() or ".." in path.parts or len(path.parts) != 1 or ":" in name
            or path.name != name or any(ord(char) < 32 for char in name)):
        raise ContractError("output_fname must use a safe relative filename")
    return name


class ScienceAgentBenchAdapter:
    benchmark = "scienceagentbench"

    def prepare(self, identity: DataIdentity, metadata: Mapping[str, Any]) -> PublicTask:
        if identity.benchmark != self.benchmark:
            raise ContractError("ScienceAgentBench identity benchmark mismatch")
        raw = object_only(metadata, {"task_id", "task_inst", "dataset_folder_tree", "dataset_preview", "output_fname", "domain_knowledge"},
                          "ScienceAgentBench public projection")
        if raw.get("task_id") != identity.task_id:
            raise ContractError("ScienceAgentBench task identity mismatch")
        payload = {
            "task_id": identity.task_id,
            "task_instruction": public_text(raw.get("task_inst"), "task_inst"),
            "dataset_layout": public_text(raw.get("dataset_folder_tree"), "dataset_folder_tree"),
            "dataset_preview": public_text(raw.get("dataset_preview"), "dataset_preview"),
            "output_filename": _safe_output_name(raw.get("output_fname")),
            "domain_knowledge": public_text(raw.get("domain_knowledge"), "domain_knowledge", optional=True),
        }
        reject_private_names(payload)
        return PublicTask.create(identity, payload)
