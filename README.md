# MoretzTrichter

> **AI notice:** This project was developed with AI assistance.

MoretzTrichter is a small HTTP ingestion service for numeric time-series data.
Devices send batches of measurements to the service; it validates them and
writes them to TimescaleDB. Unknown devices and channels are registered
automatically. Grafana or other tools can read the database separately.

## Run

Copy the example environment file, set a strong PostgreSQL password, and make
the password in `DATABASE_URL` match `POSTGRES_PASSWORD`:

```bash
cp .env.example .env
docker compose up -d --build
```

The API is published on `http://<server-ip>:8080`. Change the host-side port
in `compose.yml` if port 8080 is already used.

The Compose stack runs Trichter and TimescaleDB. Database storage and the
generated API token live in named Docker volumes, so they persist across
container replacement. Both services restart automatically unless explicitly
stopped.

## Authentication and checks

All API routes under `/api/v1` require a bearer token. If `API_TOKEN` is not
set, Trichter creates a random token on its first start, stores it in its
persistent state volume with restrictive permissions, and never writes it to
logs. An administrator can retrieve it with:

```bash
docker compose exec trichter cat /var/lib/moretztrichter/api_token
```

Set `API_TOKEN` in `.env` to provide and manage the token yourself. It takes
precedence over the generated token.

`GET /healthz` is unauthenticated and confirms only that the HTTP service is
running. `GET /api/v1/ping` requires a token and verifies database access:

```bash
curl --fail --show-error \
  -H "Authorization: Bearer $(docker compose exec -T trichter cat /var/lib/moretztrichter/api_token)" \
  http://localhost:8080/api/v1/ping
```

## Ingest data

Send `POST /api/v1/ingest` with `Content-Type: application/json` and
`Authorization: Bearer <token>`.

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
    }
  ]
}
```

`batch_id` must be a UUIDv7. Generate it once for a packet and reuse it for
every retry. A series is identified by `device.identifier` and
`channels[].name`; both are required. `device.name` and `channels[].unit` are
optional metadata. Supplying either later updates its stored value.

Samples are `[timestamp, value]` pairs. Timestamps must be RFC 3339 strings
with an explicit offset, usually UTC such as `2026-10-27T09:00:00Z`. Values
may be numbers or `null`; non-finite numbers are stored as `NULL`.

Python 3.14 or newer can generate compatible IDs and timestamps without an
additional dependency:

```python
from datetime import UTC, datetime
from uuid import uuid7


def new_batch_id() -> str:
    return str(uuid7())


def new_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
```

Invalid packets are rejected without writing their measurements. Historical
data is accepted. A timestamp is stored only once per series; later samples
for that timestamp are discarded and logged as warnings. Repeating a complete
packet with the same `batch_id` and content succeeds without inserting data
again. Reusing a batch ID for different content returns `409 Conflict`.

## Responses and retries

Every response includes `X-Request-ID`, which identifies the related server
log entry.

| Result | Meaning | Client action |
| --- | --- | --- |
| `201 Created` | The batch was stored for the first time. | Success |
| `200 OK` with `duplicate: true` | This batch was already stored. | Success |
| Connection error, timeout, or no response | The service could not be reached. | Retry the same packet later. |
| `429` or `5xx` | A temporary failure occurred. | Retry the same packet later. |
| Other `4xx` | The packet was rejected. | Correct it and send a new packet. |

## Security

Compose publishes only the API port; TimescaleDB is reachable only inside the
Docker network. For traffic outside a trusted local network, place the API
behind a TLS-capable reverse proxy. Bearer tokens authenticate requests but do
not encrypt traffic.

## Development

This project uses [uv](https://docs.astral.sh/uv/) and Python 3.14 or newer.

```bash
uv sync
uv run ruff check .
uv run mypy
uv run pytest
```

Database schema changes are SQL migrations in `migrations/`, applied when
Trichter starts. The initial migration creates the TimescaleDB extension,
tables, hypertable, and Grafana read-only role.

## License

Distributed under the [MIT License](LICENSE).
