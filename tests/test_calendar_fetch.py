from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from gws_cli.calendar import (
    _with_supports_attachments,
    fetch_event,
    list_events,
    list_events_all_pages,
)


def _make_http_error(status, reason, content=b""):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_request_mock(uri: str, execute_return=None, execute_side_effect=None):
    request = MagicMock()
    request.uri = uri
    if execute_side_effect is not None:
        request.execute.side_effect = execute_side_effect
    else:
        request.execute.return_value = execute_return
    return request


def _make_get_service(request):
    service = MagicMock()
    service.events.return_value.get.return_value = request
    return service


def _make_list_service(request):
    service = MagicMock()
    service.events.return_value.list.return_value = request
    return service


def test_with_supports_attachments_appends_with_question_mark():
    request = _make_request_mock(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt"
    )

    returned = _with_supports_attachments(request)

    assert returned is request
    assert request.uri.endswith("?supportsAttachments=true")


def test_with_supports_attachments_appends_with_ampersand_when_query_present():
    request = _make_request_mock(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        "?timeMin=2026-01-01T00:00:00Z"
    )

    _with_supports_attachments(request)

    assert request.uri.endswith("&supportsAttachments=true")


def test_with_supports_attachments_does_not_double_append():
    request = _make_request_mock(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt"
    )

    _with_supports_attachments(request)
    _with_supports_attachments(request)

    assert request.uri.count("supportsAttachments=true") == 1


def test_fetch_event_invokes_get_with_calendar_and_event_ids():
    request = _make_request_mock(
        "https://example.com/events/evt", execute_return={"id": "evt"}
    )
    service = _make_get_service(request)

    result = fetch_event(service, event_id="evt", calendar_id="primary")

    service.events.return_value.get.assert_called_once_with(
        calendarId="primary", eventId="evt"
    )
    assert result == {"id": "evt"}


def test_fetch_event_appends_supports_attachments_to_request_uri():
    request = _make_request_mock("https://example.com/events/evt", execute_return={})
    service = _make_get_service(request)

    fetch_event(service, event_id="evt", calendar_id="primary")

    assert "supportsAttachments=true" in request.uri


def test_fetch_event_propagates_404():
    request = _make_request_mock(
        "https://example.com/events/missing",
        execute_side_effect=_make_http_error(404, "Not Found"),
    )
    service = _make_get_service(request)

    with pytest.raises(HttpError) as excinfo:
        fetch_event(service, event_id="missing", calendar_id="primary")

    assert excinfo.value.resp.status == 404


def test_list_events_passes_only_provided_kwargs_and_attaches_attachments():
    request = _make_request_mock(
        "https://example.com/events?calendarId=primary",
        execute_return={"items": [{"id": "a"}], "nextPageToken": "TOK"},
    )
    service = _make_list_service(request)

    result = list_events(
        service,
        calendar_id="primary",
        time_min="2026-05-01T00:00:00+09:00",
        time_max="2026-05-08T00:00:00+09:00",
        q="meeting",
        event_types=["default"],
        order_by="startTime",
        page_size=50,
        page_token=None,
        time_zone="Asia/Tokyo",
    )

    list_call = service.events.return_value.list
    list_call.assert_called_once()
    kwargs = list_call.call_args.kwargs
    assert kwargs == {
        "calendarId": "primary",
        "timeMin": "2026-05-01T00:00:00+09:00",
        "timeMax": "2026-05-08T00:00:00+09:00",
        "q": "meeting",
        "eventTypes": ["default"],
        "orderBy": "startTime",
        "maxResults": 50,
        "timeZone": "Asia/Tokyo",
        "singleEvents": True,
    }
    assert "supportsAttachments=true" in request.uri
    assert result == {"items": [{"id": "a"}], "nextPageToken": "TOK"}


def test_list_events_passes_page_token_when_provided():
    request = _make_request_mock(
        "https://example.com/events", execute_return={"items": []}
    )
    service = _make_list_service(request)

    list_events(service, calendar_id="primary", page_token="PTOK")

    kwargs = service.events.return_value.list.call_args.kwargs
    assert kwargs["pageToken"] == "PTOK"


def test_list_events_all_pages_collects_items_across_pages():
    request_a = _make_request_mock(
        "https://example.com/events",
        execute_return={"items": [{"id": "a"}], "nextPageToken": "T1"},
    )
    request_b = _make_request_mock(
        "https://example.com/events?pageToken=T1",
        execute_return={"items": [{"id": "b"}], "nextPageToken": "T2"},
    )
    request_c = _make_request_mock(
        "https://example.com/events?pageToken=T2",
        execute_return={"items": [{"id": "c"}]},
    )
    service = MagicMock()
    service.events.return_value.list.side_effect = [
        request_a,
        request_b,
        request_c,
    ]

    items = list_events_all_pages(
        service,
        calendar_id="primary",
        time_min="2026-05-01T00:00:00+09:00",
        time_max="2026-05-08T00:00:00+09:00",
    )

    assert [item["id"] for item in items] == ["a", "b", "c"]
    assert service.events.return_value.list.call_count == 3
    second_kwargs = service.events.return_value.list.call_args_list[1].kwargs
    third_kwargs = service.events.return_value.list.call_args_list[2].kwargs
    assert second_kwargs["pageToken"] == "T1"
    assert third_kwargs["pageToken"] == "T2"


def test_list_events_all_pages_requires_time_range():
    service = MagicMock()

    with pytest.raises(ValueError):
        list_events_all_pages(service, calendar_id="primary")

    with pytest.raises(ValueError):
        list_events_all_pages(
            service, calendar_id="primary", time_min="2026-05-01T00:00:00Z"
        )

    with pytest.raises(ValueError):
        list_events_all_pages(
            service, calendar_id="primary", time_max="2026-05-08T00:00:00Z"
        )
