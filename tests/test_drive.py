from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from gws_cli.drive import (
    FOLDER_MIME,
    DriveUploadError,
    find_existing,
    guess_mime_type,
    upload_file,
    validate_folder,
)


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_service(
    get_return=None,
    list_return=None,
    create_return=None,
    update_return=None,
    revisions_list_return=None,
    revisions_list_side_effect=None,
):
    service = MagicMock()

    get_req = MagicMock()
    get_req.execute.return_value = get_return
    service.files.return_value.get.return_value = get_req

    list_req = MagicMock()
    list_req.execute.return_value = (
        list_return if list_return is not None else {"files": []}
    )
    service.files.return_value.list.return_value = list_req

    create_req = MagicMock()
    create_req.execute.return_value = create_return
    service.files.return_value.create.return_value = create_req

    update_req = MagicMock()
    update_req.execute.return_value = update_return
    service.files.return_value.update.return_value = update_req

    rev_req = MagicMock()
    if revisions_list_side_effect is not None:
        rev_req.execute.side_effect = revisions_list_side_effect
    else:
        rev_req.execute.return_value = (
            revisions_list_return
            if revisions_list_return is not None
            else {"revisions": []}
        )
    service.revisions.return_value.list.return_value = rev_req

    return service


def _make_tmp_file(tmp_path: Path, name: str = "foo.pptx") -> Path:
    p = tmp_path / name
    p.write_bytes(b"some content")
    return p


# --- guess_mime_type ---


def test_guess_mime_type_pptx():
    assert guess_mime_type(Path("x.pptx")) == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_guess_mime_type_pdf():
    assert guess_mime_type(Path("x.pdf")) == "application/pdf"


def test_guess_mime_type_unknown_returns_octet_stream():
    assert guess_mime_type(Path("x.unknownext")) == "application/octet-stream"


# --- validate_folder ---


def test_validate_folder_allows_my_drive_folder():
    service = _make_service(get_return={"id": "f1", "mimeType": FOLDER_MIME})
    validate_folder(service, "f1")


def test_validate_folder_rejects_shared_drive_folder():
    service = _make_service(
        get_return={"id": "f1", "mimeType": FOLDER_MIME, "driveId": "drive-xyz"}
    )
    with pytest.raises(DriveUploadError, match="shared drive"):
        validate_folder(service, "f1")


def test_validate_folder_rejects_non_folder_mimetype():
    service = _make_service(get_return={"id": "f1", "mimeType": "application/pdf"})
    with pytest.raises(DriveUploadError, match="not a folder"):
        validate_folder(service, "f1")


def test_validate_folder_requests_driveId_and_mimeType_fields():
    service = _make_service(get_return={"id": "f1", "mimeType": FOLDER_MIME})
    validate_folder(service, "f1")
    service.files.return_value.get.assert_called_once_with(
        fileId="f1",
        fields="id, driveId, mimeType",
    )


# --- find_existing ---


def test_find_existing_returns_empty_when_no_match():
    service = _make_service(list_return={"files": []})
    assert find_existing(service, "foo.pptx", "parent-1") == []


def test_find_existing_returns_matching_files():
    files = [{"id": "f1", "name": "foo.pptx", "mimeType": "x"}]
    service = _make_service(list_return={"files": files})
    assert find_existing(service, "foo.pptx", "parent-1") == files


def test_find_existing_query_contains_parent_name_and_not_trashed():
    service = _make_service(list_return={"files": []})
    find_existing(service, "foo.pptx", "parent-1")
    kwargs = service.files.return_value.list.call_args.kwargs
    q = kwargs["q"]
    assert "'parent-1' in parents" in q
    assert "name = 'foo.pptx'" in q
    assert "trashed = false" in q


def test_find_existing_escapes_single_quotes_in_name():
    service = _make_service(list_return={"files": []})
    find_existing(service, "it's.pptx", "parent-1")
    kwargs = service.files.return_value.list.call_args.kwargs
    assert "it\\'s.pptx" in kwargs["q"]


def test_find_existing_does_not_pass_supports_all_drives():
    service = _make_service(list_return={"files": []})
    find_existing(service, "foo.pptx", "parent-1")
    kwargs = service.files.return_value.list.call_args.kwargs
    assert "supportsAllDrives" not in kwargs


# --- upload_file: errors ---


def test_upload_file_errors_when_local_file_missing(tmp_path):
    service = _make_service()
    missing = tmp_path / "nope.pptx"
    with pytest.raises(DriveUploadError, match="not found"):
        upload_file(
            service,
            local_path=missing,
            name=None,
            folder_id=None,
            overwrite=False,
            keep_forever=False,
        )


def test_upload_file_errors_when_same_name_exists_without_overwrite(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={
            "files": [{"id": "existing-1", "name": "foo.pptx", "mimeType": "x"}]
        },
    )
    with pytest.raises(DriveUploadError, match="--overwrite"):
        upload_file(
            service,
            local_path=local,
            name=None,
            folder_id=None,
            overwrite=False,
            keep_forever=False,
        )


def test_upload_file_errors_when_multiple_matches_with_overwrite(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={
            "files": [
                {"id": "e1", "name": "foo.pptx"},
                {"id": "e2", "name": "foo.pptx"},
            ]
        },
    )
    with pytest.raises(DriveUploadError, match="Multiple files"):
        upload_file(
            service,
            local_path=local,
            name=None,
            folder_id=None,
            overwrite=True,
            keep_forever=False,
        )


def test_upload_file_errors_when_multiple_matches_without_overwrite(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={
            "files": [
                {"id": "e1", "name": "foo.pptx"},
                {"id": "e2", "name": "foo.pptx"},
            ]
        },
    )
    with pytest.raises(DriveUploadError, match="Multiple files"):
        upload_file(
            service,
            local_path=local,
            name=None,
            folder_id=None,
            overwrite=False,
            keep_forever=False,
        )


def test_upload_file_rejects_shared_drive_folder(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        get_return={"id": "f1", "mimeType": FOLDER_MIME, "driveId": "drive-x"},
    )
    with pytest.raises(DriveUploadError, match="shared drive"):
        upload_file(
            service,
            local_path=local,
            name=None,
            folder_id="f1",
            overwrite=False,
            keep_forever=False,
        )


# --- upload_file: create path ---


def test_upload_file_creates_new_when_no_existing(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": (
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            "webViewLink": "https://drive.google.com/file/d/new-1/view",
        },
    )
    result = upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    assert result["fileId"] == "new-1"
    assert result["action"] == "created"
    assert result["previousRevisionId"] is None
    assert result["webViewLink"] == "https://drive.google.com/file/d/new-1/view"


def test_upload_file_creates_in_root_when_no_folder_id(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["parents"] == ["root"]
    list_q = service.files.return_value.list.call_args.kwargs["q"]
    assert "'root' in parents" in list_q


def test_upload_file_uses_name_override(tmp_path):
    local = _make_tmp_file(tmp_path, name="foo.pptx")
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "custom.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name="custom.pptx",
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["name"] == "custom.pptx"
    list_q = service.files.return_value.list.call_args.kwargs["q"]
    assert "name = 'custom.pptx'" in list_q


def test_upload_file_uses_basename_when_name_missing(tmp_path):
    local = _make_tmp_file(tmp_path, name="doc-123.pdf")
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "doc-123.pdf",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["name"] == "doc-123.pdf"


def test_upload_file_sets_keep_revision_forever_when_flag_set(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=True,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["keepRevisionForever"] is True


def test_upload_file_does_not_set_keep_revision_forever_by_default(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["keepRevisionForever"] is False


def test_upload_file_validates_folder_when_folder_id_given(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        get_return={"id": "folder-1", "mimeType": FOLDER_MIME},
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id="folder-1",
        overwrite=False,
        keep_forever=False,
    )
    service.files.return_value.get.assert_called_once_with(
        fileId="folder-1",
        fields="id, driveId, mimeType",
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["parents"] == ["folder-1"]


def test_upload_file_skips_folder_validation_when_no_folder_id(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    service.files.return_value.get.assert_not_called()


def test_upload_file_create_does_not_pass_supports_all_drives(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": []},
        create_return={
            "id": "new-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=False,
        keep_forever=False,
    )
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert "supportsAllDrives" not in create_kwargs


# --- upload_file: update (overwrite) path ---


def test_upload_file_overwrites_when_single_match(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={
            "files": [{"id": "existing-1", "name": "foo.pptx", "mimeType": "x"}]
        },
        update_return={
            "id": "existing-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "https://drive.google.com/file/d/existing-1/view",
        },
        revisions_list_return={"revisions": [{"id": "rev-1"}, {"id": "rev-2"}]},
    )
    result = upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=True,
        keep_forever=False,
    )
    assert result["action"] == "updated"
    assert result["fileId"] == "existing-1"
    assert result["previousRevisionId"] == "rev-2"
    service.files.return_value.update.assert_called_once()
    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert update_kwargs["fileId"] == "existing-1"
    assert update_kwargs["keepRevisionForever"] is False


def test_upload_file_does_not_call_create_on_overwrite(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": [{"id": "existing-1", "name": "foo.pptx"}]},
        update_return={
            "id": "existing-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=True,
        keep_forever=False,
    )
    service.files.return_value.create.assert_not_called()


def test_upload_file_overwrite_sets_keep_revision_forever(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": [{"id": "existing-1", "name": "foo.pptx"}]},
        update_return={
            "id": "existing-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
    )
    upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=True,
        keep_forever=True,
    )
    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert update_kwargs["keepRevisionForever"] is True


def test_upload_file_overwrite_previous_revision_id_none_when_revisions_empty(
    tmp_path,
):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": [{"id": "existing-1", "name": "foo.pptx"}]},
        update_return={
            "id": "existing-1",
            "name": "foo.pptx",
            "mimeType": "x",
            "webViewLink": "",
        },
        revisions_list_return={"revisions": []},
    )
    result = upload_file(
        service,
        local_path=local,
        name=None,
        folder_id=None,
        overwrite=True,
        keep_forever=False,
    )
    assert result["previousRevisionId"] is None


def test_upload_file_overwrite_fails_closed_when_revisions_list_errors(tmp_path):
    local = _make_tmp_file(tmp_path)
    service = _make_service(
        list_return={"files": [{"id": "existing-1", "name": "foo.pptx"}]},
        revisions_list_side_effect=_make_http_error(500, "Internal", b""),
    )
    with pytest.raises(DriveUploadError, match="rollback"):
        upload_file(
            service,
            local_path=local,
            name=None,
            folder_id=None,
            overwrite=True,
            keep_forever=False,
        )
    service.files.return_value.update.assert_not_called()
