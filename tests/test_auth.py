from unittest.mock import MagicMock

import gws_cli.auth as auth_module
from gws_cli.auth import (
    CALENDAR_SCOPES,
    DRIVE_READ_SCOPES,
    DRIVE_UPLOAD_SCOPES,
    SCOPES,
    build_calendar_service,
    build_drive_service,
    build_drive_upload_service,
    get_credentials,
)


def test_scopes_include_calendar_and_drive_readonly():
    assert "https://www.googleapis.com/auth/calendar.readonly" in SCOPES
    assert "https://www.googleapis.com/auth/drive.readonly" in SCOPES


def test_scopes_include_drive_file_for_upload():
    assert "https://www.googleapis.com/auth/drive.file" in SCOPES


def test_calendar_scopes_are_limited_to_calendar_readonly():
    assert CALENDAR_SCOPES == ["https://www.googleapis.com/auth/calendar.readonly"]


def test_drive_read_scopes_are_limited_to_drive_readonly():
    assert DRIVE_READ_SCOPES == ["https://www.googleapis.com/auth/drive.readonly"]


def test_drive_upload_scopes_pair_readonly_and_file():
    assert set(DRIVE_UPLOAD_SCOPES) == {
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    }


def test_drive_upload_scopes_do_not_include_calendar():
    assert "https://www.googleapis.com/auth/calendar.readonly" not in (
        DRIVE_UPLOAD_SCOPES
    )


def test_get_credentials_calls_google_auth_default_with_scopes(monkeypatch):
    credentials = MagicMock(name="credentials")
    default_mock = MagicMock(return_value=(credentials, "test-project"))
    monkeypatch.setattr(auth_module, "default", default_mock)

    result = get_credentials()

    assert result is credentials
    default_mock.assert_called_once_with(scopes=SCOPES)


def test_get_credentials_accepts_explicit_scope_list(monkeypatch):
    credentials = MagicMock(name="credentials")
    default_mock = MagicMock(return_value=(credentials, "p"))
    monkeypatch.setattr(auth_module, "default", default_mock)

    custom = ["https://www.googleapis.com/auth/only.scope"]
    result = get_credentials(custom)

    assert result is credentials
    default_mock.assert_called_once_with(scopes=custom)


def _patch_auth_builders(monkeypatch):
    credentials = MagicMock(name="credentials")
    default_mock = MagicMock(return_value=(credentials, "p"))
    build_mock = MagicMock(name="build")
    monkeypatch.setattr(auth_module, "default", default_mock)
    monkeypatch.setattr(auth_module, "build", build_mock)
    return default_mock, build_mock


def test_build_calendar_service_requests_calendar_scopes(monkeypatch):
    default_mock, build_mock = _patch_auth_builders(monkeypatch)

    build_calendar_service()

    default_mock.assert_called_once_with(scopes=CALENDAR_SCOPES)
    build_mock.assert_called_once()
    args, _ = build_mock.call_args
    assert args[0] == "calendar"


def test_build_drive_service_requests_drive_read_scopes(monkeypatch):
    default_mock, build_mock = _patch_auth_builders(monkeypatch)

    build_drive_service()

    default_mock.assert_called_once_with(scopes=DRIVE_READ_SCOPES)
    args, _ = build_mock.call_args
    assert args[0] == "drive"


def test_build_drive_upload_service_requests_drive_upload_scopes(monkeypatch):
    default_mock, build_mock = _patch_auth_builders(monkeypatch)

    build_drive_upload_service()

    default_mock.assert_called_once_with(scopes=DRIVE_UPLOAD_SCOPES)
    args, _ = build_mock.call_args
    assert args[0] == "drive"
