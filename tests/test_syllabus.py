from pathlib import Path

import pytest

from common.errors import ParseError
from common.session import SessionRequiredError
from tools.syllabus import _extract_ncsi_url, parse_syllabus

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_syllabus_extracts_core_fields():
    detail = parse_syllabus(
        (FIXTURES / "syllabus_detail.html").read_bytes(),
        "https://ncsi.mjc.ac.kr/forMJCCyber/lecture.do?sbj=x",
    )
    assert detail.course_name == "AI활용웹개발"
    assert detail.professor == "정필성"
    assert detail.category == "통합전공교과"
    assert detail.credit == 1
    assert detail.grade_semester == "1학년 / 2학기 (101반)"
    assert "RISE 사업" in detail.overview
    assert "AI 코딩 도구의 대화형 개발 흐름" in detail.goals
    assert "AI 코딩 도구 활용 기초" in detail.content_summary


def test_parse_syllabus_multiline_content_keeps_newlines():
    detail = parse_syllabus((FIXTURES / "syllabus_detail.html").read_bytes(), "https://x")
    assert "\n" in detail.overview


def test_parse_syllabus_evaluation_methods_only_checked():
    detail = parse_syllabus((FIXTURES / "syllabus_detail.html").read_bytes(), "https://x")
    assert detail.evaluation_methods == ["A.포트폴리오", "K.구두발표"]


def test_parse_syllabus_never_includes_contact_info():
    """담당교수 연락처는 원문에 있지만 SyllabusDetail에는 필드 자체가 없어야 한다."""
    detail = parse_syllabus((FIXTURES / "syllabus_detail.html").read_bytes(), "https://x")
    dumped = detail.model_dump()
    assert "phone" not in dumped
    assert "email" not in dumped


def test_parse_syllabus_raises_parse_error_on_malformed_html():
    with pytest.raises(ParseError):
        parse_syllabus(b"<html><body>not a syllabus</body></html>", "https://x")


def test_extract_ncsi_url_ignores_commented_example_line():
    content = (FIXTURES / "lect_plan_pop_response.txt").read_bytes()
    url = _extract_ncsi_url(content)
    assert url.startswith("https://ncsi.mjc.ac.kr/forMJCCyber/lecture.do?")
    assert "sbj=FAKEsbjTOKEN/abcd1234EF==" in url
    assert "maj=FAKEmajTOKEN/ghij5678KL==" in url
    assert "OLDsbjTOKEN" not in url  # 주석에 있던 값이 섞이면 안 된다


def test_extract_ncsi_url_raises_session_required_when_logged_out():
    content = (FIXTURES / "lect_plan_pop_logged_out.html").read_bytes()
    with pytest.raises(SessionRequiredError):
        _extract_ncsi_url(content)
