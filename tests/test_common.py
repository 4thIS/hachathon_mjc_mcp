import pytest

from common.errors import FetchError, ParseError, ToolError
from common.parse import parse_html, parse_xml


def test_errors_are_tool_errors():
    assert isinstance(FetchError("ConnectTimeout"), ToolError)
    assert isinstance(ParseError("공지 목록"), ToolError)


def test_error_message_does_not_leak_raw_content():
    """에러 메시지에 원문이 섞이면 안 된다. 타입명과 고정 문구만."""
    message = str(FetchError("ConnectTimeout"))
    assert "ConnectTimeout" in message
    assert "<html" not in message


def test_parse_xml_strips_utf8_bom():
    """도서관 API 응답에는 BOM이 붙어 있다."""
    content = b"\xef\xbb\xbf<?xml version='1.0' encoding='utf-8'?><root><a>1</a></root>"
    root = parse_xml(content)
    assert root.find("a").text == "1"


def test_parse_xml_reads_cdata():
    content = b"<root><item><nm><![CDATA[\xea\xb0\x95\xec\x9d\x98\xec\x8b\xa4]]></nm></item></root>"
    root = parse_xml(content)
    assert root.find("item/nm").text == "강의실"


def test_parse_html_decodes_utf8_from_bytes():
    content = '<html><body><p class="x">한글</p></body></html>'.encode("utf-8")
    soup = parse_html(content)
    assert soup.select_one("p.x").get_text() == "한글"


def test_with_fallback_returns_fresh_data_and_no_age(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    data, age = cache.with_fallback("k", lambda: {"v": 1})
    assert data == {"v": 1}
    assert age is None


def test_with_fallback_uses_cache_when_fetch_fails(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.with_fallback("k", lambda: {"v": 1})

    def boom():
        raise FetchError("ConnectTimeout")

    data, age = cache.with_fallback("k", boom)
    assert data == {"v": 1}
    assert age == 0


def test_with_fallback_reraises_when_no_cache(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    def boom():
        raise FetchError("ConnectTimeout")

    with pytest.raises(FetchError):
        cache.with_fallback("missing", boom)
