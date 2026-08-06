"""학사·장학·채용·일반 공지 게시판 조회.

게시판 내부 파라미터(menu_idx, BM/BD 코드)는 AI에게 노출하지 않는다.
AI는 의미 있는 카테고리 이름만 쓰고, 상세 조회에는 목록이 돌려준
불투명 ID를 그대로 넘긴다.
"""

import re
from typing import Literal

from mcp.types import ToolAnnotations

from common.cache import with_fallback
from common.errors import ParseError
from common.http import fetch
from common.models import NoticeDetail, NoticeList, NoticeSummary
from common.parse import parse_html

LIST_URL = "https://www.mjc.ac.kr/bbs/data/list.do"
VIEW_URL = "https://www.mjc.ac.kr/bbs/data/view.do"
MAX_BODY_CHARS = 4000
_IMAGE_ONLY_BODY = (
    "(이 공지의 본문은 이미지로 작성되어 텍스트를 추출할 수 없습니다. "
    "첨부파일 목록과 제목을 참고하세요.)"
)

# 카테고리 키 -> (menu_idx, 사람이 읽는 게시판 이름)
BOARDS: dict[str, tuple[int, str]] = {
    "general": (66, "공지사항"),
    "academic": (169, "학사공지"),
    "scholarship": (208, "장학공지"),
    "job": (2617, "채용공지"),
}

NoticeCategory = Literal["general", "academic", "scholarship", "job"]

_FN_VIEW = re.compile(r"fn_view\('(BM\d+)','(BD\d+)'")


def parse_notice_list(content: bytes, menu_idx: int) -> list[NoticeSummary]:
    soup = parse_html(content)
    table = soup.select_one("table.board_list")
    if table is None:
        raise ParseError("공지 목록")

    notices: list[NoticeSummary] = []
    for row in table.select("tr"):
        link = row.select_one("td.cell_type01 a[href*='fn_view']")
        if link is None:
            continue
        match = _FN_VIEW.search(link.get("href", ""))
        if match is None:
            continue

        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # 첫 칸이 행마다 번호/공지 아이콘으로 달라지므로 뒤에서부터 센다.
        views_text = cells[-1].get_text(strip=True)
        notices.append(
            NoticeSummary(
                notice_id=f"{menu_idx}:{match.group(1)}:{match.group(2)}",
                title=link.get_text(strip=True),
                department=cells[-3].get_text(strip=True),
                posted_on=cells[-2].get_text(strip=True),
                views=int(views_text) if views_text.isdigit() else 0,
                pinned="cell_notice" in (row.get("class") or []),
            )
        )

    return notices


def _fetch_list(menu_idx: int) -> dict:
    notices = parse_notice_list(
        fetch(LIST_URL, params={"menu_idx": str(menu_idx)}), menu_idx
    )
    return {"notices": [n.model_dump(mode="json") for n in notices]}


def search_notices(
    category: NoticeCategory = "academic", limit: int = 10
) -> NoticeList:
    """명지전문대 공지 게시판의 최신 글 목록을 조회한다.

    category: general(일반 공지사항), academic(학사), scholarship(장학), job(채용)
    본문 전문이 필요하면 결과의 notice_id를 get_notice에 넘긴다.
    """
    if category not in BOARDS:
        raise ParseError(f"알 수 없는 게시판 '{category}'")
    menu_idx, board_name = BOARDS[category]

    data, stale_age_min = with_fallback(
        f"notices_{category}", lambda: _fetch_list(menu_idx)
    )
    notices = [NoticeSummary.model_validate(n) for n in data["notices"]]
    return NoticeList(
        category=board_name,
        notices=notices[: max(1, limit)],
        stale_age_min=stale_age_min,
    )


def parse_notice_detail(content: bytes) -> NoticeDetail:
    soup = parse_html(content)
    view = soup.select_one("div.board_view")
    if view is None:
        raise ParseError("공지 본문")

    title_element = view.select_one("h2.tit")

    # 작성자/조회수/날짜는 th-td 쌍으로 들어 있다. 순서에 의존하지 않고 라벨로 찾는다.
    info: dict[str, str] = {}
    for header in view.select("table.tbl_data th"):
        cell = header.find_next_sibling("td")
        if cell is not None:
            info[header.get_text(strip=True)] = cell.get_text(strip=True)

    memo = view.select_one("#divMemo")
    body = memo.get_text("\n", strip=True) if memo is not None else ""
    truncated = len(body) > MAX_BODY_CHARS
    body = body[:MAX_BODY_CHARS] if body else _IMAGE_ONLY_BODY

    attachments = [
        link.get_text(strip=True)
        for link in view.select("a[href*='fn_egov_downFile']")
        if link.get_text(strip=True)
    ]

    views_text = info.get("조회수", "")
    return NoticeDetail(
        title=title_element.get_text(strip=True) if title_element else "",
        department=info.get("작성자", ""),
        posted_on=info.get("날짜", ""),
        views=int(views_text) if views_text.isdigit() else 0,
        body=body,
        attachments=attachments,
        truncated=truncated,
    )


def get_notice(notice_id: str) -> NoticeDetail:
    """공지 한 건의 본문 전문과 첨부파일 목록을 조회한다.

    notice_id는 반드시 search_notices가 돌려준 값을 그대로 넘겨야 한다.
    사람이 임의로 만들어낼 수 있는 형식이 아니다.
    """
    parts = notice_id.split(":")
    if len(parts) != 3 or not parts[0].isdigit():
        raise ParseError("공지 식별자 형식")
    menu_idx, bbs_mst_idx, data_idx = parts

    content = fetch(
        VIEW_URL,
        params={
            "menu_idx": menu_idx,
            "bbs_mst_idx": bbs_mst_idx,
            "data_idx": data_idx,
        },
    )
    return parse_notice_detail(content)


def register(mcp) -> None:
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    mcp.tool(annotations=read_only)(search_notices)
    mcp.tool(annotations=read_only)(get_notice)
