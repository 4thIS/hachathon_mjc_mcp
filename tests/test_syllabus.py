import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from common import http, session
from common.errors import ParseError
from common.parse import parse_html
from common.session import SessionRequiredError
from tools.syllabus import (
    LECT_PLAN_POP_URL,
    NCSI_URL,
    _extract_ncsi_url,
    _find_section,
    _label_map,
    get_syllabus,
    parse_syllabus,
)

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


# --- <tbody>가 없는 표 (lxml은 tbody를 만들어 주지 않는다) ---


def _box(html: str):
    return parse_html(html.encode("utf-8")).select_one("div.tabBox")


_NO_TBODY_GOALS = """<html><body><div class="tabBox"><h3>교과목표</h3>
<table class="bodyTbl">
<tr><th>교과목 개요</th><td class="left">개요 첫 줄<br/>개요 둘째 줄</td></tr>
<tr><th>교과목표</th><td class="left">목표 본문</td></tr>
<tr><th>교육내용</th><td class="left">교육내용 본문</td></tr>
</table></div></body></html>"""


def test_label_map_reads_table_without_explicit_tbody():
    """원문에 <tbody>가 없어도 라벨을 읽어야 한다. 빈 dict는 결과를 조용히 비운다."""
    labels = _label_map(_box(_NO_TBODY_GOALS), multiline=True)
    assert labels["교과목표"] == "목표 본문"
    assert labels["교육내용"] == "교육내용 본문"
    assert labels["교과목 개요"] == "개요 첫 줄\n개요 둘째 줄"


def test_label_map_without_tbody_still_blocks_contact_row():
    """tbody 폴백이 연락처 차단을 우회하는 통로가 되면 안 된다."""
    html = """<html><body><div class="tabBox"><h3>교과목 기본정보</h3>
<table class="bodyTbl">
<tr><th>교과목명</th><td>테스트과목</td></tr>
<tr><th>연락처</th><td><table class="headTbl">
<tr><th>연락처 및 이메일 주소</th><td>02-300-1234 / prof@mjc.ac.kr</td></tr>
</table></td></tr>
<tr><th>학점</th><td>1</td></tr>
</table></div></body></html>"""
    basic = _label_map(_box(html))
    assert "연락처" not in basic
    assert "연락처 및 이메일 주소" not in basic  # 중첩 표의 th도 새면 안 된다
    assert basic["교과목명"] == "테스트과목"
    assert basic["학점"] == "1"  # 연락처 뒤의 행은 살아 있어야 한다
    for value in basic.values():
        assert not _PHONE_SHAPED.search(value)
        assert not _EMAIL_SHAPED.search(value)


def test_parse_syllabus_raises_parse_error_when_goals_section_missing():
    """교과목표를 못 읽으면 알맹이 없는 결과를 성공으로 위장하지 말고 ParseError."""
    html = """<html><body><div class="tabBox"><h3>교과목 기본정보</h3>
<table class="bodyTbl"><tbody>
<tr><th>교과목명</th><td>테스트과목</td></tr>
<tr><th>학점</th><td>1</td></tr>
</tbody></table></div></body></html>"""
    with pytest.raises(ParseError) as exc_info:
        parse_syllabus(html.encode("utf-8"), "https://x")
    assert "교과목표" in str(exc_info.value)


# --- NCS 전공과목의 헤딩 변형 ("NCS정보 및 교과목표") ---
#
# 실제 응답 캡처본 fixtures/syllabus_detail_capstone.html("캡스톤디자인",
# NCS 기반 전공과목)로 검증한다. 기존 fixtures/syllabus_detail.html은 헤딩이
# "교과목표" 단독인 RISE 특례 교과목이라 완전일치 버그를 가리고 있었다.


def _capstone():
    return parse_syllabus(
        (FIXTURES / "syllabus_detail_capstone.html").read_bytes(),
        "https://ncsi.mjc.ac.kr/forMJCCyber/lecture.do?sbj=x",
    )


def test_parse_syllabus_extracts_core_fields_from_ncs_major_course():
    """헤딩이 "NCS정보 및 교과목표"인 실제 전공과목 응답을 파싱한다.

    완전일치로 찾던 시절엔 이 헤딩에서 ParseError가 났다.
    """
    detail = _capstone()

    assert detail.course_name == "캡스톤디자인"
    assert detail.professor == "정필성"
    assert detail.category == "전공과정"
    assert detail.credit == 4
    assert detail.grade_semester == "3학년 / 2학기 (101반)"
    assert detail.evaluation_methods == ["D.논술형시험", "K.구두발표"]


def test_parse_syllabus_ncs_major_course_goals_section_is_populated():
    """overview/goals/content_summary가 전부 "NCS정보 및 교과목표" 표에서 나온다."""
    detail = _capstone()

    assert "캡스톤디자인 과제를 병행하여" in detail.overview
    assert "사물인터넷과 임베디드 시스템" in detail.goals
    assert "주제 발굴부터 결과 발표까지" in detail.content_summary
    assert "\n" in detail.overview  # <br/>이 줄바꿈으로 살아 있어야 한다


def test_parse_syllabus_ncs_major_course_has_no_phone_or_email_shaped_value():
    """원문에 마스킹된 연락처가 남아 있어도 결과에는 그 형태조차 새면 안 된다."""
    raw = (FIXTURES / "syllabus_detail_capstone.html").read_bytes().decode("utf-8")
    # 픽스처 자체에 전화·이메일 "모양"의 문자열이 있어야 이 테스트가 의미를 가진다.
    assert _PHONE_SHAPED.search(raw) and _EMAIL_SHAPED.search(raw)

    detail = _capstone()
    dumped = detail.model_dump()
    assert "phone" not in dumped
    assert "email" not in dumped
    for field, value in dumped.items():
        text = value if isinstance(value, str) else str(value)
        assert not _PHONE_SHAPED.search(text), f"{field}에 전화번호 형태 문자열이 남았다"
        assert not _EMAIL_SHAPED.search(text), f"{field}에 이메일 형태 문자열이 남았다"


def test_parse_syllabus_ignores_unrecognized_ncs_sections():
    """파서가 쓰지 않는 NCS 전용 섹션이 있어도 그냥 무시한다(design.md §14.6).

    부분일치로 섹션을 찾으므로, 이 헤딩들이 인식 대상 키워드를 가로채지
    않는다는 것까지 함께 확인한다.
    """
    soup = parse_html((FIXTURES / "syllabus_detail_capstone.html").read_bytes())
    headings = [
        box.find("h3").get_text(strip=True)
        for box in soup.select("div.tabBox")
        if box.find("h3") is not None
    ]
    for unused in (
        "능력단위요소 및 수행준거",
        "지식 / 기술 / 태도",
        "직업기초능력",
        "교과목 구성",
        "교재 (NCS학습모듈)",
        "교수/학습방법",
    ):
        assert unused in headings, f"픽스처에 '{unused}' 섹션이 없다 — 테스트 전제가 깨졌다"

    sections = {heading: heading for heading in headings}
    assert _find_section(sections, "교과목 기본정보") == "교과목 기본정보"
    assert _find_section(sections, "교과목표") == "NCS정보 및 교과목표"
    assert _find_section(sections, "평가방법") == "평가방법"

    _capstone()  # 인식 못 하는 섹션이 섞여 있어도 예외 없이 끝나야 한다


def test_find_section_matches_partial_heading():
    sections = {"NCS정보 및 교과목표": "goals-box", "교과목 기본정보": "basic-box"}
    assert _find_section(sections, "교과목표") == "goals-box"
    assert _find_section(sections, "교과목 기본정보") == "basic-box"


def test_find_section_returns_none_when_no_heading_contains_keyword():
    sections = {"교과목 기본정보": "basic-box", "교재": "book-box"}
    assert _find_section(sections, "평가방법") is None


def test_find_section_does_not_confuse_real_fixture_headings():
    """실제 픽스처의 헤딩끼리 부분일치로 서로를 잡아채지 않는지 확인."""
    soup = parse_html((FIXTURES / "syllabus_detail.html").read_bytes())
    sections = {}
    for box in soup.select("div.tabBox"):
        heading = box.find("h3")
        if heading is not None:
            sections[heading.get_text(strip=True)] = heading.get_text(strip=True)

    for keyword in ("교과목 기본정보", "교과목표", "평가방법"):
        matched = [h for h in sections if keyword in h]
        assert matched == [keyword], f"{keyword}가 다른 헤딩과 충돌한다: {matched}"


# --- get_syllabus() 전체 흐름 ---


@pytest.fixture
def syllabus_env(monkeypatch):
    """세션·네트워크·대기 시간을 모두 끊은 get_syllabus 실행 환경.

    yield 값은 MockTransport가 받은 httpx.Request 목록이다.
    """
    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(session, "load_session", lambda system: {"JSESSIONID": "fake-session"})
    http._last_request_at.clear()

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "sugang.mjc.ac.kr":
            return httpx.Response(
                200, content=(FIXTURES / "lect_plan_pop_response.txt").read_bytes()
            )
        return httpx.Response(
            200, content=(FIXTURES / "syllabus_detail.html").read_bytes()
        )

    class MockedClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", MockedClient)
    yield requests
    http._last_request_at.clear()


def test_get_syllabus_maps_arguments_to_lect_plan_pop_fields(syllabus_env):
    """popMaj/popSbj/popBunban에 학과·과목·분반이 뒤바뀌지 않고 실려야 한다."""
    get_syllabus("DEPT-1234", "SUBJ-5678", "101")

    pop_request = syllabus_env[0]
    assert pop_request.method == "POST"
    assert str(pop_request.url).startswith(LECT_PLAN_POP_URL)

    form = parse_qs(pop_request.content.decode("utf-8"))
    assert form["popMaj"] == ["DEPT-1234"]     # department_code
    assert form["popSbj"] == ["SUBJ-5678"]     # course_code
    assert form["popBunban"] == ["101"]        # section


def test_get_syllabus_sends_no_cookie_to_ncsi(syllabus_env):
    """이 브랜치의 핵심 보안 속성 — ncsi 요청에는 세션 쿠키가 실리지 않는다."""
    get_syllabus("DEPT-1234", "SUBJ-5678", "101")

    pop_request, ncsi_request = syllabus_env
    assert pop_request.headers.get("cookie") is not None  # sugang에는 실린다
    assert ncsi_request.url.host == "ncsi.mjc.ac.kr"
    assert ncsi_request.headers.get("cookie") is None
    assert "fake-session" not in str(ncsi_request.headers)
    assert ncsi_request.headers.get("referer") == "https://sugang.mjc.ac.kr/"


def test_get_syllabus_uses_pinned_ncsi_base_url(syllabus_env):
    """ncsi 베이스 URL은 코드 상수 — sugang 응답에서 호스트를 가져오지 않는다."""
    get_syllabus("DEPT-1234", "SUBJ-5678", "101")

    ncsi_request = syllabus_env[1]
    assert str(ncsi_request.url).startswith(NCSI_URL + "?")
    assert "FAKEsbjTOKEN" in str(ncsi_request.url)
    assert "OLDsbjTOKEN" not in str(ncsi_request.url)


def test_get_syllabus_happy_path_returns_syllabus_detail(syllabus_env):
    detail = get_syllabus("DEPT-1234", "SUBJ-5678", "101")

    assert len(syllabus_env) == 2  # lectPlanPop POST + ncsi GET, 그 이상 없음
    assert detail.course_name == "AI활용웹개발"
    assert detail.professor == "정필성"
    assert detail.credit == 1
    assert detail.evaluation_methods == ["A.포트폴리오", "K.구두발표"]
    assert detail.source_url.startswith(NCSI_URL + "?")


def test_get_syllabus_raises_session_required_without_session(monkeypatch):
    monkeypatch.setattr(session, "load_session", lambda system: None)
    with pytest.raises(SessionRequiredError):
        get_syllabus("DEPT-1234", "SUBJ-5678", "101")
