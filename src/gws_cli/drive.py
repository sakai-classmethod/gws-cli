import contextlib
import json
import mimetypes
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

import typer
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from gws_cli.auth import build_drive_service, build_drive_write_service

app = typer.Typer()

FOLDER_MIME = "application/vnd.google-apps.folder"

DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024


class DriveError(Exception):
    pass


class DriveUploadError(DriveError):
    pass


class DriveDownloadError(DriveError):
    pass


class DriveMkdirError(DriveError):
    pass


class DriveMoveError(DriveError):
    pass


REJECTED_NATIVE_MIMES = frozenset(
    {
        FOLDER_MIME,
        "application/vnd.google-apps.shortcut",
        "application/vnd.google-apps.form",
        "application/vnd.google-apps.site",
        "application/vnd.google-apps.audio",
        "application/vnd.google-apps.video",
        "application/vnd.google-apps.fusiontable",
        "application/vnd.google-apps.jam",
        "application/vnd.google-apps.map",
        "application/vnd.google-apps.drive-sdk",
        "application/vnd.google-apps.unknown",
    }
)


NATIVE_DEFAULT_EXPORT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
    "application/vnd.google-apps.script": (
        "application/vnd.google-apps.script+json",
        ".json",
    ),
}


EXPORT_SHORTCUTS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", ".pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "csv": ("text/csv", ".csv"),
    "txt": ("text/plain", ".txt"),
    "rtf": ("application/rtf", ".rtf"),
    "odt": ("application/vnd.oasis.opendocument.text", ".odt"),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", ".ods"),
    "epub": ("application/epub+zip", ".epub"),
    "tsv": ("text/tab-separated-values", ".tsv"),
}


MIME_TO_EXT: dict[str, str] = {mime: ext for mime, ext in EXPORT_SHORTCUTS.values()}


STRIPPABLE_NAMING_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rtf",
        ".doc",
        ".docx",
        ".odt",
        ".html",
        ".htm",
        ".csv",
        ".tsv",
        ".xls",
        ".xlsx",
        ".ods",
        ".ppt",
        ".pptx",
        ".odp",
        ".pdf",
        ".epub",
    }
)


def guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def validate_folder(service: Any, folder_id: str) -> str:
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
    return meta["id"]


def _escape_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_existing(service: Any, name: str, parent_id: str) -> list[dict]:
    safe = _escape_query_literal(name)
    query = f"'{parent_id}' in parents and name = '{safe}' and trashed = false"
    files: list[dict] = []
    page_token: str | None = None
    while True:
        list_kwargs: dict[str, Any] = {
            "q": query,
            "fields": "nextPageToken, files(id, name, mimeType)",
            "spaces": "drive",
        }
        if page_token:
            list_kwargs["pageToken"] = page_token
        resp = service.files().list(**list_kwargs).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return files


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


def mkdir_folder(
    service: Any, name: str, parent_id: str | None, exist_ok: bool
) -> dict:
    resolved_parent = parent_id or "root"

    if parent_id is not None:
        validate_folder(service, parent_id)

    existing = find_existing(service, name, resolved_parent)

    if len(existing) >= 2:
        ids = [f["id"] for f in existing]
        raise DriveMkdirError(
            f"Multiple items named '{name}' exist in folder "
            f"{resolved_parent}: fileIds={ids}. "
            f"Resolve ambiguity manually before retrying."
        )

    response_fields = "id, name, mimeType, webViewLink, parents"

    if existing:
        match = existing[0]
        if not exist_ok:
            raise DriveMkdirError(
                f"'{name}' already exists in folder {resolved_parent} "
                f"(fileId: {match['id']}). "
                f"Pass --exist-ok to reuse an existing folder."
            )
        if match.get("mimeType") != FOLDER_MIME:
            raise DriveMkdirError(
                f"'{name}' exists but is not a folder in folder {resolved_parent} "
                f"(fileId: {match['id']}, mimeType={match.get('mimeType')})"
            )
        result = (
            service.files().get(fileId=match["id"], fields=response_fields).execute()
        )
        action = "existing"
    else:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [resolved_parent]}
        result = service.files().create(body=body, fields=response_fields).execute()
        action = "created"

    return {
        "fileId": result["id"],
        "name": result["name"],
        "mimeType": result["mimeType"],
        "webViewLink": result.get("webViewLink", ""),
        "parentId": (result.get("parents") or [resolved_parent])[0],
        "action": action,
    }


def move_file(service: Any, file_id: str, to_folder_id: str, name: str | None) -> dict:
    # "root" is only an alias: parents carry the canonical ID, so compare with that.
    dest_id = validate_folder(service, to_folder_id)

    meta = (
        service.files()
        .get(fileId=file_id, fields="id, name, mimeType, parents, driveId, webViewLink")
        .execute()
    )
    if meta.get("driveId"):
        raise DriveMoveError(
            f"File {file_id} is on a shared drive; only My Drive is allowed."
        )

    current_name: str = meta["name"]
    final_name = name or current_name
    previous_parents: list[str] = meta.get("parents", [])

    collisions = [
        f["id"]
        for f in find_existing(service, final_name, dest_id)
        if f["id"] != file_id
    ]
    if collisions:
        raise DriveMoveError(
            f"'{final_name}' already exists in destination {dest_id}: "
            f"fileIds={collisions}. Pass --name to use a different name."
        )

    renaming = final_name != current_name

    if dest_id in previous_parents and not renaming:
        result = meta
        action = "unchanged"
    else:
        update_kwargs: dict[str, Any] = {"fileId": file_id}
        if dest_id not in previous_parents:
            update_kwargs["addParents"] = dest_id
        remove_parents = ",".join(p for p in previous_parents if p != dest_id)
        if remove_parents:
            update_kwargs["removeParents"] = remove_parents
        result = (
            service.files()
            .update(
                **update_kwargs,
                body={"name": final_name} if renaming else {},
                fields="id, name, mimeType, parents, webViewLink",
            )
            .execute()
        )
        action = "moved"

    return {
        "fileId": result["id"],
        "name": result["name"],
        "mimeType": result["mimeType"],
        "webViewLink": result.get("webViewLink", ""),
        "parentId": dest_id,
        "previousParentIds": previous_parents,
        "action": action,
    }


def is_native_mime(mime: str) -> bool:
    return mime.startswith("application/vnd.google-apps.")


def check_rejected_mime(mime: str) -> None:
    if mime in REJECTED_NATIVE_MIMES:
        raise DriveDownloadError(
            f"Cannot download mimeType '{mime}': not a downloadable resource"
        )
    if mime.startswith(("video/", "audio/")):
        raise DriveDownloadError(
            f"Cannot download mimeType '{mime}': video/audio downloads are out of scope"
        )


def resolve_export(format_arg: str | None, source_mime: str) -> tuple[str, str] | None:
    if not is_native_mime(source_mime):
        if format_arg is not None:
            raise DriveDownloadError(
                f"--export is only valid for Google native files; "
                f"file mimeType is '{source_mime}'"
            )
        return None

    if format_arg is None:
        if source_mime not in NATIVE_DEFAULT_EXPORT:
            raise DriveDownloadError(
                f"No default export format for native mimeType '{source_mime}'; "
                f"specify --export"
            )
        return NATIVE_DEFAULT_EXPORT[source_mime]

    if format_arg in EXPORT_SHORTCUTS:
        return EXPORT_SHORTCUTS[format_arg]

    if "/" in format_arg:
        return (format_arg, MIME_TO_EXT.get(format_arg, ""))

    raise DriveDownloadError(
        f"Unknown --export value '{format_arg}'; "
        f"use a shortcut ({', '.join(sorted(EXPORT_SHORTCUTS))}) or a MIME type"
    )


def sanitize_filename(name: str) -> str:
    return name.replace("/", "_").replace("\0", "_")


def _strip_naming_suffix(name: str) -> str:
    p = Path(name)
    if p.suffix.lower() in STRIPPABLE_NAMING_SUFFIXES:
        return name[: -len(p.suffix)]
    return name


def resolve_local_path(dest: str | None, drive_name: str, ext: str) -> Path:
    safe_name = sanitize_filename(drive_name)
    if ext and not safe_name.lower().endswith(ext.lower()):
        safe_name = _strip_naming_suffix(safe_name) + ext

    if dest is None or dest == "":
        return Path.cwd() / safe_name

    trailing = dest.endswith(("/", os.sep))
    dest_path = Path(dest)

    if trailing:
        if not dest_path.is_dir():
            raise DriveDownloadError(f"Directory not found: {dest}")
        return dest_path / safe_name

    if dest_path.is_dir():
        return dest_path / safe_name

    return dest_path


def _stream_download(request: Any, fd: BinaryIO) -> int:
    downloader = MediaIoBaseDownload(fd, request, chunksize=DOWNLOAD_CHUNK_SIZE)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=3)
    try:
        return fd.tell()
    except OSError:
        return 0


def _is_export_too_large_error(err: HttpError) -> bool:
    status = err.resp.status
    if status not in (400, 403):
        return False
    text = ""
    if hasattr(err, "content") and err.content:
        try:
            text = err.content.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    if not text:
        text = str(err)
    text_lower = text.lower()
    return "too large" in text_lower or "exportsizelimitexceeded" in text_lower


def download_file(
    service: Any,
    file_id: str,
    dest: str | None,
    export: str | None,
    overwrite: bool,
    stdout_buffer: BinaryIO | None = None,
    stdout_is_tty: bool = False,
) -> dict:
    meta = (
        service.files()
        .get(
            fileId=file_id,
            fields=(
                "id, name, mimeType, driveId, size, headRevisionId, "
                "modifiedTime, md5Checksum, webViewLink"
            ),
            supportsAllDrives=True,
        )
        .execute()
    )

    mime: str = meta["mimeType"]
    name: str = meta["name"]
    check_rejected_mime(mime)

    export_resolution = resolve_export(export, mime)
    if export_resolution is None:
        source = "media"
        export_mime: str | None = None
        ext = ""
    else:
        source = "export"
        export_mime, ext = export_resolution

    use_stdout = dest == "-"

    if use_stdout:
        if stdout_buffer is None:
            raise DriveDownloadError("stdout buffer not provided for '-' destination")
        if stdout_is_tty:
            raise DriveDownloadError(
                "Refusing to write binary content to a TTY; "
                "redirect stdout or specify <dest>"
            )
        local_path: Path | None = None
    else:
        local_path = resolve_local_path(dest, name, ext)
        if local_path.exists() and not overwrite:
            raise DriveDownloadError(
                f"Local file already exists: {local_path}. Pass --overwrite to replace."
            )
        if ext and local_path.suffix and local_path.suffix.lower() != ext.lower():
            print(
                f"Warning: dest extension '{local_path.suffix}' differs from "
                f"export extension '{ext}'",
                file=sys.stderr,
            )

    if source == "export":
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    try:
        if local_path is None:
            assert stdout_buffer is not None
            bytes_written = _stream_download(request, stdout_buffer)
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
                delete=False,
                dir=local_path.parent,
                prefix=f".{local_path.name}.",
                suffix=".part",
            )
            tmp_path = Path(tmp.name)
            try:
                bytes_written = _stream_download(request, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp_path, local_path)
            except BaseException:
                with contextlib.suppress(Exception):
                    tmp.close()
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                raise
    except HttpError as e:
        if source == "export" and _is_export_too_large_error(e):
            raise DriveDownloadError(
                "Export failed: Drive API limits export output to 10MB. "
                "Use the Drive UI 'File > Download' or Google Takeout for "
                "larger files."
            ) from e
        raise

    return {
        "fileId": meta["id"],
        "name": name,
        "mimeType": mime,
        "exportMime": export_mime,
        "localPath": None if local_path is None else str(local_path),
        "bytesWritten": bytes_written,
        "source": source,
        "action": "downloaded",
        "headRevisionId": meta.get("headRevisionId"),
        "modifiedTime": meta.get("modifiedTime"),
        "md5Checksum": None if source == "export" else meta.get("md5Checksum"),
        "size": None if source == "export" else meta.get("size"),
        "webViewLink": meta.get("webViewLink"),
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
    service = build_drive_write_service()
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


@app.command("download")
def download_command(
    file_id: str,
    dest: str = typer.Argument(
        None,
        help="Output path: directory, file, or '-' for stdout (defaults to CWD)",
    ),
    export: str = typer.Option(
        None,
        "--export",
        help=(
            "Export format for Google native files. "
            "Shortcut (pdf, docx, xlsx, pptx, png, jpeg, csv, txt, ...) "
            "or a MIME type."
        ),
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite an existing local file"
    ),
) -> None:
    service = build_drive_service()
    try:
        result = download_file(
            service,
            file_id=file_id,
            dest=dest,
            export=export,
            overwrite=overwrite,
            stdout_buffer=sys.stdout.buffer,
            stdout_is_tty=sys.stdout.isatty(),
        )
    except DriveDownloadError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None

    payload = json.dumps(result, ensure_ascii=False)
    if result["localPath"] is None:
        print(payload, file=sys.stderr)
    else:
        print(payload)


@app.command("mkdir")
def mkdir_command(
    name: str,
    parent_id: str = typer.Option(
        None,
        "--parent-id",
        envvar="GWS_CLI_DEFAULT_FOLDER_ID",
        help="My Drive parent folder ID (defaults to My Drive root)",
    ),
    exist_ok: bool = typer.Option(
        False,
        "--exist-ok",
        help="Return a single existing folder with the same name instead of failing",
    ),
) -> None:
    service = build_drive_write_service()
    try:
        result = mkdir_folder(
            service, name=name, parent_id=parent_id, exist_ok=exist_ok
        )
    except DriveError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None

    print(json.dumps(result, ensure_ascii=False))


@app.command("move")
def move_command(
    file_id: str,
    to: str = typer.Option(
        ...,
        "--to",
        help="Destination My Drive folder ID ('root' for My Drive root)",
    ),
    name: str = typer.Option(
        None, "--name", help="Rename to this display name while moving"
    ),
) -> None:
    service = build_drive_write_service()
    try:
        result = move_file(service, file_id=file_id, to_folder_id=to, name=name)
    except DriveError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except HttpError as e:
        print(f"Error: {e.resp.status} {e.resp.reason}", file=sys.stderr)
        raise typer.Exit(code=1) from None

    print(json.dumps(result, ensure_ascii=False))
