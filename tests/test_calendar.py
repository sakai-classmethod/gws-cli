from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from gws_cli.calendar import get_attachments


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_service_mock(execute_return=None, execute_side_effect=None):
    service = MagicMock()
    request_mock = MagicMock()
    request_mock.uri = "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt"
    if execute_side_effect:
        request_mock.execute.side_effect = execute_side_effect
    else:
        request_mock.execute.return_value = execute_return
    service.events.return_value.get.return_value = request_mock
    return service


def test_get_attachments_returns_attachment_list():
    service = _make_service_mock(execute_return={
        "attachments": [
            {
                "fileId": "file-123",
                "title": "Agenda.pdf",
                "fileUrl": "https://drive.google.com/file/d/file-123/view",
            }
        ]
    })

    result = get_attachments(service, event_id="event-123", calendar_id="primary")

    assert result == [
        {
            "fileId": "file-123",
            "title": "Agenda.pdf",
            "fileUrl": "https://drive.google.com/file/d/file-123/view",
        }
    ]
    service.events.return_value.get.assert_called_once_with(
        calendarId="primary",
        eventId="event-123",
    )


def test_get_attachments_appends_supports_attachments_to_uri():
    service = _make_service_mock(execute_return={"attachments": []})
    request_mock = service.events.return_value.get.return_value

    get_attachments(service, event_id="evt", calendar_id="primary")

    assert "supportsAttachments=true" in request_mock.uri


def test_get_attachments_returns_empty_list_when_no_attachments_key():
    service = _make_service_mock(execute_return={})

    result = get_attachments(service, event_id="event-456", calendar_id="team")

    assert result == []


def test_get_attachments_propagates_404():
    service = _make_service_mock(
        execute_side_effect=_make_http_error(404, "Not Found", b"not found")
    )

    with pytest.raises(HttpError) as exc_info:
        get_attachments(service, event_id="missing", calendar_id="primary")

    assert exc_info.value.resp.status == 404


def test_get_attachments_propagates_403():
    service = _make_service_mock(
        execute_side_effect=_make_http_error(403, "Forbidden", b"forbidden")
    )

    with pytest.raises(HttpError) as exc_info:
        get_attachments(service, event_id="restricted", calendar_id="primary")

    assert exc_info.value.resp.status == 403
