"""SciCode public-task projection from a custody-filtered record.

The official evaluator keeps every source record in model metadata, including
test cases and ground-truth code.  This adapter accepts only the smaller public
projection defined here; it never accepts a raw Hugging Face record.
"""

from __future__ import annotations

from typing import Any, Mapping

from research_loop.modular.contracts import DataIdentity, PublicTask
from research_loop.ontology import ContractError

from ._public import object_only, public_text, reject_private_names


_STEP_FIELDS = {"step_description_prompt", "function_header", "return_line", "step_background"}


class SciCodeAdapter:
    benchmark = "scicode"

    def prepare(self, identity: DataIdentity, metadata: Mapping[str, Any]) -> PublicTask:
        if identity.benchmark != self.benchmark:
            raise ContractError("SciCode identity benchmark mismatch")
        raw = object_only(metadata, {"problem_id", "sub_steps", "required_dependencies"}, "SciCode public projection")
        if raw.get("problem_id") != identity.task_id:
            raise ContractError("SciCode problem identity mismatch")
        dependencies = public_text(raw.get("required_dependencies"), "required_dependencies")
        source_steps = raw.get("sub_steps")
        if not isinstance(source_steps, list) or not source_steps:
            raise ContractError("SciCode sub_steps must be a nonempty public list")
        steps = []
        for ordinal, source_step in enumerate(source_steps, start=1):
            step = object_only(source_step, _STEP_FIELDS, "SciCode public sub_step")
            steps.append({
                "ordinal": ordinal,
                "prompt": public_text(step.get("step_description_prompt"), "sub_step.step_description_prompt"),
                "function_header": public_text(step.get("function_header"), "sub_step.function_header"),
                "return_line": public_text(step.get("return_line"), "sub_step.return_line"),
                "background": public_text(step.get("step_background"), "sub_step.step_background", optional=True),
            })
        payload = {"problem_id": identity.task_id, "required_dependencies": dependencies, "steps": steps}
        reject_private_names(payload)
        return PublicTask.create(identity, payload)
