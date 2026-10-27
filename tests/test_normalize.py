from uuid import uuid7

import pytest

from moretztrichter.models import IngestRequest
from moretztrichter.normalize import normalize


def payload(channels: list[dict[str, object]]) -> dict[str, object]:
    return {
        "batch_id": str(uuid7()),
        "device": {"identifier": "device-1", "name": "Meter"},
        "channels": channels,
    }


def test_normalization_is_order_independent_and_nonfinite_values_become_null() -> None:
    first = IngestRequest.model_validate(
        payload(
            [
                {
                    "name": "voltage",
                    "unit": "V",
                    "samples": [["2026-01-01T00:00:01Z", float("nan")]],
                },
                {"name": "current", "samples": [["2026-01-01T00:00:00+00:00", 1.0]]},
            ]
        )
    )
    first_dump = first.model_dump(mode="json")
    second = IngestRequest.model_validate(
        {**first_dump, "channels": list(reversed(first_dump["channels"]))}
    )

    assert normalize(first).payload_hash == normalize(second).payload_hash
    assert normalize(first).samples.to_dicts()[1]["value"] is None


def test_duplicate_timestamp_keeps_first_sample() -> None:
    request = IngestRequest.model_validate(
        payload(
            [
                {
                    "name": "voltage",
                    "samples": [
                        ["2026-01-01T00:00:00Z", 1.0],
                        ["2026-01-01T00:00:00Z", 2.0],
                    ],
                }
            ]
        )
    )
    normalized = normalize(request)
    assert normalized.local_duplicates == 1
    assert normalized.samples.to_dicts()[0]["value"] == 1.0


def test_numeric_strings_are_rejected() -> None:
    with pytest.raises(ValueError):
        IngestRequest.model_validate(
            payload(
                [
                    {
                        "name": "voltage",
                        "samples": [["2026-01-01T00:00:00Z", "1.0"]],
                    }
                ]
            )
        )


@pytest.mark.parametrize("timestamp", [1_700_000_000, 1_700_000_000.0, "2026-01-01 00:00:00Z"])
def test_non_rfc3339_timestamps_are_rejected(timestamp: object) -> None:
    with pytest.raises(ValueError):
        IngestRequest.model_validate(
            payload(
                [
                    {
                        "name": "voltage",
                        "samples": [[timestamp, 1.0]],
                    }
                ]
            )
        )
