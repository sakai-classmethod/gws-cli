import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from gws_cli import drive as drive_mod
from gws_cli.drive import FOLDER_MIME, DriveError, DriveMkdirError, app, mkdir_folder


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_service(get_return=None, list_return=None, create_return=None):
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

    return service


def _created_folder(file_id="new1", name="reports", parents=("0Aroot",)):
    return {
        "id": file_id,
        "name": name,
        "mimeType": FOLDER_MIME,
        "webViewLink": f"https://drive.google.com/drive/folders/{file_id}",
        "parents": list(parents),
    }


def test_mkdir_error_is_a_drive_error():
    assert issubclass(DriveMkdirError, DriveError)


def test_mkdir_creates_folder_under_root_when_parent_omitted():
    service = _make_service(create_return=_created_folder())

    result = mkdir_folder(service, "reports", parent_id=None, exist_ok=False)

    service.files.return_value.get.assert_not_called()
    list_kwargs = service.files.return_value.list.call_args.kwargs
    assert "'root' in parents" in list_kwargs["q"]
    assert "name = 'reports'" in list_kwargs["q"]
    create_kwargs = service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"] == {
        "name": "reports",
        "mimeType": FOLDER_MIME,
        "parents": ["root"],
    }
    assert create_kwargs["fields"] == "id, name, mimeType, webViewLink, parents"
    assert "supportsAllDrives" not in create_kwargs
    assert result == {
        "fileId": "new1",
        "name": "reports",
        "mimeType": FOLDER_MIME,
        "webViewLink": "https://drive.google.com/drive/folders/new1",
        "parentId": "0Aroot",
        "action": "created",
    }


def test_mkdir_validates_explicit_parent_as_my_drive_folder():
    service = _make_service(
        get_return={"id": "p1", "mimeType": FOLDER_MIME},
        create_return=_created_folder(parents=("p1",)),
    )

    result = mkdir_folder(service, "reports", parent_id="p1", exist_ok=False)

    get_kwargs = service.files.return_value.get.call_args.kwargs
    assert get_kwargs["fileId"] == "p1"
    assert "'p1' in parents" in service.files.return_value.list.call_args.kwargs["q"]
    assert service.files.return_value.create.call_args.kwargs["body"]["parents"] == [
        "p1"
    ]
    assert result["parentId"] == "p1"


def test_mkdir_falls_back_to_requested_parent_when_response_lacks_parents():
    created = _created_folder()
    del created["parents"]
    service = _make_service(create_return=created)

    result = mkdir_folder(service, "reports", parent_id=None, exist_ok=False)

    assert result["parentId"] == "root"


def test_mkdir_rejects_shared_drive_parent():
    service = _make_service(
        get_return={"id": "p1", "mimeType": FOLDER_MIME, "driveId": "d1"}
    )

    with pytest.raises(DriveError, match="shared drive"):
        mkdir_folder(service, "reports", parent_id="p1", exist_ok=False)

    service.files.return_value.create.assert_not_called()


def test_mkdir_exist_ok_returns_existing_folder_without_creating():
    service = _make_service(
        list_return={
            "files": [{"id": "old1", "name": "reports", "mimeType": FOLDER_MIME}]
        },
        get_return=_created_folder(file_id="old1"),
    )

    result = mkdir_folder(service, "reports", parent_id=None, exist_ok=True)

    service.files.return_value.create.assert_not_called()
    get_kwargs = service.files.return_value.get.call_args.kwargs
    assert get_kwargs == {
        "fileId": "old1",
        "fields": "id, name, mimeType, webViewLink, parents",
    }
    assert result == {
        "fileId": "old1",
        "name": "reports",
        "mimeType": FOLDER_MIME,
        "webViewLink": "https://drive.google.com/drive/folders/old1",
        "parentId": "0Aroot",
        "action": "existing",
    }


def test_mkdir_exist_ok_rejects_same_named_non_folder():
    service = _make_service(
        list_return={
            "files": [{"id": "f1", "name": "reports", "mimeType": "application/pdf"}]
        }
    )

    with pytest.raises(DriveMkdirError, match="exists but is not a folder"):
        mkdir_folder(service, "reports", parent_id=None, exist_ok=True)

    service.files.return_value.create.assert_not_called()


def test_mkdir_without_exist_ok_rejects_existing_name():
    service = _make_service(
        list_return={
            "files": [{"id": "old1", "name": "reports", "mimeType": FOLDER_MIME}]
        }
    )

    with pytest.raises(DriveMkdirError) as excinfo:
        mkdir_folder(service, "reports", parent_id=None, exist_ok=False)

    message = str(excinfo.value)
    assert "already exists" in message
    assert "old1" in message
    assert "--exist-ok" in message
    service.files.return_value.create.assert_not_called()


@pytest.mark.parametrize("exist_ok", [False, True])
def test_mkdir_rejects_multiple_same_named_entries(exist_ok):
    service = _make_service(
        list_return={
            "files": [
                {"id": "a1", "name": "reports", "mimeType": FOLDER_MIME},
                {"id": "a2", "name": "reports", "mimeType": FOLDER_MIME},
            ]
        }
    )

    with pytest.raises(DriveMkdirError) as excinfo:
        mkdir_folder(service, "reports", parent_id=None, exist_ok=exist_ok)

    message = str(excinfo.value)
    assert "Multiple" in message
    assert "a1" in message
    assert "a2" in message
    service.files.return_value.create.assert_not_called()


def test_cli_mkdir_emits_json_and_reads_parent_from_env(monkeypatch):
    service = _make_service(
        get_return={"id": "envp", "mimeType": FOLDER_MIME},
        create_return=_created_folder(name="議事録", parents=("envp",)),
    )
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)
    monkeypatch.setenv("GWS_CLI_DEFAULT_FOLDER_ID", "envp")

    result = CliRunner().invoke(app, ["mkdir", "議事録", "--exist-ok"])

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert "議事録" in lines[0]
    payload = json.loads(lines[0])
    assert payload["parentId"] == "envp"
    assert payload["action"] == "created"


def test_cli_mkdir_explicit_parent_id_overrides_env(monkeypatch):
    service = _make_service(
        get_return={"id": "cli-p", "mimeType": FOLDER_MIME},
        create_return=_created_folder(parents=("cli-p",)),
    )
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)

    result = CliRunner().invoke(
        app,
        ["mkdir", "reports", "--parent-id", "cli-p"],
        env={"GWS_CLI_DEFAULT_FOLDER_ID": "envp"},
    )

    assert result.exit_code == 0, result.stderr
    assert service.files.return_value.get.call_args.kwargs["fileId"] == "cli-p"
    assert service.files.return_value.create.call_args.kwargs["body"]["parents"] == [
        "cli-p"
    ]
    assert json.loads(result.stdout)["parentId"] == "cli-p"


def test_cli_mkdir_reports_drive_error_and_exits_nonzero(monkeypatch):
    service = _make_service(
        list_return={
            "files": [{"id": "old1", "name": "reports", "mimeType": FOLDER_MIME}]
        }
    )
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)
    monkeypatch.delenv("GWS_CLI_DEFAULT_FOLDER_ID", raising=False)

    result = CliRunner().invoke(app, ["mkdir", "reports"])

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert "already exists" in result.stderr
    assert result.stdout == ""


def test_cli_mkdir_reports_http_error_and_exits_nonzero(monkeypatch):
    service = _make_service()
    service.files.return_value.create.return_value.execute.side_effect = (
        _make_http_error(403, "Forbidden", b"{}")
    )
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)
    monkeypatch.delenv("GWS_CLI_DEFAULT_FOLDER_ID", raising=False)

    result = CliRunner().invoke(app, ["mkdir", "reports"])

    assert result.exit_code == 1
    assert "Error: 403 Forbidden" in result.stderr
