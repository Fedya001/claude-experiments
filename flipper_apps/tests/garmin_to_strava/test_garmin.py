import pytest

from apps.garmin_to_strava import garmin


def test_login_without_tokens_or_credentials_explains_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="auth-garmin"):
        garmin.login(tmp_path)
