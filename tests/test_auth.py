from pathlib import Path

import pytest

from moretztrichter.auth import get_or_create_token


def test_generated_token_is_reused_and_private(tmp_path: Path) -> None:
    token_file = tmp_path / "state" / "api_token"
    first = get_or_create_token(None, token_file)
    second = get_or_create_token(None, token_file)

    assert first == second
    assert len(first) >= 32
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_configured_token_has_precedence(tmp_path: Path) -> None:
    assert get_or_create_token(" managed-token ", tmp_path / "api_token") == "managed-token"


def test_empty_token_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="must not be empty"):
        get_or_create_token(" ", tmp_path / "api_token")
