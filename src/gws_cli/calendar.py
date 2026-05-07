import html
import json
import re
import sys
from typing import Any

import typer
from bs4 import BeautifulSoup
from googleapiclient.errors import HttpError

from gws_cli.auth import build_calendar_service

app = typer.Typer()
event_app = typer.Typer(help="Read Calendar events with attachments and links")
app.add_typer(event_app, name="event")


FOLDER_MIME = "application/vnd.google-apps.folder"

NATIVE_DOC_PATH_TO_MIME: dict[str, str] = {
    "document": "application/vnd.google-apps.document",
    "spreadsheets": "application/vnd.google-apps.spreadsheet",
    "presentation": "application/vnd.google-apps.presentation",
    "forms": "application/vnd.google-apps.form",
    "drawings": "application/vnd.google-apps.drawing",
}

_DOCS_NATIVE_RE = re.compile(
    r"https?://docs\.google\.com/"
    r"(document|spreadsheets|presentation|forms|drawings)/d/"
    r"([A-Za-z0-9_\-]+)"
)
_DRIVE_FILE_RE = re.compile(r"https?://drive\.google\.com/file/d/([A-Za-z0-9_\-]+)")
_DRIVE_FOLDER_RE = re.compile(
    r"https?://drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_\-]+)"
)
_PLAIN_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#@!$&'*+,;=%]+")
_PLAIN_URL_TRAILING_TRIM = '.,;:)>]"'


def parse_drive_url(url: str) -> tuple[str, str | None] | None:
    if not isinstance(url, str):
        return None
    m = _DOCS_NATIVE_RE.search(url)
    if m:
        return m.group(2), NATIVE_DOC_PATH_TO_MIME[m.group(1)]
    m = _DRIVE_FOLDER_RE.search(url)
    if m:
        return m.group(1), FOLDER_MIME
    m = _DRIVE_FILE_RE.search(url)
    if m:
        return m.group(1), None
    return None


def _link_entry(
    *,
    url: str,
    file_id: str | None,
    mime_type: str | None,
    title: str | None,
    source: str,
) -> dict:
    return {
        "url": url,
        "fileId": file_id,
        "mimeType": mime_type,
        "title": title,
        "sources": [source],
        "sourceUrls": [url],
    }


def extract_links_from_attachments(
    attachments: list[dict] | None,
) -> list[dict]:
    if not attachments:
        return []
    return [
        _link_entry(
            url=att.get("fileUrl") or "",
            file_id=att.get("fileId"),
            mime_type=att.get("mimeType"),
            title=att.get("title"),
            source="event.attachments",
        )
        for att in attachments
    ]


def _add_or_merge(
    by_fileid: dict[str, dict],
    order: list[str],
    candidate: dict,
) -> None:
    file_id = candidate["fileId"]
    if file_id not in by_fileid:
        by_fileid[file_id] = {
            "url": candidate["url"],
            "fileId": file_id,
            "mimeType": candidate.get("mimeType"),
            "title": candidate.get("title"),
            "sources": list(candidate.get("sources", [])),
            "sourceUrls": list(candidate.get("sourceUrls", [])),
        }
        order.append(file_id)
        return
    existing = by_fileid[file_id]
    for source in candidate.get("sources", []):
        if source not in existing["sources"]:
            existing["sources"].append(source)
    for source_url in candidate.get("sourceUrls", []):
        if source_url not in existing["sourceUrls"]:
            existing["sourceUrls"].append(source_url)
    if existing["title"] is None and candidate.get("title"):
        existing["title"] = candidate["title"]
    if existing["mimeType"] is None and candidate.get("mimeType"):
        existing["mimeType"] = candidate["mimeType"]


def extract_links_from_description(description: str | None) -> list[dict]:
    if not description:
        return []
    soup = BeautifulSoup(description, "html.parser")

    by_fileid: dict[str, dict] = {}
    order: list[str] = []
    seen_anchor_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = html.unescape(anchor.get("href"))
        text_unescaped = html.unescape(anchor.get_text() or "").strip()
        parsed = parse_drive_url(href)
        if parsed is None:
            continue
        file_id, mime = parsed
        title = (
            None if text_unescaped == "" or text_unescaped == href else text_unescaped
        )
        seen_anchor_urls.add(href)
        _add_or_merge(
            by_fileid,
            order,
            _link_entry(
                url=href,
                file_id=file_id,
                mime_type=mime,
                title=title,
                source="event.description",
            ),
        )

    plain_text = html.unescape(soup.get_text(" "))
    for raw in _PLAIN_URL_RE.findall(plain_text):
        url = raw.rstrip(_PLAIN_URL_TRAILING_TRIM)
        if url in seen_anchor_urls:
            continue
        parsed = parse_drive_url(url)
        if parsed is None:
            continue
        file_id, mime = parsed
        _add_or_merge(
            by_fileid,
            order,
            _link_entry(
                url=url,
                file_id=file_id,
                mime_type=mime,
                title=None,
                source="event.description",
            ),
        )

    return [by_fileid[file_id] for file_id in order]


def merge_links(*link_lists: list[dict]) -> list[dict]:
    by_fileid: dict[str, dict] = {}
    order: list[str] = []
    no_id: list[dict] = []
    for entries in link_lists:
        for entry in entries:
            if entry.get("fileId") is None:
                no_id.append(
                    {
                        "url": entry["url"],
                        "fileId": None,
                        "mimeType": entry.get("mimeType"),
                        "title": entry.get("title"),
                        "sources": list(entry.get("sources", [])),
                        "sourceUrls": list(entry.get("sourceUrls", [])),
                    }
                )
                continue
            _add_or_merge(by_fileid, order, entry)
    return [by_fileid[file_id] for file_id in order] + no_id


def build_links(event: dict) -> list[dict]:
    return merge_links(
        extract_links_from_attachments(event.get("attachments")),
        extract_links_from_description(event.get("description")),
    )


def _with_supports_attachments(request: Any) -> Any:
    """Append ``supportsAttachments=true`` to a Discovery request URI in-place.

    The Calendar v3 Discovery doc does not expose ``supportsAttachments`` on
    ``events.get`` / ``events.list``, so we patch the URI directly. Returns
    the same request object so callers can chain.
    """
    if "supportsAttachments=true" in request.uri:
        return request
    sep = "&" if "?" in request.uri else "?"
    request.uri += f"{sep}supportsAttachments=true"
    return request


def fetch_event(service: Any, event_id: str, calendar_id: str = "primary") -> dict:
    request = service.events().get(calendarId=calendar_id, eventId=event_id)
    _with_supports_attachments(request)
    return request.execute()


def list_events(
    service: Any,
    *,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    q: str | None = None,
    event_types: list[str] | None = None,
    order_by: str | None = None,
    page_size: int | None = None,
    page_token: str | None = None,
    time_zone: str | None = None,
    show_deleted: bool = False,
    single_events: bool = True,
) -> dict:
    kwargs: dict[str, Any] = {
        "calendarId": calendar_id,
        "singleEvents": single_events,
    }
    if time_min is not None:
        kwargs["timeMin"] = time_min
    if time_max is not None:
        kwargs["timeMax"] = time_max
    if q is not None:
        kwargs["q"] = q
    if event_types:
        kwargs["eventTypes"] = event_types
    if order_by is not None:
        kwargs["orderBy"] = order_by
    if page_size is not None:
        kwargs["maxResults"] = page_size
    if page_token is not None:
        kwargs["pageToken"] = page_token
    if time_zone is not None:
        kwargs["timeZone"] = time_zone
    if show_deleted:
        kwargs["showDeleted"] = True

    request = service.events().list(**kwargs)
    _with_supports_attachments(request)
    return request.execute()


def list_events_all_pages(
    service: Any,
    *,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    q: str | None = None,
    event_types: list[str] | None = None,
    order_by: str | None = None,
    page_size: int | None = None,
    time_zone: str | None = None,
    show_deleted: bool = False,
    single_events: bool = True,
) -> list[dict]:
    if time_min is None or time_max is None:
        raise ValueError("list_events_all_pages requires both time_min and time_max")
    items: list[dict] = []
    page_token: str | None = None
    while True:
        response = list_events(
            service,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            q=q,
            event_types=event_types,
            order_by=order_by,
            page_size=page_size,
            page_token=page_token,
            time_zone=time_zone,
            show_deleted=show_deleted,
            single_events=single_events,
        )
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def get_attachments(
    service: Any, event_id: str, calendar_id: str = "primary"
) -> list[dict]:
    event = fetch_event(service, event_id=event_id, calendar_id=calendar_id)
    return event.get("attachments", [])


def _enrich_event(event: dict) -> dict:
    return {
        **event,
        "attachments": event.get("attachments") or [],
        "links": build_links(event),
    }


@app.command("attachments")
def attachments_command(
    event_id: str,
    calendar_id: str = typer.Option("primary", "--calendar-id"),
) -> None:
    print(
        "warning: 'calendar attachments' is deprecated; "
        "use 'gws-cli calendar event get <event-id>' "
        "(returns attachments and extracted Drive links). "
        "This command will be removed in the next major release.",
        file=sys.stderr,
    )
    service = build_calendar_service()
    try:
        result = get_attachments(service, event_id=event_id, calendar_id=calendar_id)
        print(json.dumps(result, ensure_ascii=False))
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None


@event_app.command("get")
def event_get_command(
    event_id: str,
    calendar_id: str = typer.Option("primary", "--calendar-id"),
) -> None:
    service = build_calendar_service()
    try:
        event = fetch_event(service, event_id=event_id, calendar_id=calendar_id)
        print(json.dumps(_enrich_event(event), ensure_ascii=False))
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None


@event_app.command("list")
def event_list_command(
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    time_min: str = typer.Option(None, "--time-min"),
    time_max: str = typer.Option(None, "--time-max"),
    q: str = typer.Option(None, "--q"),
    event_type: list[str] = typer.Option(None, "--event-type"),
    order_by: str = typer.Option(None, "--order-by"),
    page_size: int = typer.Option(None, "--page-size"),
    page_token: str = typer.Option(None, "--page-token"),
    time_zone: str = typer.Option(None, "--time-zone"),
    show_deleted: bool = typer.Option(False, "--show-deleted"),
    all_pages: bool = typer.Option(False, "--all-pages"),
) -> None:
    if all_pages and (time_min is None or time_max is None):
        print(
            "Error: --all-pages requires both --time-min and --time-max",
            file=sys.stderr,
        )
        raise typer.Exit(code=2)

    service = build_calendar_service()
    try:
        if all_pages:
            items_raw = list_events_all_pages(
                service,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                q=q,
                event_types=event_type or None,
                order_by=order_by,
                page_size=page_size,
                time_zone=time_zone,
                show_deleted=show_deleted,
            )
            envelope: dict[str, Any] = {
                "items": [_enrich_event(item) for item in items_raw]
            }
        else:
            response = list_events(
                service,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                q=q,
                event_types=event_type or None,
                order_by=order_by,
                page_size=page_size,
                page_token=page_token,
                time_zone=time_zone,
                show_deleted=show_deleted,
            )
            envelope = {
                "items": [_enrich_event(item) for item in response.get("items", [])]
            }
            if response.get("nextPageToken"):
                envelope["nextPageToken"] = response["nextPageToken"]
            if response.get("nextSyncToken"):
                envelope["nextSyncToken"] = response["nextSyncToken"]
        print(json.dumps(envelope, ensure_ascii=False))
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None


@app.command("calendars")
def calendars_command() -> None:
    service = build_calendar_service()
    try:
        items: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {}
            if page_token:
                kwargs["pageToken"] = page_token
            response = service.calendarList().list(**kwargs).execute()
            items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        print(json.dumps({"items": items}, ensure_ascii=False))
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None
