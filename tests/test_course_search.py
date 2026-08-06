import json
from pathlib import Path

import pytest

from common.errors import ParseError
from tools.course_search import parse_courses

FIXTURE = Path(__file__).parent / "fixtures" / "lect_list_response.json"


def test_parses_three_courses():
    courses = parse_courses(FIXTURE.read_bytes())
    assert len(courses) == 3


def test_course_has_required_fields():
    courses = parse_courses(FIXTURE.read_bytes())
    first = courses[0]
    assert first.course_code == "J04661"
    assert first.name == "캡스톤디자인"
    assert first.professor == "정필성"
    assert first.capacity == 40
    assert first.credit == 4
    assert first.grade == 3
    assert first.category == "전공과정"


def test_schedule_converts_br_to_newline_and_keeps_room():
    courses = parse_courses(FIXTURE.read_bytes())
    first = courses[0]
    assert "\n" in first.schedule
    assert "공803" in first.schedule
    assert "<br>" not in first.schedule


def test_no_korean_mojibake():
    courses = parse_courses(FIXTURE.read_bytes())
    joined = "".join(c.name + c.professor for c in courses)
    assert "�" not in joined


def test_professor_staff_number_never_appears():
    """memberNo(교수 사번)는 개인정보라 CourseSummary에 절대 담지 않는다."""
    courses = parse_courses(FIXTURE.read_bytes())
    for course in courses:
        assert not hasattr(course, "member_no")
        assert not hasattr(course, "memberNo")


def test_raises_parse_error_on_malformed_json():
    with pytest.raises(ParseError):
        parse_courses(b"not json at all")


def test_raises_parse_error_when_rows_missing():
    with pytest.raises(ParseError):
        parse_courses(json.dumps({"other": []}).encode())
