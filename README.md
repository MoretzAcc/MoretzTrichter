# MoretzTrichter

> **AI-generated notice:** This project was primarily generated with AI assistance. Review it before production use.

MoretzTrichter accepts authenticated batches of numeric time-series data over HTTP and stores them in TimescaleDB. Devices create series automatically; Grafana or other tools can read the database separately.

## Deploy

Download [compose.yml](compose.yml) and [.env.example](.env.example), copy the latter to `.env`, set `POSTGRES_PASSWORD`, and update the password in `DATABASE_URL` to the same value. Initialize the database manually, then start Trichter:

```sh
cp .env.example .env
docker compose up -d timescaledb
docker compose run --rm --no-deps trichter moretztrichter-init-db
docker compose up -d trichter
```

Trichter listens on `http://<server>:8080`. The database is not published on a host port.

The first start generates a bearer token and stores it in the persistent `trichter_state` volume:

```sh
docker compose exec trichter cat /var/lib/moretztrichter/api_token
```

Alternatively, set `API_TOKEN` in `.env` to manage the token yourself. After changing it, recreate Trichter with `docker compose up -d --force-recreate trichter`.

## API

`GET /healthz` is an unauthenticated liveness check. `GET /readyz` is an
unauthenticated database-readiness check used by Docker. `GET /api/v1/ping`
also verifies the database connection and requires `Authorization: Bearer <token>`.

Send measurements to `POST /api/v1/ingest` with the same header and `Content-Type: application/json`:

```json
{
  "batch_id": "019a7f6a-85f2-7bc0-8947-2f2bfdc43af3",
  "device": {"identifier": "mac:aa:bb:cc:dd:ee:ff", "name": "weather-station"},
  "channels": [
    {
      "name": "temperature",
      "unit": "°C",
      "samples": [["2026-10-27T12:00:00Z", 21.5], ["2026-10-27T12:00:10Z", null]]
    }
  ]
}
```

Devices running Python 3.14+ can create the required values as follows:

```python
from uuid import uuid7

batch_id = str(uuid7())
```

```python
from datetime import datetime, timezone

timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

`batch_id` must be UUIDv7. Timestamps must be RFC 3339 strings with an explicit offset. A series is identified by `(device.identifier, channel.name)`; optional name and unit metadata update existing metadata when supplied. `null`, `NaN`, and infinite values are stored as SQL `NULL`.

Invalid requests are rejected without writing the batch. Reuse a `batch_id` for retries: an identical normalized batch returns `200`, while a different payload returns `409`. Samples whose series/timestamp already exists are discarded and logged; the remaining samples are stored. Retry connection failures, `429`, and `5xx` responses; correct `4xx` requests before sending them again.

## Update

The Compose file follows the published `ghcr.io/moretzacc/moretztrichter:latest` image:

```sh
docker compose pull trichter
docker compose run --rm --no-deps trichter moretztrichter-init-db
docker compose up -d trichter
```

The GHCR package must be public for anonymous pulls; otherwise authenticate the
server first with `docker login ghcr.io`.

For access outside a trusted LAN, place Trichter behind a TLS-capable reverse
proxy. Bearer tokens do not encrypt traffic.

## License

Released under the [MIT License](LICENSE).
