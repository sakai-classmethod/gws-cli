import re
import sys
from typing import Any

import typer
from googleapiclient.errors import HttpError
from markdownify import markdownify

from gws_cli.auth import build_drive_service

app = typer.Typer()


def _strip_style_attributes(html: str) -> str:
    return re.sub(r'\s+style="[^"]*"', "", re.sub(r"\s+style='[^']*'", "", html))


SECTION_MARKERS = {
    "transcript": "📖 文字起こし",
    "notes": "📝 メモ",
}


def extract_section(text: str, section: str | None) -> str:
    if section is None:
        return text
    marker = SECTION_MARKERS.get(section)
    if marker is None or marker not in text:
        return text
    parts = text.split(marker, 1)
    if section == "notes":
        after_marker = parts[1]
        next_marker = SECTION_MARKERS["transcript"]
        if next_marker in after_marker:
            after_marker = after_marker.split(next_marker, 1)[0]
        return (marker + after_marker).strip()
    return (marker + parts[1]).strip()


def get_doc_content(service: Any, doc_id: str, fmt: str = "plain") -> str:
    if fmt == "md":
        raw = service.files().export(fileId=doc_id, mimeType="text/html").execute()
        html = _strip_style_attributes(raw.decode("utf-8"))
        return markdownify(html)
    else:
        raw = service.files().export(fileId=doc_id, mimeType="text/plain").execute()
        return raw.decode("utf-8")


@app.command("get")
def get_command(
    doc_id: str,
    fmt: str = typer.Option("plain", "--format"),
    section: str = typer.Option(None, "--section", help="transcript or notes"),
) -> None:
    service = build_drive_service()
    try:
        content = get_doc_content(service, doc_id=doc_id, fmt=fmt)
        content = extract_section(content, section)
        print(content)
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None
