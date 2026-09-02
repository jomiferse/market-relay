"""Progress cursor serialized in `Job.cursor`.

`design.md` § "Single scheduler with persistent queue" requires that jobs
include a cursor and retry window, and that no process depend on local
memory to resume work: the cursor persists intact in the `Job` row, not in
the process that executes it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from market_relay.domain.observations.models import ObservationType


class InvalidCursorError(Exception):
    """The text of `Job.cursor` is not a valid recovery cursor."""


@dataclass(frozen=True, slots=True)
class FetchCursor:
    """Everything a worker needs to retrieve a specific range, without
    depending on additional state in memory or in another table.
    """

    external_listing_id: str
    credential_scope: str
    observation_type: ObservationType
    start: date
    end: date

    def serialize(self) -> str:
        payload = asdict(self)
        payload["observation_type"] = self.observation_type.value
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        return json.dumps(payload, sort_keys=True)

    @classmethod
    def parse(cls, raw: str | None) -> FetchCursor:
        if not raw:
            raise InvalidCursorError("The job has no serialized cursor.")
        try:
            payload = json.loads(raw)
            return cls(
                external_listing_id=payload["external_listing_id"],
                credential_scope=payload["credential_scope"],
                observation_type=ObservationType(payload["observation_type"]),
                start=date.fromisoformat(payload["start"]),
                end=date.fromisoformat(payload["end"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidCursorError(f"Malformed job cursor: {exc!r}") from exc
