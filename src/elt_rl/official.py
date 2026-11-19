"""Phase 2 seam for adapting the official benchmark to the same episode contract."""

from pathlib import Path

from .contracts import TaskDefinition


def snowflake_task(benchmark_checkout: Path, task_id: str = "books") -> TaskDefinition:
    """Return the official task and host-side backend/verifier once Phase 2 is implemented.

    The adapter owns secret injection, Airbyte sync, isolated Snowflake namespaces,
    dbt execution, and a fresh private output folder for eva.py on every replay.
    """
    raise NotImplementedError("Official Snowflake/Airbyte rollouts are deferred to Phase 2")
