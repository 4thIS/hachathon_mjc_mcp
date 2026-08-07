"""NCSI 강의계획서 조회.

sugang이 인증된 세션으로 POST /core/lectPlanPop을 받으면 AES로 암호화된
ncsi.mjc.ac.kr URL을 만들어 돌려준다(암호화는 서버가 한다, 우리가 구현하지 않음).
그 URL 자체가 접근 토큰이라(쿠키 불필요, 2026-08-07 실측 확인) 이후 조회는
비인증 fetch()로 진행한다.
"""

import re
import time

from mcp.types import ToolAnnotations

from common.errors import NotRegisteredError, ParseError
from common.http import fetch, fetch_authenticated
from common.models import SyllabusDetail
from common.parse import parse_html
from common.session import SessionRequiredError, require_active_session, require_session

LECT_PLAN_POP_URL = "https://sugang.mjc.ac.kr/core/lectPlanPop"
NCSI_URL = "https://ncsi.mjc.ac.kr/forMJCCyber/lecture.do"
_LOGGED_OUT_MARKER = "<title>로그아웃</title>"
_NCSI_FIELDS = ("sbj", "maj", "year", "term", "group")
# 이 라벨이 붙은 칸은 파서가 값을 읽지 않는다(담당교수 개인 연락처).
_CONTACT_LABELS = frozenset({"연락처"})


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


def _find_section(sections: dict, keyword: str):
    """헤딩에 keyword가 포함된 섹션을 찾는다(완전일치 아님).

    NCS 기반 전공과목은 헤딩에 "NCS정보 및 " 같은 접두어가 붙는다
    ("NCS정보 및 교과목표"). 픽스처로 쓴 RISE 특례 교과목만 "교과목표"
    단독 형태였다 — 완전일치로 찾으면 일반 전공과목이 전부 깨진다.
    """
    return next((box for heading, box in sections.items() if keyword in heading), None)


def _label_map(box, *, multiline: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    table = box.select_one("table.bodyTbl") if box is not None else None
    if table is None:
        return result
    # lxml은 <tbody>를 자동으로 만들어 주지 않는다. 원문에 tbody가 없으면
    # table 자신이 tr의 부모이므로 그쪽을 훑는다. 없다고 빈 dict를 돌려주면
    # 빈 결과가 성공으로 위장된다.
    root = table.find("tbody", recursive=False) or table
    # 이 표 자신의 행만 훑는다. select("th")는 하위를 재귀로 파고들어
    # 중첩된 표(연락처 칸의 table.headTbl)의 th까지 키로 만들 수 있다.
    # 훑는 범위를 고정해야 아래 라벨 차단이 우회되지 않는다.
    for tr in root.find_all("tr", recursive=False):
        for th in tr.find_all("th", recursive=False):
            label = th.get_text(strip=True)
            # 연락처 칸은 값을 읽지 않고 건너뛴다. 이 td 안에 중첩된 표에
            # 담당교수의 전화번호와 이메일이 들어 있어, get_text()를 부르는
            # 순간 개인정보가 문자열로 잡힌다(SyllabusDetail에 실리지 않더라도
            # 추출 자체를 하지 않는 것이 요구사항이다).
            if label in _CONTACT_LABELS:
                continue
            td = th.find_next_sibling("td")
            if td is None:
                continue
            text = td.get_text("\n", strip=True) if multiline else td.get_text(strip=True)
            result[label] = text
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

    basic = _label_map(_find_section(sections, "교과목 기본정보"))
    if not basic:
        raise ParseError("강의계획서")
    if not basic.get("교과목명"):
        # 표와 라벨은 있는데 값 칸이 전부 빈 문자열인 페이지가 있다(학교가 아직
        # 강의계획서를 작성하지 않은 과목). dict가 비었는지만 보는 위 검사는
        # 이 경우를 통과시켜, 전 필드가 빈 SyllabusDetail을 성공으로 위장한다.
        # 교과목명은 실제 강의계획서라면 학교가 항상 채우는 값이다.
        raise NotRegisteredError("강의계획서")

    goals = _label_map(_find_section(sections, "교과목표"), multiline=True)
    if not goals:
        # overview/goals/content_summary가 전부 이 표에서 나온다. 비어 있는데
        # 성공으로 넘기면 알맹이 없는 결과를 정상 응답으로 위장하게 된다.
        raise ParseError("강의계획서 교과목표")

    methods = _extract_evaluation_methods(_find_section(sections, "평가방법"))

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

    department_code는 list_departments가 돌려준 값 — 즉 이 과목을 찾을 때
    search_courses에 넘긴 것과 동일한 값 — 을 그대로 다시 넘길 것
    (CourseSummary에는 이 필드가 없다). course_code/section은 search_courses가
    돌려준 CourseSummary의 course_code/section을 그대로 넘길 것.
    원문에 있는 담당교수 연락처(전화·이메일)는 포함하지 않는다.
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
