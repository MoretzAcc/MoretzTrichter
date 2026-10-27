from __future__ import annotations

import os
import secrets
import time
from pathlib import Path


def get_or_create_token(configured_token: str | None, token_file: Path) -> str:
    """Use a configured token, or atomically persist a generated local token."""
    if configured_token is not None:
        token = configured_token.strip()
        if not token:
            raise RuntimeError("API_TOKEN must not be empty")
        return token
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if token:
        return token
    if token_file.exists():
        raise RuntimeError("the persisted API token must not be empty") from None

    token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate = secrets.token_urlsafe(32)
    try:
        descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(10):
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
            time.sleep(0.01)
        raise RuntimeError("the persisted API token must not be empty") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(candidate + "\n")
    return candidate
