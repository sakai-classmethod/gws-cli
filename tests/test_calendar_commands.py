import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from gws_cli.main import app

runner = CliRunner()


def _http_error(status, reason, content=b""):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _request_mock(uri="https://example.com/events", execute_return=None):
    request = MagicMock()
    request.uri = uri
    request.execute.return_value = execute_return or {}
    return request


@pytest.fixture
def fake_calendar_service(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr("gws_cli.calendar.build_calendar_service", lambda: service)
    return service


def test_event_get_outputs_event_with_attachments_and_links(fake_calendar_service):
    event = {
        "id": "evt-1",
        "summary": "Demo",
        "description": (
            '<a href="https://drive.google.com/drive/folders/F1">folder</a>'
        ),
        "attachments": [
            {
                "fileId": "DOC1",
                "title": "Gemini メモ",
                "fileUrl": "https://docs.google.com/document/d/DOC1/edit",
                "mimeType": "application/vnd.google-apps.document",
            }
        ],
    }
    request = _request_mock(
        uri="https://example.com/events/evt-1", execute_return=event
    )
    fake_calendar_service.events.return_value.get.return_value = request

    result = runner.invoke(app, ["calendar", "event", "get", "evt-1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == "evt-1"
    assert payload["attachments"] == event["attachments"]
    by_id = {entry["fileId"]: entry for entry in payload["links"]}
    assert set(by_id) == {"DOC1", "F1"}
    assert by_id["DOC1"]["sources"] == ["event.attachments"]
    assert by_id["F1"]["mimeType"] == "application/vnd.google-apps.folder"
    assert "supportsAttachments=true" in request.uri


def test_event_get_fills_empty_attachments_when_api_omits(fake_calendar_service):
    request = _request_mock(execute_return={"id": "evt-2", "summary": "x"})
    fake_calendar_service.events.return_value.get.return_value = request

    result = runner.invoke(app, ["calendar", "event", "get", "evt-2"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["attachments"] == []
    assert payload["links"] == []


def test_event_get_returns_exit_1_on_404(fake_calendar_service):
    request = _request_mock()
    request.execute.side_effect = _http_error(404, "Not Found")
    fake_calendar_service.events.return_value.get.return_value = request

    result = runner.invoke(app, ["calendar", "event", "get", "missing"])

    assert result.exit_code == 1
    assert "404" in result.output or "Not Found" in result.output


def test_event_list_outputs_envelope_with_items_and_token(fake_calendar_service):
    response = {
        "items": [
            {"id": "a", "summary": "x"},
            {
                "id": "b",
                "summary": "y",
                "attachments": [
                    {
                        "fileId": "DOC1",
                        "title": "Gemini",
                        "fileUrl": "https://docs.google.com/document/d/DOC1/edit",
                        "mimeType": "application/vnd.google-apps.document",
                    }
                ],
            },
        ],
        "nextPageToken": "TOK",
    }
    request = _request_mock(execute_return=response)
    fake_calendar_service.events.return_value.list.return_value = request

    result = runner.invoke(
        app,
        [
            "calendar",
            "event",
            "list",
            "--time-min",
            "2026-05-01T00:00:00+09:00",
            "--time-max",
            "2026-05-08T00:00:00+09:00",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["nextPageToken"] == "TOK"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["attachments"] == []
    assert payload["items"][0]["links"] == []
    assert payload["items"][1]["links"][0]["fileId"] == "DOC1"
    assert "supportsAttachments=true" in request.uri


def test_event_list_passes_filters_to_api(fake_calendar_service):
    request = _request_mock(execute_return={"items": []})
    fake_calendar_service.events.return_value.list.return_value = request

    runner.invoke(
        app,
        [
            "calendar",
            "event",
            "list",
            "--calendar-id",
            "alt@example.com",
            "--time-min",
            "2026-05-01T00:00:00+09:00",
            "--time-max",
            "2026-05-08T00:00:00+09:00",
            "--q",
            "design review",
            "--event-type",
            "default",
            "--event-type",
            "focusTime",
            "--order-by",
            "startTime",
            "--page-size",
            "75",
            "--time-zone",
            "Asia/Tokyo",
        ],
    )

    list_call = fake_calendar_service.events.return_value.list
    kwargs = list_call.call_args.kwargs
    assert kwargs["calendarId"] == "alt@example.com"
    assert kwargs["timeMin"] == "2026-05-01T00:00:00+09:00"
    assert kwargs["timeMax"] == "2026-05-08T00:00:00+09:00"
    assert kwargs["q"] == "design review"
    assert kwargs["eventTypes"] == ["default", "focusTime"]
    assert kwargs["orderBy"] == "startTime"
    assert kwargs["maxResults"] == 75
    assert kwargs["timeZone"] == "Asia/Tokyo"
    assert kwargs["singleEvents"] is True


def test_event_list_with_all_pages_aggregates_items_and_omits_token(
    fake_calendar_service,
):
    request_a = _request_mock(
        execute_return={"items": [{"id": "a"}], "nextPageToken": "T1"}
    )
    request_b = _request_mock(execute_return={"items": [{"id": "b"}]})
    fake_calendar_service.events.return_value.list.side_effect = [
        request_a,
        request_b,
    ]

    result = runner.invoke(
        app,
        [
            "calendar",
            "event",
            "list",
            "--time-min",
            "2026-05-01T00:00:00+09:00",
            "--time-max",
            "2026-05-08T00:00:00+09:00",
            "--all-pages",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["items"]] == ["a", "b"]
    assert "nextPageToken" not in payload


def test_event_list_all_pages_without_time_range_exits_with_code_2(
    fake_calendar_service,
):
    result = runner.invoke(app, ["calendar", "event", "list", "--all-pages"])

    assert result.exit_code == 2
    fake_calendar_service.events.return_value.list.assert_not_called()


def test_event_list_returns_exit_1_on_403(fake_calendar_service):
    request = _request_mock()
    request.execute.side_effect = _http_error(403, "Forbidden")
    fake_calendar_service.events.return_value.list.return_value = request

    result = runner.invoke(app, ["calendar", "event", "list"])

    assert result.exit_code == 1


def test_calendars_command_outputs_calendar_list_envelope(fake_calendar_service):
    response = {
        "items": [
            {"id": "primary", "summary": "Me"},
            {"id": "alt@example.com", "summary": "Alt"},
        ]
    }
    request = MagicMock()
    request.execute.return_value = response
    fake_calendar_service.calendarList.return_value.list.return_value = request

    result = runner.invoke(app, ["calendar", "calendars"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {"items": response["items"]}


def test_attachments_command_emits_deprecation_warning_to_stderr(
    fake_calendar_service,
):
    request = _request_mock(execute_return={"attachments": []})
    fake_calendar_service.events.return_value.get.return_value = request

    result = runner.invoke(
        app,
        ["calendar", "attachments", "evt-x"],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == []
    assert "deprecated" in result.stderr.lower()
    assert "calendar event get" in result.stderr
