"""Persistence layer: declarative base, session, and ORM models.

Importing this package registers all models on `Base.metadata`, which
Alembic needs for autogenerate, and the already hand-written migrations
compare against this state.
"""

from market_relay.db.base import Base
from market_relay.domain.catalog.models import ExternalIdentity, Instrument, Listing
from market_relay.domain.governance.models import SourcePolicyDecision
from market_relay.domain.observations.models import Job, Observation

__all__ = [
    "Base",
    "Instrument",
    "Listing",
    "ExternalIdentity",
    "SourcePolicyDecision",
    "Observation",
    "Job",
]
