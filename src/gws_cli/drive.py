import json
import mimetypes
import sys
from pathlib import Path
from typing import Any

import typer
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from gws_cli.auth import build_drive_upload_service

app = typer.Typer()

FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveUploadError(Exception):
    pass


def guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def validate_folder(service: Any, folder_id: str) -> None:
    meta = (
        service.files().get(fileId=folder_id, fields="id, driveId, mimeType").execute()
    )
    if meta.get("driveId"):
        raise DriveUploadError(
            f"Folder {folder_id} is on a shared drive; only My Drive is allowed."
        )
    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveUploadError(
            f"Target {folder_id} is not a folder (mimeType={meta.get('mimeType')})"
        )


def _escape_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_existing(service: Any, name: str, parent_id: str) -> list[dict]:
    safe = _escape_query_literal(name)
    query = f"'{parent_id}' in parents and name = '{safe}' and trashed = false"
    resp = (
        service.files()
        .list(q=query, fields="files(id, name, mimeType)", spaces="drive")
        .execute()
    )
    return resp.get("files", [])


def _latest_revision_id(service: Any, file_id: str) -> str | None:
    resp = service.revisions().list(fileId=file_id, fields="revisions(id)").execute()
    revs = resp.get("revisions", [])
    return revs[-1]["id"] if revs else None


def upload_file(
    service: Any,
    local_path: Path,
    name: str | None,
    folder_id: str | None,
    overwrite: bool,
    keep_forever: bool,
) -> dict:
    if not local_path.is_file():
        raise DriveUploadError(f"Local file not found: {local_path}")

    display_name = name or local_path.name
    parent_id = folder_id or "root"

    if folder_id is not None:
        validate_folder(service, folder_id)

    existing = find_existing(service, display_name, parent_id)

    if len(existing) >= 2:
        ids = [f["id"] for f in existing]
        raise DriveUploadError(
            f"Multiple files named '{display_name}' exist in folder "
            f"{parent_id}: fileIds={ids}. "
            f"Resolve ambiguity manually before retrying."
        )

    if len(existing) == 1 and not overwrite:
        raise DriveUploadError(
            f"File '{display_name}' already exists in folder {parent_id} "
            f"(fileId: {existing[0]['id']}). "
            f"Pass --overwrite to replace or --name to use a different name."
        )

    mime_type = guess_mime_type(local_path)
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    response_fields = "id, name, mimeType, webViewLink"

    if existing:
        file_id = existing[0]["id"]
        try:
            prev_rev_id = _latest_revision_id(service, file_id)
        except HttpError as e:
            raise DriveUploadError(
                f"Failed to fetch previous revision before overwrite "
                f"(fileId: {file_id}): {e.resp.status} {e.resp.reason}. "
                f"Refusing to overwrite without rollback handle; retry later."
            ) from e
        result = (
            service.files()
            .update(
                fileId=file_id,
                media_body=media,
                keepRevisionForever=keep_forever,
                fields=response_fields,
            )
            .execute()
        )
        return {
            "fileId": result["id"],
            "name": result["name"],
            "mimeType": result["mimeType"],
            "webViewLink": result.get("webViewLink", ""),
            "action": "updated",
            "previousRevisionId": prev_rev_id,
        }

    body: dict[str, Any] = {"name": display_name, "parents": [parent_id]}
    result = (
        service.files()
        .create(
            body=body,
            media_body=media,
            keepRevisionForever=keep_forever,
            fields=response_fields,
        )
        .execute()
    )
    return {
        "fileId": result["id"],
        "name": result["name"],
        "mimeType": result["mimeType"],
        "webViewLink": result.get("webViewLink", ""),
        "action": "created",
        "previousRevisionId": None,
    }


@app.command("upload")
def upload_command(
    local_path: Path,
    folder_id: str = typer.Option(
        None,
        "--folder-id",
        envvar="GWS_CLI_DEFAULT_FOLDER_ID",
        help="My Drive folder ID (defaults to My Drive root)",
    ),
    name: str = typer.Option(
        None, "--name", help="Drive display name (defaults to local basename)"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace an existing single match as a new revision"
    ),
    keep_forever: bool = typer.Option(
        False,
        "--keep-forever",
        help="Mark the created revision with keepRevisionForever",
    ),
) -> None:
    service = build_drive_upload_service()
    try:
        result = upload_file(
            service,
            local_path=local_path,
            name=name,
            folder_id=folder_id,
            overwrite=overwrite,
            keep_forever=keep_forever,
        )
    except DriveUploadError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None

    prev_rev = result.pop("previousRevisionId", None)
    if result["action"] == "updated":
        print(
            f"Overwriting existing file: {result['name']} "
            f"(fileId: {result['fileId']}, previousRevisionId: {prev_rev})",
            file=sys.stderr,
        )
    print(json.dumps(result, ensure_ascii=False))
