import pytest

from gws_cli.calendar import (
    build_links,
    extract_links_from_attachments,
    extract_links_from_description,
    merge_links,
    parse_drive_url,
)


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://docs.google.com/document/d/abc123/edit",
            ("abc123", "application/vnd.google-apps.document"),
        ),
        (
            "https://docs.google.com/spreadsheets/d/SH-1_abc/edit#gid=0",
            ("SH-1_abc", "application/vnd.google-apps.spreadsheet"),
        ),
        (
            "https://docs.google.com/presentation/d/PRID/edit?usp=sharing",
            ("PRID", "application/vnd.google-apps.presentation"),
        ),
        (
            "https://docs.google.com/forms/d/FRID/viewform",
            ("FRID", "application/vnd.google-apps.form"),
        ),
        (
            "https://docs.google.com/drawings/d/DRID/edit",
            ("DRID", "application/vnd.google-apps.drawing"),
        ),
        (
            "https://drive.google.com/file/d/FILE-1/view",
            ("FILE-1", None),
        ),
        (
            "https://drive.google.com/drive/folders/FOLD-1",
            ("FOLD-1", "application/vnd.google-apps.folder"),
        ),
        (
            "https://drive.google.com/drive/u/0/folders/FOLD-abc",
            ("FOLD-abc", "application/vnd.google-apps.folder"),
        ),
        (
            "http://docs.google.com/document/d/abc123/edit",
            ("abc123", "application/vnd.google-apps.document"),
        ),
    ],
)
def test_parse_drive_url_recognises_native_and_drive_urls(url, expected):
    assert parse_drive_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/orgs/foo/projects/1",
        "https://meet.google.com/abc-defg-hij",
        "https://classmethod.enterprise.slack.com/archives/C04S5L5NJ7L",
        "https://docs.google.com/",
        "not a url",
    ],
)
def test_parse_drive_url_returns_none_for_non_drive_urls(url):
    assert parse_drive_url(url) is None


def test_extract_links_from_attachments_basic():
    attachments = [
        {
            "fileId": "1aBcD",
            "title": "Gemini によるメモ",
            "fileUrl": "https://docs.google.com/document/d/1aBcD/edit?usp=meet",
            "mimeType": "application/vnd.google-apps.document",
        }
    ]

    result = extract_links_from_attachments(attachments)

    assert result == [
        {
            "url": "https://docs.google.com/document/d/1aBcD/edit?usp=meet",
            "fileId": "1aBcD",
            "mimeType": "application/vnd.google-apps.document",
            "title": "Gemini によるメモ",
            "sources": ["event.attachments"],
            "sourceUrls": ["https://docs.google.com/document/d/1aBcD/edit?usp=meet"],
        }
    ]


def test_extract_links_from_attachments_falls_back_when_no_fileid_or_mime():
    attachments = [{"title": "x", "fileUrl": "https://example.com/foo"}]

    result = extract_links_from_attachments(attachments)

    assert result[0]["fileId"] is None
    assert result[0]["mimeType"] is None
    assert result[0]["url"] == "https://example.com/foo"
    assert result[0]["sources"] == ["event.attachments"]


def test_extract_links_from_attachments_handles_empty():
    assert extract_links_from_attachments([]) == []
    assert extract_links_from_attachments(None) == []


def test_extract_links_from_description_anchor_tag():
    html = '<a href="https://docs.google.com/document/d/DOC1/edit">資料</a>'

    result = extract_links_from_description(html)

    assert result == [
        {
            "url": "https://docs.google.com/document/d/DOC1/edit",
            "fileId": "DOC1",
            "mimeType": "application/vnd.google-apps.document",
            "title": "資料",
            "sources": ["event.description"],
            "sourceUrls": ["https://docs.google.com/document/d/DOC1/edit"],
        }
    ]


def test_extract_links_from_description_plain_url_in_text():
    html = (
        "Notion → Docsに切り替え。"
        "https://docs.google.com/spreadsheets/d/SH123/edit を参照"
    )

    result = extract_links_from_description(html)

    assert len(result) == 1
    assert result[0]["fileId"] == "SH123"
    assert result[0]["mimeType"] == "application/vnd.google-apps.spreadsheet"
    assert result[0]["title"] is None


def test_extract_links_from_description_unescapes_html_entities():
    html = (
        '<a href="https://docs.google.com/document/d/DOC1/edit?gid=1&amp;tab=t.0">x</a>'
    )

    result = extract_links_from_description(html)

    assert "&" in result[0]["url"]
    assert "&amp;" not in result[0]["url"]
    assert result[0]["fileId"] == "DOC1"


def test_extract_links_from_description_ignores_non_drive_urls():
    html = '<a href="https://github.com/orgs/foo/projects/1">project</a>'

    assert extract_links_from_description(html) == []


def test_extract_links_from_description_title_is_none_when_text_equals_url():
    url = "https://docs.google.com/document/d/DOC1/edit"
    html = f'<a href="{url}">{url}</a>'

    result = extract_links_from_description(html)

    assert result[0]["title"] is None


def test_extract_links_from_description_dedups_same_fileid_with_multiple_sourceurls():
    html = (
        '<a href="https://docs.google.com/document/d/X/edit">edit</a>'
        '<a href="https://docs.google.com/document/d/X/view">view</a>'
    )

    result = extract_links_from_description(html)

    assert len(result) == 1
    assert sorted(result[0]["sourceUrls"]) == [
        "https://docs.google.com/document/d/X/edit",
        "https://docs.google.com/document/d/X/view",
    ]
    assert result[0]["sources"] == ["event.description"]


def test_extract_links_from_description_handles_empty():
    assert extract_links_from_description("") == []
    assert extract_links_from_description(None) == []


def test_extract_links_from_description_finds_anchor_inside_complex_html():
    html = (
        "<u></u>"
        '<a target="_blank" '
        'href="https://docs.google.com/document/d/REAL/edit" '
        'class="pastedDriveLink-0">'
        "https://docs.google.com/document/d/REAL/edit"
        "</a><br>その他"
    )

    result = extract_links_from_description(html)

    assert len(result) == 1
    assert result[0]["fileId"] == "REAL"
    assert result[0]["title"] is None  # text equals href


def test_merge_links_dedups_by_fileid_across_sources_and_prefers_attachment_title():
    attachments_links = [
        {
            "url": "https://docs.google.com/document/d/X/edit?usp=meet",
            "fileId": "X",
            "mimeType": "application/vnd.google-apps.document",
            "title": "Gemini メモ",
            "sources": ["event.attachments"],
            "sourceUrls": ["https://docs.google.com/document/d/X/edit?usp=meet"],
        }
    ]
    description_links = [
        {
            "url": "https://docs.google.com/document/d/X/edit",
            "fileId": "X",
            "mimeType": "application/vnd.google-apps.document",
            "title": None,
            "sources": ["event.description"],
            "sourceUrls": ["https://docs.google.com/document/d/X/edit"],
        }
    ]

    merged = merge_links(attachments_links, description_links)

    assert len(merged) == 1
    entry = merged[0]
    assert entry["fileId"] == "X"
    assert sorted(entry["sources"]) == [
        "event.attachments",
        "event.description",
    ]
    assert sorted(entry["sourceUrls"]) == [
        "https://docs.google.com/document/d/X/edit",
        "https://docs.google.com/document/d/X/edit?usp=meet",
    ]
    assert entry["title"] == "Gemini メモ"
    assert entry["mimeType"] == "application/vnd.google-apps.document"


def test_merge_links_keeps_separate_entries_for_different_fileids():
    a = [
        {
            "url": "u1",
            "fileId": "X",
            "mimeType": "m1",
            "title": "t1",
            "sources": ["event.attachments"],
            "sourceUrls": ["u1"],
        }
    ]
    d = [
        {
            "url": "u2",
            "fileId": "Y",
            "mimeType": "m2",
            "title": None,
            "sources": ["event.description"],
            "sourceUrls": ["u2"],
        }
    ]

    merged = merge_links(a, d)

    assert len(merged) == 2
    assert {entry["fileId"] for entry in merged} == {"X", "Y"}


def test_merge_links_passes_through_entries_without_fileid():
    a = [
        {
            "url": "a",
            "fileId": None,
            "mimeType": None,
            "title": None,
            "sources": ["event.attachments"],
            "sourceUrls": ["a"],
        }
    ]
    d = [
        {
            "url": "a",
            "fileId": None,
            "mimeType": None,
            "title": None,
            "sources": ["event.description"],
            "sourceUrls": ["a"],
        }
    ]

    merged = merge_links(a, d)

    assert len(merged) == 2


def test_merge_links_preserves_order_of_first_appearance():
    a = [
        {
            "url": "u1",
            "fileId": "A",
            "mimeType": "m",
            "title": None,
            "sources": ["event.attachments"],
            "sourceUrls": ["u1"],
        },
        {
            "url": "u2",
            "fileId": "B",
            "mimeType": "m",
            "title": None,
            "sources": ["event.attachments"],
            "sourceUrls": ["u2"],
        },
    ]

    merged = merge_links(a)

    assert [entry["fileId"] for entry in merged] == ["A", "B"]


def test_build_links_combines_attachments_and_description_dedups():
    event = {
        "attachments": [
            {
                "fileId": "X",
                "title": "Gemini メモ",
                "fileUrl": "https://docs.google.com/document/d/X/edit?usp=meet",
                "mimeType": "application/vnd.google-apps.document",
            }
        ],
        "description": (
            '<a href="https://docs.google.com/document/d/X/edit">'
            "edit"
            "</a>"
            '<a href="https://drive.google.com/drive/folders/F">folder</a>'
        ),
    }

    links = build_links(event)

    by_id = {entry["fileId"]: entry for entry in links}
    assert set(by_id) == {"X", "F"}
    assert sorted(by_id["X"]["sources"]) == [
        "event.attachments",
        "event.description",
    ]
    assert by_id["F"]["sources"] == ["event.description"]
    assert by_id["F"]["mimeType"] == "application/vnd.google-apps.folder"


def test_build_links_handles_event_without_attachments_or_description():
    assert build_links({}) == []
    assert build_links({"attachments": []}) == []
    assert build_links({"description": ""}) == []
