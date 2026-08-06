"""NCSI 강의계획서 조회.

sugang이 인증된 세션으로 POST /core/lectPlanPop을 받으면 AES로 암호화된
ncsi.mjc.ac.kr URL을 만들어 돌려준다(암호화는 서버가 한다, 우리가 구현하지 않음).
그 URL 자체가 접근 토큰이라(쿠키 불필요, 2026-08-07 실측 확인) 이후 조회는
비인증 fetch()로 진행한다.
"""

import re
import time

from mcp.types import ToolAnnotations

from common.errors import ParseError
from common.http import fetch, fetch_authenticated
from common.models import SyllabusDetail
from common.parse import parse_html
from common.session import SessionRequiredError, require_active_session, require_session

LECT_PLAN_POP_URL = "https://sugang.mjc.ac.kr/core/lectPlanPop"
NCSI_URL = "https://ncsi.mjc.ac.kr/forMJCCyber/lecture.do"
_LOGGED_OUT_MARKER = "<title>로그아웃</title>"
_NCSI_FIELDS = ("sbj", "maj", "year", "term", "group")


def _extract_ncsi_url(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    if _LOGGED_OUT_MARKER in text:
        raise SessionRequiredError("sugang")

    # 실측 응답에 예시로 남은 주석 줄(//url = "...")을 먼저 제거한다.
    # 없으면 따옴표로 감싼 문자열을 순서대로 이어붙일 때 주석의 값과 섞인다.
    cleaned = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )

    fields: dict[str, str] = {}
    for name in _NCSI_FIELDS:
        match = re.search(rf'{name}=([^"]*)"', cleaned)
        if match is None:
            raise ParseError("강의계획서 링크")
        fields[name] = match.group(1)

    query = "&".join(f"{key}={value}" for key, value in fields.items())
    return f"{NCSI_URL}?{query}&fake={int(time.time() * 1000)}"


def _label_map(box, *, multiline: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    table = box.select_one("table.bodyTbl") if box is not None else None
    if table is None:
        return result
    for th in table.select("th"):
        td = th.find_next_sibling("td")
        if td is None:
            continue
        text = td.get_text("\n", strip=True) if multiline else td.get_text(strip=True)
        result[th.get_text(strip=True)] = text
    return result


def _extract_evaluation_methods(box) -> list[str]:
    table = box.select_one("table.bodyTbl") if box is not None else None
    if table is None:
        return []
    rows = table.select("tbody > tr")
    methods: list[str] = []
    for label_row, data_row in zip(rows[0::2], rows[1::2]):
        labels = [th.get_text(strip=True) for th in label_row.find_all("th")]
        cells = data_row.find_all("td")
        for label, cell in zip(labels, cells):
            if label and cell.select_one("span.on") is not None:
                methods.append(label)
    return methods


def parse_syllabus(content: bytes, source_url: str) -> SyllabusDetail:
    soup = parse_html(content)
    sections = {}
    for box in soup.select("div.tabBox"):
        heading = box.find("h3")
        if heading is not None:
            sections[heading.get_text(strip=True)] = box

    basic = _label_map(sections.get("교과목 기본정보"))
    if not basic:
        raise ParseError("강의계획서")

    goals = _label_map(sections.get("교과목표"), multiline=True)
    methods = _extract_evaluation_methods(sections.get("평가방법"))

    credit_text = basic.get("학점", "")
    return SyllabusDetail(
        course_name=basic.get("교과목명", ""),
        professor=basic.get("담당교수", ""),
        category=basic.get("이수구분", ""),
        credit=int(credit_text) if credit_text.isdigit() else 0,
        grade_semester=basic.get("학년/학기(분반)", ""),
        overview=goals.get("교과목 개요", ""),
        goals=goals.get("교과목표", ""),
        content_summary=goals.get("교육내용", ""),
        evaluation_methods=methods,
        source_url=source_url,
    )


def get_syllabus(department_code: str, course_code: str, section: str) -> SyllabusDetail:
    """강의계획서를 조회한다. 로그인 필요(search_courses와 동일 세션 재사용).

    department_code/course_code/section은 search_courses 결과의 값을
    그대로 넘길 것. 원문에 있는 담당교수 연락처(전화·이메일)는 포함하지 않는다.
    주차별 15주 계획 등 상세는 반환값의 source_url에서 직접 확인할 것.
    """
    cookies = require_session("sugang")
    pop_response = fetch_authenticated(
        LECT_PLAN_POP_URL,
        cookies=cookies,
        method="POST",
        params={"fake": str(int(time.time() * 1000))},
        headers={"Referer": "https://sugang.mjc.ac.kr/core/home"},
        data={
            "popMaj": department_code,
            "popSbj": course_code,
            "popBunban": section,
        },
    )
    require_active_session(pop_response, "sugang")
    ncsi_url = _extract_ncsi_url(pop_response.content)

    html = fetch(ncsi_url, headers={"Referer": "https://sugang.mjc.ac.kr/"})
    return parse_syllabus(html, ncsi_url)


def register(mcp) -> None:
    mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True)
    )(get_syllabus)
