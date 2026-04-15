from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from gws_cli.docs import extract_section, get_doc_content


def _make_http_error(status, reason, content):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, content)


def test_get_doc_content_plain_returns_decoded_text():
    service = MagicMock()
    service.files.return_value.export.return_value.execute.return_value = (
        b"plain text body"
    )

    result = get_doc_content(service, doc_id="doc-123", fmt="plain")

    assert result == "plain text body"
    service.files.return_value.export.assert_called_once_with(
        fileId="doc-123",
        mimeType="text/plain",
    )


def test_get_doc_content_md_converts_html_to_markdown():
    service = MagicMock()
    service.files.return_value.export.return_value.execute.return_value = (
        b"<p>Hello <strong>world</strong></p>"
    )

    result = get_doc_content(service, doc_id="doc-456", fmt="md")

    assert "Hello" in result
    assert "world" in result
    service.files.return_value.export.assert_called_once_with(
        fileId="doc-456",
        mimeType="text/html",
    )


def test_get_doc_content_md_strips_style_attributes():
    service = MagicMock()
    service.files.return_value.export.return_value.execute.return_value = (
        b"<p><span style='font-weight:700;color:#000'>important</span> normal</p>"
    )

    result = get_doc_content(service, doc_id="doc-789", fmt="md")

    assert "important" in result
    assert "style=" not in result


def test_get_doc_content_propagates_404():
    service = MagicMock()
    service.files.return_value.export.return_value.execute.side_effect = (
        _make_http_error(404, "Not Found", b"not found")
    )

    with pytest.raises(HttpError) as exc_info:
        get_doc_content(service, doc_id="missing", fmt="plain")

    assert exc_info.value.resp.status == 404


SAMPLE_DOC = """\
📝 メモ
4月 15, 2026
サンプル株式会社内部MTG

概要
プロジェクトの進め方と役割分担を定義しました。

📖 文字起こし
2026年4月15日
サンプル株式会社内部MTG - 文字起こし
00:00:00

話者A: お疲れ様です。
話者B: よいしょ。はい。
"""


def test_extract_section_transcript():
    result = extract_section(SAMPLE_DOC, "transcript")

    assert "文字起こし" in result
    assert "話者A: お疲れ様です。" in result
    assert "📝 メモ" not in result
    assert "概要" not in result


def test_extract_section_notes():
    result = extract_section(SAMPLE_DOC, "notes")

    assert "メモ" in result
    assert "概要" in result
    assert "話者A: お疲れ様です。" not in result


def test_extract_section_none_returns_full():
    result = extract_section(SAMPLE_DOC, None)

    assert result == SAMPLE_DOC


def test_extract_section_not_found_returns_full():
    result = extract_section("no sections here", "transcript")

    assert result == "no sections here"


def test_get_doc_content_propagates_403():
    service = MagicMock()
    service.files.return_value.export.return_value.execute.side_effect = (
        _make_http_error(403, "Forbidden", b"forbidden")
    )

    with pytest.raises(HttpError) as exc_info:
        get_doc_content(service, doc_id="restricted", fmt="md")

    assert exc_info.value.resp.status == 403
