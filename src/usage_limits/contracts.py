"""Canonical contracts for usage_limits collection and discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from usage_limits.table import ModelAvailability, UsageRow

__all__ = [
    "AvailabilityCollection",
    "AvailabilitySnapshot",
    "OpenRouterTrace",
    "ProviderError",
    "ProviderSnapshot",
    "RegisteredProvider",
    "UsageCollection",
]


class OpenRouterTrace(BaseModel):
    """A unique OpenRouter trace/span for deduplication."""

    model_config = ConfigDict(frozen=True)

    trace_id: str
    span_id: str
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        exclude=True,  # Don't use for hashing/equality in Pydantic V2 frozen models
    )

    def __hash__(self) -> int:
        return hash((self.trace_id, self.span_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OpenRouterTrace):
            return False
        return self.trace_id == other.trace_id and self.span_id == other.span_id


class ProviderError(BaseModel):
    """Normalized provider failure description."""

    type: str
    message: str

    model_config = ConfigDict(frozen=True)


class ProviderSnapshot(BaseModel):
    """Normalized usage snapshot for a single provider."""

    provider: str
    display_name: str
    status: Literal["ok", "error"]
    rows: list[UsageRow] = Field(default_factory=list)
    availability: list[ModelAvailability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[ProviderError] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


class UsageCollection(BaseModel):
    """Top-level payload for structured usage collection."""

    version: str = "1"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    providers: list[ProviderSnapshot]

    model_config = ConfigDict(frozen=True)


class AvailabilitySnapshot(BaseModel):
    """Availability-focused view of a provider snapshot."""

    provider: str
    display_name: str
    status: Literal["ok", "error"]
    availability: list[ModelAvailability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[ProviderError] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_provider_snapshot(cls, snapshot: ProviderSnapshot) -> AvailabilitySnapshot:
        """Drop usage rows and keep the availability contract only."""
        return cls(
            provider=snapshot.provider,
            display_name=snapshot.display_name,
            status=snapshot.status,
            availability=snapshot.availability,
            metadata=snapshot.metadata,
            errors=snapshot.errors,
        )


class AvailabilityCollection(BaseModel):
    """Top-level payload for availability-only collection."""

    version: str = "1"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    providers: list[AvailabilitySnapshot]

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_usage_collection(cls, collection: UsageCollection) -> AvailabilityCollection:
        """Project a usage collection into an availability collection."""
        return cls(
            version=collection.version,
            captured_at=collection.captured_at,
            providers=[
                AvailabilitySnapshot.from_provider_snapshot(snapshot)
                for snapshot in collection.providers
            ],
        )


class RegisteredProvider(BaseModel):
    """Structured provider listing entry."""

    provider: str
    display_name: str
    module: str
    source: Literal["builtin", "entry_point"] = "builtin"

    model_config = ConfigDict(frozen=True)
