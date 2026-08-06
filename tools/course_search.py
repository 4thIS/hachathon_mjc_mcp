"""sugang 개설 강좌 검색.

로그인이 필요하다. department_code는 list_departments가 돌려준 값을
그대로 받는다 — 내부 코드를 AI가 직접 조합해 만들지 않는다.

실제 응답 필드명(subjectCd, subjectNmKor, nm 등)은 2026-08-07 실제 로그인
세션으로 확인했다. memberNo(교수 사번)는 개인정보라 절대 CourseSummary에
담지 않는다.
"""

import json
import re
import time
from typing import Literal

from mcp.types import ToolAnnotations

from common.errors import ParseError
from common.http import fetch_authenticated
from common.models import CourseList, CourseSummary
from common.session import require_active_session, require_session

LECT_LIST_URL = "https://sugang.mjc.ac.kr/core/d/lectList"

# 사람이 읽는 이름 -> sugang 내부 강좌구분코드. 2026-08-07 실측으로 확정.
CourseType = Literal["general", "major", "remote", "metamorphosis"]
_COURSE_TYPE_CODES: dict[str, str] = {
    "general": "10",
    "major": "30",
    "remote": "60",
    "metamorphosis": "61",
}

_BR_PATTERN = re.compile(r"\s*<br>\s*")


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_courses(content: bytes) -> list[CourseSummary]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise ParseError("강좌 검색 응답") from None

    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError("강좌 검색 응답")

    return [
        CourseSummary(
            course_code=str(row.get("subjectCd", "")),
            name=str(row.get("subjectNmKor", "")),
            professor=str(row.get("nm", "")),
            category=str(row.get("isuCdNm", "")),
            credit=_int_or_zero(row.get("credit")),
            grade=_int_or_zero(row.get("grade")),
            schedule=_BR_PATTERN.sub("\n", str(row.get("time", ""))).strip(),
            capacity=_int_or_zero(row.get("limitNum")),
        )
        for row in rows
    ]


def search_courses(
    department_code: str,
    course_type: CourseType = "major",
    grade: int | None = None,
    keyword: str = "",
) -> CourseList:
    """개설 강좌를 검색한다.

    department_code는 list_departments가 돌려준 값을 그대로 넘길 것.
    course_type: general(교양), major(전공), remote(원격강좌), metamorphosis(메타모포시스)
    grade를 생략하면 전 학년, keyword를 생략하면 학과 전체 강좌를 검색한다.
    실시간 신청 인원은 제공하지 않는다 — capacity(정원)만 제공한다.
    """
    cookies = require_session("sugang")
    response = fetch_authenticated(
        LECT_LIST_URL,
        cookies=cookies,
        method="POST",
        params={"fake": str(int(time.time() * 1000))},
        headers={"Referer": "https://sugang.mjc.ac.kr/core/home"},
        data={
            "pCourseCd": "",
            "pSugangGbn": "S",
            "pSelMetaA": "", "pSelMetaB": "",
            "pSelMetaUnionA": "", "pSelMetaUnionB": "", "pSelMetaUnionC": "",
            "pParams": "",
            "pComboSugangCd": _COURSE_TYPE_CODES[course_type],
            "pComboGrade": str(grade) if grade is not None else "",
            "pComboClsMajCd": department_code,
            "pSearchNm": keyword,
        },
    )
    require_active_session(response, "sugang")
    return CourseList(courses=parse_courses(response.content))


def register(mcp) -> None:
    mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True)
    )(search_courses)
