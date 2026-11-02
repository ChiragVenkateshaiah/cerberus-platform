"""What the commands read. Protocols plus the container that hands them out.

The commands never import boto3; they ask a Sources object for a reader. Tests
pass fakes. The AWS implementations are in aws.py. Phase 10 adds an AMP reader
here without touching the grammar.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Unavailable(Exception):
    """A source cannot answer right now. Never carries a message to the visitor."""


class StepFunctionsReader(Protocol):
    def list_executions(self) -> list[dict]:
        """Newest first: {arn, name, status, start, stop} (ISO strings or None)."""

    def current_state(self, execution_arn: str) -> str | None:
        """The state a RUNNING execution entered last."""

    def execution_detail(self, execution_arn: str) -> dict:
        """{states: [{state, seconds}], failed_state, error}. The cause text is never read."""


class FreshnessReader(Protocol):
    def gold_freshness(self) -> dict:
        """{tables: [{table, last_commit}], bytes_scanned}."""


@dataclass
class Sources:
    runs_dir: Path
    sfn_factory: Callable[[], StepFunctionsReader] | None = None
    freshness_factory: Callable[[], FreshnessReader] | None = None

    def sfn(self) -> StepFunctionsReader:
        if self.sfn_factory is None:
            raise Unavailable
        return self.sfn_factory()

    def freshness(self) -> FreshnessReader:
        if self.freshness_factory is None:
            raise Unavailable
        return self.freshness_factory()
