import json

import httpx
import pytest

from common.http import fetch_authenticated
from common.session import (
    SessionRequiredError,
    load_session,
    require_active_session,
    require_session,
    save_session,
)


def test_fetch_authenticated_sends_cookies_and_returns_full_response(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["cookie_header"] = request.headers.get("cookie", "")
        captured["method"] = request.method
        return httpx.Response(302, headers={"location": "/logOut"})

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    import common.http as http_mod
    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http_mod, "httpx", httpx)
    monkeypatch.setattr(httpx, "Client", fake_client)

    resp = fetch_authenticated(
        "https://sugang.mjc.ac.kr/core/d/lectList",
        cookies={"JSESSIONID": "abc123"},
    )
    assert "JSESSIONID=abc123" in captured["cookie_header"]
    assert captured["method"] == "GET"
    assert resp.status_code == 302
    assert resp.is_redirect


def test_fetch_authenticated_posts_form_data(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        captured["method"] = request.method
        return httpx.Response(200, json={"rows": []})

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    import common.http as http_mod
    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(httpx, "Client", fake_client)

    resp = fetch_authenticated(
        "https://sugang.mjc.ac.kr/core/d/lectList",
        cookies={"JSESSIONID": "abc123"},
        method="POST",
        data={"pComboClsMajCd": "1201001"},
    )
    assert captured["method"] == "POST"
    assert "pComboClsMajCd=1201001" in captured["body"]
    assert resp.status_code == 200


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    save_session("sugang", {"JSESSIONID": "abc123"})
    assert load_session("sugang") == {"JSESSIONID": "abc123"}


def test_load_returns_none_when_missing(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    assert load_session("sugang") is None


def test_load_returns_none_when_corrupted(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    (tmp_path / "session_sugang.json").write_text("not json", encoding="utf-8")
    assert load_session("sugang") is None


def test_require_session_raises_when_missing(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    with pytest.raises(SessionRequiredError):
        require_session("sugang")


def test_session_required_error_message_has_no_cookie_value():
    err = SessionRequiredError("sugang")
    assert "abc123" not in str(err)
    assert "login_helper" in str(err)


def test_require_active_session_raises_on_redirect():
    resp = httpx.Response(302, headers={"location": "/logOut"}, request=httpx.Request("GET", "https://x"))
    with pytest.raises(SessionRequiredError):
        require_active_session(resp, "sugang")


def test_require_active_session_passes_on_200():
    resp = httpx.Response(200, request=httpx.Request("GET", "https://x"))
    require_active_session(resp, "sugang")  # 예외 없이 통과해야 함
