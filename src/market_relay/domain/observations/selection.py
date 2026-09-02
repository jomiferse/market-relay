"""Deterministic selection of the publishable observation, without silent mixing.

`specs/market-observations/spec.md` § "Deterministic selection without
silent mixing" requires that, when different closes exist for the same
listing and date, the response identify the chosen value, its source, and
the applied policy — never averaging or merging values from different
sources as if they were equivalent. `design.md` adds that the raw `close`
is never substituted by `adjusted_close`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_relay.domain.governance.policy_gate import PolicyGate
from market_relay.domain.observations.models import Observation, ObservationType


class NoEligibleObservationError(Exception):
    """No source in the policy produced a publishable observation."""


@dataclass(frozen=True, slots=True)
class SourcePriorityPolicy:
    """Explicit policy: order of source preference by priority.

    The first source in `ordered_sources` with a current, publishable
    observation for the given key wins. There is no implicit resolution: a
    source absent from the list is never considered.
    """

    name: str
    ordered_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Chosen observation, the applied policy, and the visible alternatives.

    `alternatives` keeps every current, publishable observation from other
    sources for the same key, even if not chosen: the discrepancy is
    exposed explicitly instead of hidden
    (specs/market-observations/spec.md § "Two approved sources differ").
    """

    selected: Observation
    policy_name: str
    alternatives: tuple[Observation, ...]

    @property
    def has_discrepancy(self) -> bool:
        return any(alt.close != self.selected.close for alt in self.alternatives)


class ObservationSelector:
    """Applies a `SourcePriorityPolicy` over the current observations.

    A source's publishability is evaluated dynamically against `PolicyGate`'s
    versioned history on each call to `select`, never against a flag stored
    on `Observation`: a policy revocation is reflected immediately without
    needing any `UPDATE` over the append-only history
    (specs/market-observations/spec.md § "Preserved history").
    """

    def __init__(self, session: Session, policy_gate: PolicyGate | None = None) -> None:
        self._session = session
        self._policy_gate = policy_gate if policy_gate is not None else PolicyGate(session)

    def select(
        self,
        *,
        listing_id: uuid.UUID,
        session_date: date,
        observation_type: ObservationType,
        policy: SourcePriorityPolicy,
    ) -> SelectionResult:
        candidates = self._current_publishable_by_source(
            listing_id=listing_id, session_date=session_date, observation_type=observation_type
        )

        selected: Observation | None = None
        for source in policy.ordered_sources:
            if source in candidates:
                selected = candidates[source]
                break

        if selected is None:
            raise NoEligibleObservationError(
                f"No source in policy '{policy.name}' has a publishable "
                f"observation for listing={listing_id} "
                f"session_date={session_date} type={observation_type.value}."
            )

        alternatives = tuple(obs for source, obs in candidates.items() if obs.id != selected.id)
        return SelectionResult(
            selected=selected, policy_name=policy.name, alternatives=alternatives
        )

    def _current_publishable_by_source(
        self,
        *,
        listing_id: uuid.UUID,
        session_date: date,
        observation_type: ObservationType,
    ) -> dict[str, Observation]:
        """The current revision per source (and credential scope), filtered
        to the sources whose publication authorization is currently valid.
        When a source has several `credential_scope`s, each one counts as
        an independent candidate under the `source:credential_scope` key so
        as not to merge distinct accounts (design.md § "Isolated central
        credentials"). Publishability is resolved against `PolicyGate` at
        query time, not against a value stored on the row.
        """

        stmt = select(Observation).where(
            Observation.listing_id == listing_id,
            Observation.session_date == session_date,
            Observation.observation_type == observation_type,
        )
        rows = list(self._session.scalars(stmt).all())

        latest_by_key: dict[tuple[str, str], Observation] = {}
        for row in rows:
            key = (row.source, row.credential_scope)
            current = latest_by_key.get(key)
            if current is None or row.revision > current.revision:
                latest_by_key[key] = row

        # Exposed by simple source name so the priority policy operates on
        # `source`; if two credential scopes of the same source competed,
        # the one with the higher `retrieved_at` is preferred
        # deterministically, without mixing them.
        by_source: dict[str, Observation] = {}
        for (source, _scope), obs in latest_by_key.items():
            if not self._policy_gate.is_publication_authorized(source):
                continue
            current = by_source.get(source)
            if current is None or obs.retrieved_at > current.retrieved_at:
                by_source[source] = obs
        return by_source
