import json

import httpx
import pytest

from common import http
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


# --- 파싱 예외 경계 (Critical 1) ---


def test_parse_xml_raises_parse_error_on_non_xml():
    """XML 자리에 오류 HTML이 오면 XMLSyntaxError가 아니라 ParseError여야 한다."""
    content = b"<html><body>&undefined_entity; secret-token</body></html>"
    with pytest.raises(ParseError) as exc_info:
        parse_xml(content)
    assert isinstance(exc_info.value, ToolError)


def test_parse_xml_error_does_not_leak_raw_content():
    """예외 메시지·체인 어디에도 원문 토큰이 남으면 안 된다."""
    content = b"<html><body>&undefined_entity; secret-token</body></html>"
    with pytest.raises(ParseError) as exc_info:
        parse_xml(content)
    assert "secret-token" not in str(exc_info.value)
    assert "undefined_entity" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_parse_xml_raises_parse_error_on_empty_body():
    with pytest.raises(ParseError):
        parse_xml(b"")


def test_parse_html_raises_parse_error_when_parser_rejects(monkeypatch):
    """lxml이 마크업을 거부하면 ParserRejectedMarkup 대신 ParseError가 나가야 한다."""
    from bs4.exceptions import ParserRejectedMarkup

    from common import parse

    def reject(*args, **kwargs):
        raise ParserRejectedMarkup("secret-token")

    monkeypatch.setattr(parse, "BeautifulSoup", reject)
    with pytest.raises(ParseError) as exc_info:
        parse.parse_html(b"<html></html>")
    assert "secret-token" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


# --- 캐시 쓰기 실패가 응답을 죽이지 않는다 (Critical 2) ---


def test_with_fallback_returns_data_when_cache_write_fails(tmp_path, monkeypatch):
    """CACHE_DIR을 만들 수 없어도 이미 받은 데이터는 그대로 나가야 한다."""
    from common import cache

    blocker = tmp_path / "blocker"
    blocker.write_text("파일이라 하위 디렉터리를 만들 수 없다", encoding="utf-8")
    monkeypatch.setattr(cache, "CACHE_DIR", blocker / "sub")

    data, age = cache.with_fallback("k", lambda: {"v": 1})
    assert data == {"v": 1}
    assert age is None


def test_with_fallback_returns_data_when_write_text_fails(tmp_path, monkeypatch):
    """디스크 풀·파일 잠금 등으로 쓰기가 실패해도 데이터는 살아남아야 한다."""
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    def boom_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cache.Path, "write_text", boom_write)
    data, age = cache.with_fallback("k", lambda: {"v": 1})
    assert data == {"v": 1}
    assert age is None


# --- 손상된 캐시 파일 (Critical 3) ---


def test_with_fallback_reraises_tool_error_when_cache_is_corrupt(tmp_path, monkeypatch):
    """캐시가 깨졌으면 JSONDecodeError가 아니라 원래의 FetchError가 나가야 한다."""
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    (tmp_path / "k.json").write_text('{"saved_at": 1, "dat', encoding="utf-8")

    def boom():
        raise FetchError("ConnectTimeout")

    with pytest.raises(FetchError):
        cache.with_fallback("k", boom)


def test_with_fallback_reraises_tool_error_when_cache_lacks_keys(tmp_path, monkeypatch):
    """구조가 다른 캐시(키 누락)도 KeyError가 아니라 FetchError로 나가야 한다."""
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    (tmp_path / "k.json").write_text(json.dumps({"data": {"v": 1}}), encoding="utf-8")

    def boom():
        raise FetchError("ConnectTimeout")

    with pytest.raises(FetchError):
        cache.with_fallback("k", boom)


# --- common/http.py (Important 4, 5) ---


@pytest.fixture
def http_env(monkeypatch):
    """네트워크로 나가지 않고, 실제로 자지도 않는 http 테스트 환경.

    yield 값은 fetch가 요청한 sleep 시간 목록이다.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    http._last_request_at.clear()
    yield sleeps
    http._last_request_at.clear()


def _install_mock_transport(monkeypatch, handler):
    """httpx.Client를 MockTransport를 물린 서브클래스로 교체한다.

    _get_once의 실제 흐름(Client 생성 → get → raise_for_status)은 그대로 탄다.
    """

    class MockedClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", MockedClient)


def test_fetch_does_not_retry_when_first_attempt_succeeds(http_env, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=b"<root/>")

    _install_mock_transport(monkeypatch, handler)
    assert http.fetch("https://lib.example.ac.kr/seats") == b"<root/>"
    assert len(calls) == 1
    assert http_env == []


def test_fetch_retries_exactly_once_then_succeeds(http_env, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, content=b"ok")

    _install_mock_transport(monkeypatch, handler)
    assert http.fetch("https://lib.example.ac.kr/seats") == b"ok"
    assert len(calls) == 2


def test_fetch_raises_fetch_error_after_second_failure(http_env, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        raise httpx.ConnectError("connection refused")

    _install_mock_transport(monkeypatch, handler)
    with pytest.raises(FetchError):
        http.fetch("https://lib.example.ac.kr/seats")
    assert len(calls) == 2  # 최초 1회 + 재시도 1회, 그 이상은 하지 않는다


def test_fetch_retry_delay_matches_host_interval(http_env, monkeypatch):
    """재시도 대기가 동일 호스트 최소 간격(1.0초)과 어긋나면 안 된다."""

    def handler(request):
        raise httpx.ConnectError("connection refused")

    _install_mock_transport(monkeypatch, handler)
    with pytest.raises(FetchError):
        http.fetch("https://lib.example.ac.kr/seats")
    assert http_env == [http.MIN_INTERVAL_SEC]
    assert http.MIN_INTERVAL_SEC == 1.0


def test_fetch_error_message_hides_url_and_body(http_env, monkeypatch):
    def handler(request):
        return httpx.Response(500, content=b"<html>secret-token</html>")

    _install_mock_transport(monkeypatch, handler)
    with pytest.raises(FetchError) as exc_info:
        http.fetch(
            "https://lib.example.ac.kr/secret-path", params={"sid": "secret-token"}
        )
    message = str(exc_info.value)
    assert "HTTPStatusError" in message
    assert "secret-token" not in message
    assert "secret-path" not in message
    assert "lib.example.ac.kr" not in message
    assert "<html" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_fetch_enforces_min_interval_between_same_host_calls(http_env, monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"ok")

    _install_mock_transport(monkeypatch, handler)
    http.fetch("https://lib.example.ac.kr/a")
    assert http_env == []  # 첫 호출은 기다리지 않는다

    http.fetch("https://lib.example.ac.kr/b")
    assert len(http_env) == 1
    assert 0.9 < http_env[0] <= http.MIN_INTERVAL_SEC


def test_fetch_does_not_wait_for_a_different_host(http_env, monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"ok")

    _install_mock_transport(monkeypatch, handler)
    http.fetch("https://lib.example.ac.kr/a")
    http.fetch("https://www.example.ac.kr/a")
    assert http_env == []


def test_fetch_sends_custom_headers(http_env, monkeypatch):
    captured = {}

    def handler(request):
        captured["referer"] = request.headers.get("referer")
        return httpx.Response(200, content=b"ok")

    _install_mock_transport(monkeypatch, handler)
    http.fetch(
        "https://ncsi.example.ac.kr/x",
        headers={"Referer": "https://sugang.example.ac.kr/"},
    )
    assert captured["referer"] == "https://sugang.example.ac.kr/"


def test_fetch_without_headers_still_works(http_env, monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"ok")

    _install_mock_transport(monkeypatch, handler)
    assert http.fetch("https://ncsi.example.ac.kr/x") == b"ok"
