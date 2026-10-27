CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS series (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_identifier TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    device_name TEXT,
    unit TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_identifier, channel_name)
);

CREATE TABLE IF NOT EXISTS ingest_batch (
    batch_id UUID PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS measurement (
    time TIMESTAMPTZ NOT NULL,
    series_id BIGINT NOT NULL REFERENCES series(id),
    value DOUBLE PRECISION,
    PRIMARY KEY (series_id, time)
);

SELECT create_hypertable('measurement', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS measurement_series_time_desc_idx ON measurement (series_id, time DESC);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        CREATE ROLE grafana_reader NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON series, ingest_batch, measurement TO grafana_reader;
