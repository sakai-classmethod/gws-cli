import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from gws_cli import drive as drive_mod
from gws_cli.drive import FOLDER_MIME, DriveError, DriveMoveError, app, move_file

TARGET_FIELDS = "id, name, mimeType, parents, driveId, webViewLink"


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def _make_service(target, list_return=None, update_return=None, dest_meta=None):
    service = MagicMock()
    dest = dest_meta if dest_meta is not None else {"mimeType": FOLDER_MIME}

    def _get(fileId, fields):
        req = MagicMock()
        req.execute.return_value = target if fields == TARGET_FIELDS else dest
        return req

    service.files.return_value.get.side_effect = _get

    list_req = MagicMock()
    list_req.execute.return_value = (
        list_return if list_return is not None else {"files": []}
    )
    service.files.return_value.list.return_value = list_req

    update_req = MagicMock()
    update_req.execute.return_value = update_return
    service.files.return_value.update.return_value = update_req

    return service


def _target(parents=("src1",), name="report.pdf", **extra):
    return {
        "id": "f1",
        "name": name,
        "mimeType": "application/pdf",
        "parents": list(parents),
        "webViewLink": "https://drive.google.com/file/d/f1/view",
        **extra,
    }


def _updated(name="report.pdf", parents=("dst1",)):
    return {
        "id": "f1",
        "name": name,
        "mimeType": "application/pdf",
        "parents": list(parents),
        "webViewLink": "https://drive.google.com/file/d/f1/view",
    }


def test_move_error_is_a_drive_error():
    assert issubclass(DriveMoveError, DriveError)


def test_move_reparents_file_into_destination():
    service = _make_service(_target(), update_return=_updated())

    result = move_file(service, "f1", "dst1", name=None)

    get_calls = service.files.return_value.get.call_args_list
    assert get_calls[0].kwargs["fileId"] == "dst1"
    assert get_calls[1].kwargs == {"fileId": "f1", "fields": TARGET_FIELDS}
    list_q = service.files.return_value.list.call_args.kwargs["q"]
    assert "'dst1' in parents" in list_q
    assert "name = 'report.pdf'" in list_q
    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert update_kwargs == {
        "fileId": "f1",
        "addParents": "dst1",
        "removeParents": "src1",
        "body": {},
        "fields": "id, name, mimeType, parents, webViewLink",
    }
    assert result == {
        "fileId": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
        "webViewLink": "https://drive.google.com/file/d/f1/view",
        "parentId": "dst1",
        "previousParentIds": ["src1"],
        "action": "moved",
    }


def test_move_with_name_renames_in_the_same_update():
    service = _make_service(_target(), update_return=_updated(name="final.pdf"))

    result = move_file(service, "f1", "dst1", name="final.pdf")

    assert "name = 'final.pdf'" in service.files.return_value.list.call_args.kwargs["q"]
    service.files.return_value.update.assert_called_once()
    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert update_kwargs["body"] == {"name": "final.pdf"}
    assert result["name"] == "final.pdf"
    assert result["action"] == "moved"


def test_move_rename_within_current_parent_keeps_parent():
    service = _make_service(
        _target(parents=("dst1",)),
        update_return=_updated(name="final.pdf"),
    )

    result = move_file(service, "f1", "dst1", name="final.pdf")

    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert "addParents" not in update_kwargs
    assert "removeParents" not in update_kwargs
    assert update_kwargs["body"] == {"name": "final.pdf"}
    assert result["action"] == "moved"


def test_move_parentless_file_omits_remove_parents():
    service = _make_service(_target(parents=()), update_return=_updated())

    result = move_file(service, "f1", "dst1", name=None)

    update_kwargs = service.files.return_value.update.call_args.kwargs
    assert "removeParents" not in update_kwargs
    assert result["previousParentIds"] == []


def test_move_is_unchanged_when_already_in_destination_with_same_name():
    service = _make_service(
        _target(parents=("dst1",)),
        list_return={"files": [{"id": "f1", "name": "report.pdf"}]},
    )

    result = move_file(service, "f1", "dst1", name="report.pdf")

    service.files.return_value.update.assert_not_called()
    assert result == {
        "fileId": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
        "webViewLink": "https://drive.google.com/file/d/f1/view",
        "parentId": "dst1",
        "previousParentIds": ["dst1"],
        "action": "unchanged",
    }


def test_move_rejects_non_folder_destination():
    service = _make_service(_target(), dest_meta={"mimeType": "application/pdf"})

    with pytest.raises(DriveError, match="not a folder"):
        move_file(service, "f1", "dst1", name=None)

    service.files.return_value.update.assert_not_called()


def test_move_rejects_target_on_shared_drive():
    service = _make_service(_target(driveId="d1"))

    with pytest.raises(DriveMoveError, match="shared drive"):
        move_file(service, "f1", "dst1", name=None)

    service.files.return_value.update.assert_not_called()


def test_move_rejects_name_collision_in_destination():
    service = _make_service(
        _target(),
        list_return={
            "files": [
                {"id": "f1", "name": "report.pdf"},
                {"id": "other1", "name": "report.pdf"},
            ]
        },
    )

    with pytest.raises(DriveMoveError) as excinfo:
        move_file(service, "f1", "dst1", name=None)

    message = str(excinfo.value)
    assert "already exists in destination" in message
    assert "other1" in message
    assert "--name" in message
    service.files.return_value.update.assert_not_called()


def test_cli_move_emits_json_to_stdout(monkeypatch):
    service = _make_service(_target(), update_return=_updated())
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)

    result = CliRunner().invoke(app, ["move", "f1", "--to", "dst1"])

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["action"] == "moved"
    assert payload["parentId"] == "dst1"


def test_cli_move_requires_destination():
    result = CliRunner().invoke(app, ["move", "f1"])

    # rich は端末幅に応じて usage 文を省略するので、文言ではなく終了コードで判定する
    assert result.exit_code == 2


def test_cli_move_reports_drive_error_and_exits_nonzero(monkeypatch):
    service = _make_service(_target(driveId="d1"))
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)

    result = CliRunner().invoke(app, ["move", "f1", "--to", "dst1"])

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert "shared drive" in result.stderr
    assert result.stdout == ""


def test_cli_move_reports_http_error_and_exits_nonzero(monkeypatch):
    service = _make_service(_target())
    service.files.return_value.update.return_value.execute.side_effect = (
        _make_http_error(400, "Bad Request", b"{}")
    )
    monkeypatch.setattr(drive_mod, "build_drive_write_service", lambda: service)

    result = CliRunner().invoke(app, ["move", "f1", "--to", "dst1"])

    assert result.exit_code == 1
    assert "Error: 400 Bad Request" in result.stderr
