from unittest.mock import MagicMock

import gws_cli.auth as auth_module
from gws_cli.auth import SCOPES, get_credentials


def test_scopes_include_calendar_and_drive_readonly():
    assert "https://www.googleapis.com/auth/calendar.readonly" in SCOPES
    assert "https://www.googleapis.com/auth/drive.readonly" in SCOPES


def test_get_credentials_calls_google_auth_default_with_scopes(monkeypatch):
    credentials = MagicMock(name="credentials")
    default_mock = MagicMock(return_value=(credentials, "test-project"))
    monkeypatch.setattr(auth_module, "default", default_mock)

    result = get_credentials()

    assert result is credentials
    default_mock.assert_called_once_with(scopes=SCOPES)
