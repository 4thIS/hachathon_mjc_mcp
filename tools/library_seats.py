"""도서관 실시간 좌석 현황.

인증이 필요 없는 XML API를 호출한다. 응답에 UTF-8 BOM이 붙어 오므로
common.parse.parse_xml이 이를 처리한다.
"""

import time
from datetime import datetime, timedelta, timezone

from mcp.types import ToolAnnotations

from common.cache import with_fallback
from common.errors import ParseError
from common.http import fetch
from common.models import LibrarySeatReport, ReadingRoom
from common.parse import parse_xml

SEAT_URL = "http://211.117.47.133:8090/mobile/PA/seatRoomStatusListXML.php"
KST = timezone(timedelta(hours=9))


def _text(item, tag: str) -> str:
    element = item.find(tag)
    return (element.text or "").strip() if element is not None else ""


def parse_seats(content: bytes) -> list[ReadingRoom]:
    root = parse_xml(content)
    rooms: list[ReadingRoom] = []

    for item in root.findall("item"):
        name = _text(item, "strRoomNm")
        if not name:
            continue
        rooms.append(
            ReadingRoom(
                name=name,
                total=int(_text(item, "strTotalSeat") or 0),
                in_use=int(_text(item, "strUseSeat") or 0),
                available=int(_text(item, "strRemainSeat") or 0),
            )
        )

    if not rooms:
        raise ParseError("도서관 좌석 정보")
    return rooms


def _fetch_report() -> dict:
    params = {
        "_search": "false",
        "nd": str(int(time.time() * 1000)),
        "rows": "30",
        "page": "1",
        "sidx": "",
        "sord": "asc",
    }
    rooms = parse_seats(fetch(SEAT_URL, params=params))
    report = LibrarySeatReport(rooms=rooms, measured_at=datetime.now(KST))
    return report.model_dump(mode="json")


def get_library_seats() -> LibrarySeatReport:
    """명지전문대 도서관의 실시간 열람실 좌석 현황을 조회한다.

    집중학습공간, 개방형학습공간, 미디어실 세 곳의 총 좌석 수와
    현재 사용 중인 좌석, 남은 좌석을 반환한다.
    """
    data, stale_age_min = with_fallback("library_seats", _fetch_report)
    report = LibrarySeatReport.model_validate(data)
    report.stale_age_min = stale_age_min
    return report


def register(mcp) -> None:
    mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True)
    )(get_library_seats)
