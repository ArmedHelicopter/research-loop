"""Public benchmark adapters and the restricted execution boundary.

The package deliberately prepares only solver-visible task envelopes.  Scorers,
references, and split allocation remain outside this import path.
"""

from .blade import BladeAdapter
from .discovery import DiscoveryBenchAdapter
from .execution import (
    ArtifactReceipt,
    DockerExecutionBroker,
    ExecutionReceipt,
    ExecutionRequest,
    validate_artifact,
)

__all__ = [
    "ArtifactReceipt",
    "BladeAdapter",
    "DiscoveryBenchAdapter",
    "DockerExecutionBroker",
    "ExecutionReceipt",
    "ExecutionRequest",
    "validate_artifact",
]
