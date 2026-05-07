import io
import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from gws_cli import drive as drive_mod
from gws_cli.drive import (
    DriveDownloadError,
    app,
    check_rejected_mime,
    download_file,
    is_native_mime,
    resolve_export,
    resolve_local_path,
    sanitize_filename,
)


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_service_for_download(meta, *, get_media_body=b"", export_body=b""):
    service = MagicMock()

    get_req = MagicMock()
    get_req.execute.return_value = meta
    service.files.return_value.get.return_value = get_req

    media_req = MagicMock()
    media_req.execute.return_value = get_media_body
    media_req._download_body = get_media_body
    service.files.return_value.get_media.return_value = media_req

    export_req = MagicMock()
    export_req.execute.return_value = export_body
    export_req._download_body = export_body
    service.files.return_value.export_media.return_value = export_req

    return service


@pytest.fixture
def patch_stream(monkeypatch):
    def _fake(request, fd):
        body = getattr(request, "_download_body", b"")
        fd.write(body)
        try:
            return fd.tell()
        except OSError:
            return len(body)

    monkeypatch.setattr(drive_mod, "_stream_download", _fake)
    return _fake


# --- is_native_mime ---


def test_is_native_mime_true_for_google_apps():
    assert is_native_mime("application/vnd.google-apps.document") is True


def test_is_native_mime_false_for_pdf():
    assert is_native_mime("application/pdf") is False


# --- check_rejected_mime ---


@pytest.mark.parametrize(
    "mime",
    [
        "application/vnd.google-apps.folder",
        "application/vnd.google-apps.shortcut",
        "application/vnd.google-apps.form",
        "application/vnd.google-apps.site",
        "application/vnd.google-apps.audio",
        "application/vnd.google-apps.video",
        "video/mp4",
        "audio/mpeg",
    ],
)
def test_check_rejected_mime_raises(mime):
    with pytest.raises(DriveDownloadError):
        check_rejected_mime(mime)


@pytest.mark.parametrize(
    "mime",
    [
        "application/pdf",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
        "image/png",
    ],
)
def test_check_rejected_mime_allows(mime):
    check_rejected_mime(mime)


# --- resolve_export ---


def test_resolve_export_returns_none_for_blob_without_format():
    assert resolve_export(None, "application/pdf") is None


def test_resolve_export_rejects_format_for_blob():
    with pytest.raises(DriveDownloadError, match="only valid for Google native"):
        resolve_export("pdf", "application/pdf")


def test_resolve_export_default_for_docs():
    mime, ext = resolve_export(None, "application/vnd.google-apps.document")
    assert ext == ".docx"
    assert "wordprocessingml" in mime


def test_resolve_export_default_for_sheets():
    mime, ext = resolve_export(None, "application/vnd.google-apps.spreadsheet")
    assert ext == ".xlsx"


def test_resolve_export_default_for_slides():
    mime, ext = resolve_export(None, "application/vnd.google-apps.presentation")
    assert ext == ".pptx"


def test_resolve_export_default_for_drawing():
    mime, ext = resolve_export(None, "application/vnd.google-apps.drawing")
    assert (mime, ext) == ("image/png", ".png")


def test_resolve_export_shortcut_pdf():
    mime, ext = resolve_export("pdf", "application/vnd.google-apps.document")
    assert (mime, ext) == ("application/pdf", ".pdf")


def test_resolve_export_accepts_explicit_mime():
    mime, ext = resolve_export(
        "application/pdf", "application/vnd.google-apps.document"
    )
    assert mime == "application/pdf"
    assert ext == ".pdf"


def test_resolve_export_unknown_shortcut_errors():
    with pytest.raises(DriveDownloadError, match="Unknown --export"):
        resolve_export("doesnotexist", "application/vnd.google-apps.document")


def test_resolve_export_unknown_native_without_format_errors():
    with pytest.raises(DriveDownloadError, match="No default export"):
        resolve_export(None, "application/vnd.google-apps.colaboratory")


# --- sanitize_filename ---


def test_sanitize_filename_replaces_slash():
    assert sanitize_filename("a/b") == "a_b"


def test_sanitize_filename_replaces_null():
    assert sanitize_filename("a\0b") == "a_b"


def test_sanitize_filename_keeps_unicode():
    assert sanitize_filename("会議メモ.docx") == "会議メモ.docx"


# --- resolve_local_path ---


def test_resolve_local_path_omitted_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = resolve_local_path(None, "report", ".docx")
    assert p == tmp_path / "report.docx"


def test_resolve_local_path_directory_appends_drive_name(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    p = resolve_local_path(str(sub), "report", ".docx")
    assert p == sub / "report.docx"


def test_resolve_local_path_explicit_file_kept_as_is(tmp_path):
    target = tmp_path / "out.docx"
    p = resolve_local_path(str(target), "report", ".docx")
    assert p == target


def test_resolve_local_path_trailing_slash_missing_dir_errors(tmp_path):
    missing = str(tmp_path / "missing") + "/"
    with pytest.raises(DriveDownloadError, match="Directory not found"):
        resolve_local_path(missing, "report", ".docx")


def test_resolve_local_path_trailing_slash_existing_dir_appends_name(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    p = resolve_local_path(str(sub) + "/", "report", ".docx")
    assert p == sub / "report.docx"


def test_resolve_local_path_does_not_double_extension(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    p = resolve_local_path(str(sub), "report.docx", ".docx")
    assert p == sub / "report.docx"


def test_resolve_local_path_blob_no_extension_added(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    p = resolve_local_path(str(sub), "raw.bin", "")
    assert p == sub / "raw.bin"


def test_resolve_local_path_sanitizes_drive_name(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    p = resolve_local_path(str(sub), "a/b", ".docx")
    assert p == sub / "a_b.docx"


# --- download_file: blob path ---


def test_download_file_blob_writes_file_and_returns_metadata(tmp_path, patch_stream):
    meta = {
        "id": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
        "size": "1234",
        "headRevisionId": "rev1",
        "modifiedTime": "2026-05-01T00:00:00Z",
        "md5Checksum": "deadbeef",
        "webViewLink": "https://drive.google.com/file/d/f1/view",
    }
    body = b"PDF-DATA"
    service = _make_service_for_download(meta, get_media_body=body)
    dest = tmp_path / "out.pdf"

    result = download_file(
        service,
        file_id="f1",
        dest=str(dest),
        export=None,
        overwrite=False,
    )

    assert dest.exists()
    assert dest.read_bytes() == body
    assert result["fileId"] == "f1"
    assert result["source"] == "media"
    assert result["exportMime"] is None
    assert result["bytesWritten"] == len(body)
    assert result["md5Checksum"] == "deadbeef"
    assert result["localPath"] == str(dest)
    assert result["action"] == "downloaded"
    service.files.return_value.get_media.assert_called_once_with(
        fileId="f1", supportsAllDrives=True
    )


def test_download_file_passes_supports_all_drives_to_get(tmp_path, patch_stream):
    meta = {
        "id": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
    }
    service = _make_service_for_download(meta, get_media_body=b"x")
    download_file(
        service,
        file_id="f1",
        dest=str(tmp_path / "out.pdf"),
        export=None,
        overwrite=False,
    )
    get_kwargs = service.files.return_value.get.call_args.kwargs
    assert get_kwargs["supportsAllDrives"] is True
    assert "id" in get_kwargs["fields"]
    assert "headRevisionId" in get_kwargs["fields"]


def test_download_file_blob_omits_md5_when_metadata_lacks_it(tmp_path, patch_stream):
    meta = {
        "id": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
    }
    service = _make_service_for_download(meta, get_media_body=b"x")
    result = download_file(
        service,
        file_id="f1",
        dest=str(tmp_path / "out.pdf"),
        export=None,
        overwrite=False,
    )
    assert result["md5Checksum"] is None


# --- download_file: native export path ---


def test_download_file_native_uses_export_media_with_default_mime(
    tmp_path, patch_stream
):
    meta = {
        "id": "doc1",
        "name": "Project Plan",
        "mimeType": "application/vnd.google-apps.document",
    }
    service = _make_service_for_download(meta, export_body=b"DOCX-BYTES")
    sub = tmp_path / "out"
    sub.mkdir()

    result = download_file(
        service,
        file_id="doc1",
        dest=str(sub),
        export=None,
        overwrite=False,
    )

    expected_path = sub / "Project Plan.docx"
    assert expected_path.exists()
    assert expected_path.read_bytes() == b"DOCX-BYTES"
    assert result["source"] == "export"
    assert result["exportMime"].endswith("wordprocessingml.document")
    assert result["md5Checksum"] is None  # export should always be null
    export_kwargs = service.files.return_value.export_media.call_args.kwargs
    assert export_kwargs["fileId"] == "doc1"
    assert "wordprocessingml" in export_kwargs["mimeType"]
    # supportsAllDrives must NOT be passed to export_media
    assert "supportsAllDrives" not in export_kwargs


def test_download_file_native_with_export_shortcut(tmp_path, patch_stream):
    meta = {
        "id": "doc1",
        "name": "Plan",
        "mimeType": "application/vnd.google-apps.document",
    }
    service = _make_service_for_download(meta, export_body=b"PDF")

    result = download_file(
        service,
        file_id="doc1",
        dest=str(tmp_path),
        export="pdf",
        overwrite=False,
    )
    assert (tmp_path / "Plan.pdf").read_bytes() == b"PDF"
    assert result["exportMime"] == "application/pdf"


# --- download_file: rejection rules ---


def test_download_file_rejects_folder(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "x", "mimeType": "application/vnd.google-apps.folder"}
    service = _make_service_for_download(meta)
    with pytest.raises(DriveDownloadError):
        download_file(
            service,
            file_id="f1",
            dest=str(tmp_path / "o"),
            export=None,
            overwrite=False,
        )


def test_download_file_rejects_video(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "x", "mimeType": "video/mp4"}
    service = _make_service_for_download(meta)
    with pytest.raises(DriveDownloadError, match="video/audio"):
        download_file(
            service,
            file_id="f1",
            dest=str(tmp_path / "o"),
            export=None,
            overwrite=False,
        )


def test_download_file_rejects_audio(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "x", "mimeType": "audio/mpeg"}
    service = _make_service_for_download(meta)
    with pytest.raises(DriveDownloadError, match="video/audio"):
        download_file(
            service,
            file_id="f1",
            dest=str(tmp_path / "o"),
            export=None,
            overwrite=False,
        )


def test_download_file_rejects_native_shortcut(tmp_path, patch_stream):
    meta = {
        "id": "f1",
        "name": "x",
        "mimeType": "application/vnd.google-apps.shortcut",
    }
    service = _make_service_for_download(meta)
    with pytest.raises(DriveDownloadError):
        download_file(
            service,
            file_id="f1",
            dest=str(tmp_path / "o"),
            export=None,
            overwrite=False,
        )


# --- download_file: overwrite handling ---


def test_download_file_errors_when_local_exists_without_overwrite(
    tmp_path, patch_stream
):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta, get_media_body=b"x")
    dest = tmp_path / "report.pdf"
    dest.write_bytes(b"existing")

    with pytest.raises(DriveDownloadError, match="already exists"):
        download_file(
            service,
            file_id="f1",
            dest=str(dest),
            export=None,
            overwrite=False,
        )
    # original content untouched
    assert dest.read_bytes() == b"existing"


def test_download_file_overwrites_when_flag_set(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta, get_media_body=b"NEW")
    dest = tmp_path / "report.pdf"
    dest.write_bytes(b"OLD")

    download_file(
        service,
        file_id="f1",
        dest=str(dest),
        export=None,
        overwrite=True,
    )
    assert dest.read_bytes() == b"NEW"


def test_download_file_atomic_no_partial_on_failure(tmp_path, monkeypatch):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta, get_media_body=b"x")
    dest = tmp_path / "report.pdf"

    def boom(request, fd):
        fd.write(b"partial")
        raise RuntimeError("network died")

    monkeypatch.setattr(drive_mod, "_stream_download", boom)

    with pytest.raises(RuntimeError, match="network died"):
        download_file(
            service,
            file_id="f1",
            dest=str(dest),
            export=None,
            overwrite=False,
        )
    assert not dest.exists()
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"unexpected leftovers: {leftovers}"


# --- download_file: stdout path ---


def test_download_file_stdout_writes_bytes_to_buffer(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta, get_media_body=b"PDF-DATA")
    buf = io.BytesIO()

    result = download_file(
        service,
        file_id="f1",
        dest="-",
        export=None,
        overwrite=False,
        stdout_buffer=buf,
        stdout_is_tty=False,
    )
    assert buf.getvalue() == b"PDF-DATA"
    assert result["localPath"] is None
    assert result["bytesWritten"] == len(b"PDF-DATA")


def test_download_file_stdout_refuses_tty(tmp_path, patch_stream):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta, get_media_body=b"x")
    buf = io.BytesIO()
    with pytest.raises(DriveDownloadError, match="TTY"):
        download_file(
            service,
            file_id="f1",
            dest="-",
            export=None,
            overwrite=False,
            stdout_buffer=buf,
            stdout_is_tty=True,
        )


# --- download_file: export 10MB error mapping ---


def test_download_file_translates_export_too_large(tmp_path, monkeypatch):
    meta = {
        "id": "doc1",
        "name": "Big",
        "mimeType": "application/vnd.google-apps.document",
    }
    service = _make_service_for_download(meta)

    err = _make_http_error(
        403,
        "Forbidden",
        b'{"error":{"message":"This file is too large to be exported."}}',
    )

    def boom(request, fd):
        raise err

    monkeypatch.setattr(drive_mod, "_stream_download", boom)

    with pytest.raises(DriveDownloadError, match="10MB"):
        download_file(
            service,
            file_id="doc1",
            dest=str(tmp_path / "out.docx"),
            export=None,
            overwrite=False,
        )


def test_download_file_passes_through_other_http_errors(tmp_path, monkeypatch):
    meta = {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"}
    service = _make_service_for_download(meta)

    err = _make_http_error(500, "Internal", b'{"error":{"message":"oops"}}')

    def boom(request, fd):
        raise err

    monkeypatch.setattr(drive_mod, "_stream_download", boom)

    with pytest.raises(HttpError):
        download_file(
            service,
            file_id="f1",
            dest=str(tmp_path / "report.pdf"),
            export=None,
            overwrite=False,
        )


# --- download_file: extension mismatch warning ---


def test_download_file_warns_on_extension_mismatch(
    tmp_path, patch_stream, capsys
):
    meta = {
        "id": "doc1",
        "name": "Plan",
        "mimeType": "application/vnd.google-apps.document",
    }
    service = _make_service_for_download(meta, export_body=b"DOCX")
    dest = tmp_path / "out.pdf"
    download_file(
        service,
        file_id="doc1",
        dest=str(dest),
        export=None,
        overwrite=False,
    )
    err = capsys.readouterr().err
    assert "differs from" in err


# --- CLI integration via Typer ---


def test_cli_download_file_path_emits_json_to_stdout(
    tmp_path, monkeypatch, patch_stream
):
    meta = {
        "id": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
        "size": "10",
    }
    service = _make_service_for_download(meta, get_media_body=b"PDF-BYTES")
    monkeypatch.setattr(drive_mod, "build_drive_service", lambda: service)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["download", "f1"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["fileId"] == "f1"
    assert payload["localPath"].endswith("report.pdf")
    assert (tmp_path / "report.pdf").read_bytes() == b"PDF-BYTES"


def test_cli_download_error_exits_nonzero(tmp_path, monkeypatch, patch_stream):
    meta = {
        "id": "f1",
        "name": "x",
        "mimeType": "application/vnd.google-apps.folder",
    }
    service = _make_service_for_download(meta)
    monkeypatch.setattr(drive_mod, "build_drive_service", lambda: service)

    runner = CliRunner()
    result = runner.invoke(app, ["download", "f1", str(tmp_path / "out")])
    assert result.exit_code == 1
