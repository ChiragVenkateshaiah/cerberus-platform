"""What the commands read. Protocols plus the container that hands them out.

The commands never import boto3; they ask a Sources object for a reader. Tests
pass fakes. The AWS implementations are in aws.py. The AMP reader (10.5a) is
called by query name, never with a PromQL string.
"""

from collections.abc import Callable, Iterable
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


class AmpReader(Protocol):
    def query(self, name: str) -> list[dict]:
        """The series of one named query (observability/queries/status.json).

        Each series is {step, execution, value}: step and execution are cleaned
        strings or None, value is a finite float or None (NaN). An empty list
        means AMP answered with no data. An unknown name raises.
        """

    def query_many(self, names: Iterable[str]) -> dict[str, list[dict]]:
        """{name: series} for all names, fetched in parallel.

        Same result as calling `query` for each name: any failure raises
        Unavailable, an unknown name raises.
        """


@dataclass
class Sources:
    runs_dir: Path
    sfn_factory: Callable[[], StepFunctionsReader] | None = None
    freshness_factory: Callable[[], FreshnessReader] | None = None
    amp_factory: Callable[[], AmpReader] | None = None

    def sfn(self) -> StepFunctionsReader:
        if self.sfn_factory is None:
            raise Unavailable
        return self.sfn_factory()

    def freshness(self) -> FreshnessReader:
        if self.freshness_factory is None:
            raise Unavailable
        return self.freshness_factory()

    def amp(self) -> AmpReader:
        if self.amp_factory is None:
            raise Unavailable
        return self.amp_factory()
