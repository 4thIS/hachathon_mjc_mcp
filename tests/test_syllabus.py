import re
from pathlib import Path

import pytest

from common.errors import ParseError
from common.parse import parse_html
from common.session import SessionRequiredError
from tools.syllabus import _extract_ncsi_url, _label_map, parse_syllabus

FIXTURES = Path(__file__).parent / "fixtures"

_PHONE_SHAPED = re.compile(r"\d{2,4}-\d{3,4}-\d{4}")
_EMAIL_SHAPED = re.compile(r"[\w.+-]+@[\w-]+\.\w+")


def _basic_info_box():
    soup = parse_html((FIXTURES / "syllabus_detail.html").read_bytes())
    for box in soup.select("div.tabBox"):
        heading = box.find("h3")
        if heading is not None and heading.get_text(strip=True) == "교과목 기본정보":
            return box
    raise AssertionError("픽스처에 '교과목 기본정보' 섹션이 없다")


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


def test_label_map_never_extracts_contact_row():
    """연락처 칸은 키로도 남기지 않는다. 값을 읽는 것 자체가 개인정보 추출이다."""
    basic = _label_map(_basic_info_box())
    assert "연락처" not in basic
    # 중첩 표(table.headTbl)의 th가 키로 새어 들어오지도 않아야 한다.
    assert "연락처 및 이메일 주소" not in basic
    # 파싱은 정상적으로 계속되어야 한다 — 연락처 뒤에 오는 행들이 살아 있는지 확인.
    assert basic["학점"] == "1"
    assert basic["성취수준"] == "3수준"


def test_label_map_holds_no_phone_or_email_shaped_value():
    """중간 산출물(dict)에도 전화번호·이메일 형태의 문자열이 남으면 안 된다."""
    basic = _label_map(_basic_info_box())
    for key, value in basic.items():
        assert not _PHONE_SHAPED.search(value), f"{key}에 전화번호 형태 문자열이 남았다"
        assert not _EMAIL_SHAPED.search(value), f"{key}에 이메일 형태 문자열이 남았다"


def test_parse_syllabus_output_has_no_phone_or_email_shaped_value():
    detail = parse_syllabus((FIXTURES / "syllabus_detail.html").read_bytes(), "https://x")
    for field, value in detail.model_dump().items():
        text = value if isinstance(value, str) else str(value)
        assert not _PHONE_SHAPED.search(text), f"{field}에 전화번호 형태 문자열이 남았다"
        assert not _EMAIL_SHAPED.search(text), f"{field}에 이메일 형태 문자열이 남았다"


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
