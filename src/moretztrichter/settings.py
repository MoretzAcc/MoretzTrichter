from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str | None
    token_file: Path
    max_request_bytes: int

    @classmethod
    def from_environment(cls) -> Settings:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be configured")
        return cls(
            database_url=database_url,
            api_token=os.environ.get("API_TOKEN"),
            token_file=Path(os.environ.get("TOKEN_FILE", "/var/lib/moretztrichter/api_token")),
            max_request_bytes=int(os.environ.get("MAX_REQUEST_BYTES", "1048576")),
        )
