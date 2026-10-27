from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import polars as pl

from moretztrichter.models import IngestRequest


@dataclass(frozen=True)
class NormalizedBatch:
    batch_id: UUID
    device_identifier: str
    device_name: str | None
    channels: tuple[tuple[str, str | None], ...]
    samples: pl.DataFrame
    payload_hash: str
    local_duplicates: int


def _time_text(timestamp: datetime) -> str:
    return timestamp.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize(request: IngestRequest) -> NormalizedBatch:
    channel_metadata: dict[str, str | None] = {}
    values: dict[tuple[str, str], float | None] = {}
    local_duplicates = 0
    for channel in request.channels:
        previous_unit = channel_metadata.setdefault(channel.name, channel.unit)
        if previous_unit != channel.unit:
            raise ValueError("a channel must have one unit per request")
        for timestamp, value in channel.samples:
            key = (channel.name, _time_text(timestamp))
            if key in values:
                local_duplicates += 1
            else:
                values[key] = value

    canonical = {
        "device_identifier": request.device.identifier,
        "device_name": request.device.name,
        "channels": sorted((name, unit) for name, unit in channel_metadata.items()),
        "samples": sorted(
            (channel, timestamp, value) for (channel, timestamp), value in values.items()
        ),
    }
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    rows = [
        {"channel": channel, "time": timestamp, "value": value}
        for (channel, timestamp), value in sorted(values.items())
    ]
    samples = pl.DataFrame(
        rows, schema={"channel": pl.String, "time": pl.String, "value": pl.Float64}
    )
    return NormalizedBatch(
        batch_id=request.batch_id,
        device_identifier=request.device.identifier,
        device_name=request.device.name,
        channels=tuple(sorted(channel_metadata.items())),
        samples=samples,
        payload_hash=hashlib.sha256(encoded.encode()).hexdigest(),
        local_duplicates=local_duplicates,
    )
