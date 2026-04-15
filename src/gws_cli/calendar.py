import json
import sys
from typing import Any

import typer
from googleapiclient.errors import HttpError

from gws_cli.auth import build_calendar_service

app = typer.Typer()


def get_attachments(
    service: Any, event_id: str, calendar_id: str = "primary"
) -> list[dict]:
    request = service.events().get(calendarId=calendar_id, eventId=event_id)
    sep = "&" if "?" in request.uri else "?"
    request.uri += f"{sep}supportsAttachments=true"
    event = request.execute()
    return event.get("attachments", [])


@app.command("attachments")
def attachments_command(
    event_id: str,
    calendar_id: str = typer.Option("primary", "--calendar-id"),
) -> None:
    service = build_calendar_service()
    try:
        result = get_attachments(service, event_id=event_id, calendar_id=calendar_id)
        print(json.dumps(result, ensure_ascii=False))
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1)
