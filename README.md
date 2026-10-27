# MoretzTrichter

> **AI notice:** AI generated this project.

MoretzTrichter receives numeric time series from devices over HTTP and writes
validated data to TimescaleDB. It is the only database writer for devices;
Grafana receives a separate read-only database role. Trichter and TimescaleDB
run together in Docker Compose. Grafana is intentionally not part of this
Compose project.

A device needs no prior registration. Trichter automatically creates the
required time series when it receives the first valid packet.

> Migrating the database used by the previous Rust project is a future task.
> This project does not modify the existing database yet.

## Device protocol

Devices send an HTTP `POST` request to `/api/v1/ingest` with
`Content-Type: application/json` and the `Authorization: Bearer <token>`
header.

```json
{
  "batch_id": "019a8c50-1234-7abc-8def-0123456789ab",
  "device": {
    "identifier": "mac:AA:BB:CC:DD:EE:FF",
    "name": "lab-supply-1"
  },
  "channels": [
    {
      "name": "voltage",
      "unit": "V",
      "samples": [
        ["2026-10-27T09:00:00.123456Z", 12.47],
        ["2026-10-27T09:00:01.123456Z", 12.48]
      ]
    },
    {
      "name": "current",
      "unit": "A",
      "samples": [["2026-10-27T09:00:00.123456Z", 0.31]]
    }
  ]
}
```

`batch_id` is a UUIDv7. A device generates it exactly once per packet and
retains it for every retry. A timestamp is RFC 3339 with an explicit time zone,
normally UTC with `Z`. Each measurement is `[timestamp, value]`.

`device.identifier` and `channels[].name` are required. Together they identify
a time series. `device.name` and `channels[].unit` are optional. When present,
they replace the previously stored metadata of that time series. This permits a
display name or channel description to change without creating a new series.

Historical values may be submitted at any time. A value must be a number or
`null`; `null` is stored as a missing measurement. If a sender supplies the
non-standard JSON values `NaN`, `Infinity`, or `-Infinity` and the parser can
receive them, Trichter also normalizes them to `null`. Senders should use
`null` themselves for maximum compatibility.

### Minimal Python helper for a device

These functions produce a UUIDv7 and a UTC timestamp without extra dependencies
on Python 3.14 or newer:

```python
from datetime import UTC, datetime
from uuid import uuid7


def new_batch_id() -> str:
    return str(uuid7())


def new_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
```

Use `new_batch_id()` once when creating a packet and `new_timestamp()` for each
measurement. On a later retry, a device must reuse the already generated
`batch_id` of its stored packet and must not call `new_batch_id()` again for
that packet.

## Retry and error behavior

A packet is completely validated and then processed in one database
transaction. An invalid packet never creates a partial import.

- No HTTP response, DNS/connection errors, or timeouts: retain the packet and
  retry later with the same `batch_id`.
- `5xx` or `429`: temporary failure. Retry later with the same `batch_id`;
  exponential backoff is recommended.
- `201 Created`: the packet was processed for the first time. The device can
  remove its local copy.
- `200 OK` with `duplicate: true`: the same packet was already successful. The
  device can remove its local copy.
- `4xx`: the packet was explicitly rejected and retrying cannot make it valid.
  Store or report the error locally, do not retry the packet automatically, and
  create a new packet only after correcting the cause. `401` means a missing or
  invalid token; `409` means the same `batch_id` was already used for a
  different payload; `413`, `415`, and `422` describe size, content type, and
  validation errors respectively.

Each time series may contain a timestamp only once. If a new packet contains a
timestamp that is already stored for the same `(device_identifier, channel)`,
Trichter discards that new measurement, writes a warning to the console, and
continues processing the remaining valid values in the packet. The response
contains the number of discarded duplicates. A successful retry of an
identical packet is recognized from `batch_id` and produces no extra warnings.
If a timestamp occurs more than once for one series within one packet, the
first sample in that packet is retained and each later sample is discarded in
the same way, even when its value differs.

Every response has an `X-Request-ID` header. Include it when reporting an API
failure so the corresponding server log entry can be found without logging the
packet contents.

## Access protection and ping

On its first start without a configured token, Trichter generates a random
bearer token and stores it with restrictive file permissions in a persistent
Docker volume. It is never written to logs. An administrator who has forgotten
it can retrieve it over SSH:

```bash
docker compose exec trichter cat /var/lib/moretztrichter/api_token
```

The volume must be retained; `docker compose down -v` would also remove the
token. Centrally managed deployments can instead provide a token through an
environment variable or Docker secret.

Use `GET /api/v1/ping` for a complete authenticated connectivity check. This
route also verifies the database connection:

```bash
curl --fail --show-error \
  -H "Authorization: Bearer $(docker compose exec -T trichter cat /var/lib/moretztrichter/api_token)" \
  http://localhost:8080/api/v1/ping
```

The later Docker health-check route, `/healthz`, remains unauthenticated and
only indicates whether the HTTP process is running.

## Planned data model

`series` contains one row per `(device_identifier, channel_name)` with a
compact internal `BIGINT` ID and optional metadata. `measurement` contains
`time TIMESTAMPTZ`, `series_id BIGINT`, and the nullable value; its primary key
`(series_id, time)` prevents duplicate timestamps. A separate `ingest_batch`
table stores `batch_id` and a normalized payload hash for idempotent retries.

The measurement table will be a Timescale hypertable. Automatic retention and
compression are initially disabled and can be decided later based on actual
data volume.

## Deployment

Copy `.env.example` to `.env`, replace `POSTGRES_PASSWORD` and the matching
password in `DATABASE_URL`, then start the initial deployment with
`docker compose up -d --build`. This Compose project creates a fresh
MoretzTrichter database volume; it does not connect to, inspect, or migrate
the database used by the earlier Rust service.

The initial SQL migration creates the Timescale extension, schema, hypertable,
indexes, and the `grafana_reader` role. It is applied automatically by
Trichter at startup and is recorded in `schema_migration`. The Compose
PostgreSQL owner performs this first setup. Grafana can use a separately
managed login role that is a member of `grafana_reader`; Trichter should remain
the only role granted write access to the application tables.

Keep the named Docker volumes. In particular, `trichter_state` contains the
generated bearer token. To use a centrally managed secret instead, set
`API_TOKEN` in the deployment environment; it takes precedence over the token
file and is never copied into it.
