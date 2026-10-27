from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a measurement value must be a number or null")
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


MeasurementValue = Annotated[float | None, BeforeValidator(finite_or_none)]
RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def parse_rfc3339_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not RFC3339_TIMESTAMP.fullmatch(value):
        raise ValueError("sample timestamps must be RFC 3339 strings with an explicit offset")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("sample timestamps must be valid RFC 3339 timestamps") from error


Timestamp = Annotated[datetime, BeforeValidator(parse_rfc3339_timestamp)]


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    identifier: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    samples: list[tuple[Timestamp, MeasurementValue]] = Field(min_length=1, max_length=100_000)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: UUID
    device: Device
    channels: list[Channel] = Field(min_length=1, max_length=256)

    @field_validator("batch_id")
    @classmethod
    def batch_id_must_be_v7(cls, batch_id: UUID) -> UUID:
        if batch_id.version != 7:
            raise ValueError("batch_id must be a UUIDv7")
        return batch_id


class IngestResponse(BaseModel):
    batch_id: UUID
    duplicate: bool
    inserted: int
    discarded_duplicates: int


class PingResponse(BaseModel):
    status: str = "ok"
