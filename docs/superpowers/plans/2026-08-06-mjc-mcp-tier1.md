# 명지전문대 MCP 서버 Tier 1 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인이 필요 없는 학교 데이터(도서관 좌석, 공지 게시판)를 AI 에이전트가 조회할 수 있는 MCP 서버를 완성한다.

**Architecture:** `server.py`는 각 툴 모듈의 `register(mcp)`를 호출만 한다. 툴 함수는 MCP에 의존하지 않는 평범한 함수로 작성하고 등록만 데코레이터로 처리한다. HTTP·파싱·에러·캐시는 `common/`에 모아 세 툴이 공유한다. 모든 응답은 Pydantic 모델로 반환해 output schema를 자동 생성한다.

**Tech Stack:** Python 3.10+, 공식 `mcp` SDK v2(`MCPServer`), `httpx`, `beautifulsoup4` + `lxml`, `pydantic`, `pytest`

설계 근거는 `docs/design.md` 참고.

## Global Constraints

- **stdio에서 stdout은 JSON-RPC 채널이다.** 어떤 파일에서도 `print()`를 쓰지 않는다. 로깅은 `logging`으로 stderr에만 보낸다.
- **HTTP 응답은 `resp.text`가 아니라 `resp.content`(bytes)로 다룬다.** 인코딩 판단은 파서에게 맡긴다.
- **테스트 fixture는 bytes 원본으로 저장한다.** 텍스트로 저장하면 인코딩 버그가 fixture에서 사라진다.
- **에러 메시지에 원문 HTML·응답 헤더·쿠키를 담지 않는다.** 예외 타입명과 고정 문구만 쓴다.
- 모든 HTTP 요청에 타임아웃을 명시한다: `httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)`
- 모든 HTTP 요청에 `follow_redirects=False`를 쓴다.
- 동일 호스트 연속 요청 사이 최소 1.0초 간격을 둔다.
- User-Agent: `MJC-MCP/0.1 (Myongji College hackathon project; +https://github.com/4thIS/hachathon_mjc_mcp)`
- 커밋 메시지는 한 줄로 짧게 쓰고, 끝에 빈 줄 후 `Co-Authored-By: Claude <noreply@anthropic.com>`를 붙인다.
- 커밋은 자기 개인 작업 브랜치(`tier1/<이름>`)에 한다. `main`에 직접 커밋하지 않는다. 자세한 내용은 아래 "브랜치 운영과 역할 분담" 참고.

## 검증된 사실 (2026-08-06 실제 호출로 확인)

**도서관 좌석 API** — 인증 불필요, 응답에 UTF-8 BOM 있음
```
GET http://211.117.47.133:8090/mobile/PA/seatRoomStatusListXML.php
    ?_search=false&nd=<ms timestamp>&rows=30&page=1&sidx=&sord=asc
```
```xml
<?xml version='1.0' encoding='utf-8'?>
<root><data><page>1</page><total></total><records></records></data>
<item>
  <strRoomNo><![CDATA[1]]></strRoomNo>
  <strRoomNm><![CDATA[집중학습공간]]></strRoomNm>
  <strTotalSeat><![CDATA[72]]></strTotalSeat>
  <strUseSeat><![CDATA[0]]></strUseSeat>
  <strFixSeat><![CDATA[0]]></strFixSeat>
  <strRemainSeat><![CDATA[72]]></strRemainSeat>
  <strMapUrl><![CDATA[./xml_seat_map.php?param_room_no=1&call_page=admin&room_gb=]]></strMapUrl>
</item>
... item 3개 (집중학습공간 72석 / 개방형학습공간 146석 / 미디어실 44석)
</root>
```

**공지 게시판** — 인증 불필요, UTF-8, 순수 HTML

| menu_idx | 게시판 | 카테고리 키 |
|---|---|---|
| 66 | 공지사항 | `general` |
| 169 | 학사공지 | `academic` |
| 208 | 장학공지 | `scholarship` |
| 2617 | 채용공지 | `job` |

목록 `GET https://www.mjc.ac.kr/bbs/data/list.do?menu_idx=<ID>`
```html
<table class="board_list">
  <tr class="cell_notice">          <!-- 상단 고정 공지. 일반 글은 그냥 <tr> -->
    <td><img alt="공지" /></td>      <!-- 일반 글은 여기가 번호(예: 381) -->
    <td class="cell_type01"><a href="javascript:fn_view('BM0000000025','BD0050388084','');">제목</a></td>
    <td><img alt="기타 첨부파일 있음" /></td>
    <td>교육과정혁신팀</td>
    <td>2026-08-04</td>
    <td>893</td>
  </tr>
```
첫 번째 `<td>`의 내용이 행마다 다르므로 **뒤에서부터 세는 것이 안전하다**: `tds[-1]`=조회수, `tds[-2]`=날짜, `tds[-3]`=부서.

상세 `GET https://www.mjc.ac.kr/bbs/data/view.do?menu_idx=<ID>&bbs_mst_idx=<BM>&data_idx=<BD>`
```html
<div class="board_view">
  <h2 class="tit">제목</h2>
  <table class="tbl_data">
    <tr><th>작성자</th><td>교육과정혁신팀</td>
        <th>조회수</th><td>895</td>
        <th>날짜</th><td>2026-08-04</td></tr>
    <tr><th>첨부파일</th><td colspan="5">
      <a href="javascript:fn_egov_downFile('BM...','BD...','BF...')">파일명.pdf</a>
    </td></tr>
  </table>
  <div class="memo" id="divMemo"> 본문 </div>
</div>
```
**중요:** 본문이 이미지로만 작성된 공지가 흔하다(확인된 사례: `#divMemo` 안에 `<img>`만 있고 텍스트 없음). 텍스트가 비면 첨부파일 목록을 안내하는 문구로 대체해야 한다.

`robots.txt`는 `User-agent: * / Allow: /` — 전면 허용.

## File Structure

| 파일 | 책임 |
|---|---|
| `requirements.txt` | 의존성 버전 고정 |
| `common/errors.py` | 툴이 던지는 에러 타입. 원문을 담지 않는다 |
| `common/http.py` | httpx GET 래퍼. 타임아웃·UA·호스트별 1초 간격 |
| `common/parse.py` | bytes → BeautifulSoup / lxml. BOM 처리를 여기 한 곳에 |
| `common/cache.py` | 조회 실패 시 마지막 성공 데이터로 폴백 |
| `common/models.py` | Pydantic 반환 모델 전부 |
| `tools/library_seats.py` | 도서관 좌석 조회 + `register(mcp)` |
| `tools/notices.py` | 공지 목록·상세 조회 + `register(mcp)` |
| `server.py` | MCP 진입점. stderr 로깅 설정 + register 호출 |
| `tests/fixtures/*.xml,*.html` | 실제 응답 원본(bytes) |
| `tests/test_library_seats.py` | 좌석 파서 테스트 |
| `tests/test_notices.py` | 공지 파서 테스트 |
| `README.md` | 제출물. 설치법·툴 표·한계 |

## 브랜치 운영과 역할 분담

Tier별 통합 브랜치를 두고, 그 아래 개인 작업 브랜치를 만든다. 개인 작업은 통합 브랜치에 먼저 머지하고, 최종적으로 팀장이 통합 브랜치를 `main`에 머지한다. `main`은 항상 동작하는 상태로 유지해 데모 안전망으로 쓴다.

```
main
 └── tier1/merged        (Tier 1 통합 브랜치)
      ├── tier1/dh       (개인 작업)
      ├── tier1/<이름>
      └── tier1/<이름>
```

**`tier1`이라는 이름의 브랜치는 만들지 않는다.** git은 브랜치를 `.git/refs/heads/` 아래 파일로 저장하므로, `tier1`(파일)과 `tier1/dh`(디렉토리 필요)는 공존할 수 없다. 통합 브랜치를 `tier1/merged`로 두면 `tier1`이 디렉토리로만 쓰여 문제가 없다(검증 완료).

```bash
# 통합 브랜치 생성 (팀장이 한 번만)
git checkout -b tier1/merged main
git push -u origin tier1/merged

# 개인 작업 브랜치 (각자)
git checkout -b tier1/dh tier1/merged

# 작업 완료 후 통합 브랜치로
git checkout tier1/merged && git pull
git merge tier1/dh && git push
```

**역할 분담**

| 담당 | 작업 | 브랜치 |
|---|---|---|
| 먼저 시작하는 사람 | Task 1 (공통 레이어) | **`tier1/merged`에 직접** |
| A | Task 2 (도서관 좌석) | `tier1/merged`에서 분기 |
| B | Task 3 + Task 4 (공지 목록·상세) | `tier1/merged`에서 분기 |
| 팀장 | Task 5 (통합·README) | A와 B 머지 후 `tier1/merged`에서 |

- **Task 1은 개인 브랜치를 거치지 않는다.** `common/`이 없으면 아무도 툴을 만들 수 없으므로, 완료 즉시 `tier1/merged`에 푸시해 나머지가 분기할 수 있게 한다.
- **Task 3과 4는 반드시 한 사람이 맡는다.** 같은 파일(`tools/notices.py`)을 수정하므로 나누면 충돌한다.
- Task 2와 Task 3~4는 서로 다른 파일이라 **병렬로 진행할 수 있다.**
- 각 태스크의 커밋 단계는 자기 개인 브랜치에 커밋하는 것을 의미한다. `main`에 직접 커밋하지 않는다.

**이번 계획의 범위 밖:** 학사일정 툴(`get_academic_calendar`)은 스크래핑 구조 조사가 별도 세션에서 진행 중이다. 구조가 확보되면 `tools/academic_calendar.py`를 같은 패턴으로 추가하고 `server.py`에 `register` 한 줄을 더한다. 기존 코드에는 영향이 없다.

---

### Task 1: 공통 기반 (프로젝트 뼈대 + common 레이어)

> **✅ 완료됨 (커밋 `fbca800`).** 코드 리뷰에서 이 태스크의 계획 코드에 결함 5건이 발견되어 아래 스텝의 코드와 실제 구현이 다릅니다. **공개 함수 시그니처는 전부 동일**하므로 Task 2~5에는 영향이 없지만, 다음 두 가지는 알고 있어야 합니다.
>
> - **`parse_xml`·`parse_html`이 파싱 실패 시 스스로 `ParseError`를 던집니다.** 호출부에서 `try/except`로 감쌀 필요가 없습니다. (원래 계획은 예외를 그대로 흘려보내 폴백 캐시가 우회되는 결함이 있었습니다.)
> - **재시도 대기는 `MIN_INTERVAL_SEC`(1.0초)로 통일**되었고 `RETRY_DELAY_SEC` 상수는 삭제되었습니다.
>
> 실제 구현은 `common/` 아래 파일을 직접 읽으세요.

**Files:**
- Create: `requirements.txt`, `common/__init__.py`, `common/errors.py`, `common/http.py`, `common/parse.py`, `common/cache.py`, `common/models.py`, `tools/__init__.py`, `tests/__init__.py`
- Test: `tests/test_common.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `common.errors.ToolError`, `FetchError(reason: str)`, `ParseError(what: str)`
  - `common.http.fetch(url: str, *, params: dict[str, str] | None = None) -> bytes`
  - `common.parse.parse_html(content: bytes) -> BeautifulSoup`
  - `common.parse.parse_xml(content: bytes) -> lxml.etree._Element`
  - `common.cache.with_fallback(key: str, fetch_fn: Callable[[], dict]) -> tuple[dict, int | None]`
  - `common.models.ReadingRoom`, `LibrarySeatReport`, `NoticeSummary`, `NoticeList`, `NoticeDetail`

- [ ] **Step 1: SDK import 경로를 실제로 확인한다**

먼저 의존성을 설치한다.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install "mcp>=2.0" httpx beautifulsoup4 lxml pydantic pytest
```

그다음 import가 실제로 되는지 확인한다. **이 계획은 `MCPServer`가 `mcp.server`에 있다는 것만 공식 문서로 확인했고, `ToolAnnotations`의 경로는 확인하지 않았다.**

```bash
.venv/Scripts/python -c "from mcp.server import MCPServer; print('MCPServer OK')"
.venv/Scripts/python -c "from mcp.types import ToolAnnotations; print('ToolAnnotations OK')"
```

`ToolAnnotations` import가 실패하면 실제 경로를 찾는다.

```bash
.venv/Scripts/python -c "import mcp, pkgutil; print([m.name for m in pkgutil.iter_modules(mcp.__path__)])"
```

찾은 경로를 Task 2, 3의 코드에 반영한다. 끝까지 못 찾으면 `annotations=` 인자를 아예 빼고 진행한다(툴은 정상 동작하며, 클라이언트 자동 승인 힌트만 없어진다).

- [ ] **Step 2: `requirements.txt` 작성**

Step 1에서 설치된 실제 버전을 고정한다.

```bash
.venv/Scripts/python -m pip freeze | grep -iE "^(mcp|httpx|beautifulsoup4|lxml|pydantic|pytest)==" > requirements.txt
cat requirements.txt
```

- [ ] **Step 3: 실패하는 테스트 작성**

`tests/test_common.py`:

```python
import pytest

from common.errors import FetchError, ParseError, ToolError
from common.parse import parse_html, parse_xml


def test_errors_are_tool_errors():
    assert isinstance(FetchError("ConnectTimeout"), ToolError)
    assert isinstance(ParseError("공지 목록"), ToolError)


def test_error_message_does_not_leak_raw_content():
    """에러 메시지에 원문이 섞이면 안 된다. 타입명과 고정 문구만."""
    message = str(FetchError("ConnectTimeout"))
    assert "ConnectTimeout" in message
    assert "<html" not in message


def test_parse_xml_strips_utf8_bom():
    """도서관 API 응답에는 BOM이 붙어 있다."""
    content = b"\xef\xbb\xbf<?xml version='1.0' encoding='utf-8'?><root><a>1</a></root>"
    root = parse_xml(content)
    assert root.find("a").text == "1"


def test_parse_xml_reads_cdata():
    content = b"<root><item><nm><![CDATA[\xea\xb0\x95\xec\x9d\x98\xec\x8b\xa4]]></nm></item></root>"
    root = parse_xml(content)
    assert root.find("item/nm").text == "강의실"


def test_parse_html_decodes_utf8_from_bytes():
    content = '<html><body><p class="x">한글</p></body></html>'.encode("utf-8")
    soup = parse_html(content)
    assert soup.select_one("p.x").get_text() == "한글"
```

- [ ] **Step 4: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 5: `common/errors.py` 구현**

```python
"""툴이 AI 에이전트에게 돌려주는 에러.

원문 응답·헤더·쿠키를 절대 담지 않는다. 예외 타입명과 고정 문구만 쓴다.
"""


class ToolError(Exception):
    """MCP 툴 실행 중 발생한, 사용자에게 그대로 보여줄 수 있는 오류."""


class FetchError(ToolError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            f"학교 서버 조회에 실패했습니다 ({reason}). 잠시 후 다시 시도해 주세요."
        )


class ParseError(ToolError):
    def __init__(self, what: str) -> None:
        super().__init__(
            f"{what}을(를) 해석하지 못했습니다. 사이트 구조가 변경되었을 수 있습니다."
        )
```

- [ ] **Step 6: `common/parse.py` 구현**

```python
"""bytes 응답을 파서에 넘기는 유일한 통로.

인코딩 판단을 이 파일 한 곳에 모은다. 호출자는 절대 resp.text를 쓰지 않는다.
"""

from bs4 import BeautifulSoup
from lxml import etree

_UTF8_BOM = b"\xef\xbb\xbf"


def parse_html(content: bytes) -> BeautifulSoup:
    """bytes를 그대로 넘겨 파서가 meta charset 선언을 보고 판단하게 한다."""
    return BeautifulSoup(content, "lxml")


def parse_xml(content: bytes) -> etree._Element:
    """XML 선언이 있는 bytes에 BOM이 붙어 있으면 lxml이 거부하므로 먼저 제거한다."""
    if content.startswith(_UTF8_BOM):
        content = content[len(_UTF8_BOM):]
    return etree.fromstring(content)
```

- [ ] **Step 7: `common/__init__.py`, `tools/__init__.py`, `tests/__init__.py` 생성 (빈 파일)**

```bash
touch common/__init__.py tools/__init__.py tests/__init__.py
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_common.py -v`
Expected: PASS (5 passed)

- [ ] **Step 9: `common/http.py` 구현**

```python
"""학교 시스템에 대한 GET 요청 통로.

- 타임아웃을 반드시 건다 (무한 대기 시 MCP 툴이 hang된다)
- 호스트별로 최소 1초 간격을 강제한다 (데이터 수집 원칙)
- 응답은 bytes로 돌려준다. 인코딩 판단은 common.parse의 몫이다.
"""

import time

import httpx

from common.errors import FetchError

USER_AGENT = (
    "MJC-MCP/0.1 (Myongji College hackathon project; "
    "+https://github.com/4thIS/hachathon_mjc_mcp)"
)
TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)
MIN_INTERVAL_SEC = 1.0
RETRY_DELAY_SEC = 0.5

_last_request_at: dict[str, float] = {}


def _get_once(url: str, params: dict[str, str] | None) -> bytes:
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
    return response.content


def fetch(url: str, *, params: dict[str, str] | None = None) -> bytes:
    """GET 요청 후 응답 본문을 bytes로 반환한다.

    실패 시 0.5초 뒤 한 번만 재시도한다. 조회 전용이므로 재시도가 안전하다.
    """
    host = httpx.URL(url).host
    elapsed = time.monotonic() - _last_request_at.get(host, 0.0)
    if elapsed < MIN_INTERVAL_SEC:
        time.sleep(MIN_INTERVAL_SEC - elapsed)

    try:
        try:
            return _get_once(url, params)
        except httpx.HTTPError:
            time.sleep(RETRY_DELAY_SEC)
            return _get_once(url, params)
    except httpx.HTTPError as exc:
        # 원문을 담지 않기 위해 타입명만 넘기고 예외 체인을 끊는다.
        raise FetchError(type(exc).__name__) from None
    finally:
        _last_request_at[host] = time.monotonic()
```

- [ ] **Step 10: `common/models.py` 구현**

```python
"""툴 반환 모델.

반환 타입 어노테이션이 곧 MCP output schema가 되므로,
Field(description=...)이 AI가 읽는 스키마 설명이 된다.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ReadingRoom(BaseModel):
    name: str = Field(description="열람실 이름")
    total: int = Field(description="총 좌석 수")
    in_use: int = Field(description="현재 사용 중인 좌석 수")
    available: int = Field(description="현재 이용 가능한 잔여 좌석 수")


class LibrarySeatReport(BaseModel):
    rooms: list[ReadingRoom] = Field(description="열람실별 좌석 현황")
    measured_at: datetime = Field(
        description="이 좌석 수치를 실제로 조회한 시각(KST). "
        "실시간 데이터이므로 오래된 값을 현재 값처럼 인용하지 말 것."
    )
    stale_age_min: int | None = Field(
        default=None,
        description="학교 서버 조회에 실패해 캐시된 값을 반환한 경우, "
        "그 값이 몇 분 전 것인지. 실시간 조회에 성공했다면 null.",
    )


class NoticeSummary(BaseModel):
    notice_id: str = Field(
        description="get_notice에 그대로 넘길 식별자. 형식은 내부 구현이므로 해석하지 말 것."
    )
    title: str = Field(description="공지 제목")
    department: str = Field(description="작성 부서")
    posted_on: str = Field(description="작성일 (YYYY-MM-DD)")
    views: int = Field(description="조회수")
    pinned: bool = Field(description="상단 고정 공지 여부")


class NoticeList(BaseModel):
    category: str = Field(description="조회한 게시판 이름")
    notices: list[NoticeSummary] = Field(description="공지 목록. 최신순.")
    stale_age_min: int | None = Field(
        default=None,
        description="학교 서버 조회에 실패해 캐시된 값을 반환한 경우, "
        "그 값이 몇 분 전 것인지. 실시간 조회에 성공했다면 null.",
    )


class NoticeDetail(BaseModel):
    title: str = Field(description="공지 제목")
    department: str = Field(description="작성 부서")
    posted_on: str = Field(description="작성일 (YYYY-MM-DD)")
    views: int = Field(description="조회수")
    body: str = Field(
        description="본문 텍스트. 본문이 이미지로만 작성된 공지는 "
        "그 사실을 알리는 안내 문구가 들어간다."
    )
    attachments: list[str] = Field(description="첨부파일 이름 목록")
    truncated: bool = Field(description="본문이 길이 제한으로 잘렸는지 여부")
```

- [ ] **Step 11: `common/cache.py` 구현**

```python
"""조회 실패 시 마지막 성공 데이터로 폴백한다.

라이브 데모 중 학교 서버나 시연장 네트워크가 죽어도 툴이 답을 내놓게 하는 안전망.
캐시된 값을 반환할 때는 몇 분 전 것인지 함께 알려 AI가 실시간 값으로 오인하지 않게 한다.
"""

import json
import time
from pathlib import Path
from typing import Callable

from common.errors import ToolError

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def with_fallback(
    key: str, fetch_fn: Callable[[], dict]
) -> tuple[dict, int | None]:
    """(데이터, 캐시 나이(분)) 를 반환한다. 실시간 조회에 성공하면 나이는 None.

    캐시도 없이 조회에 실패하면 원래 에러를 그대로 올린다.
    """
    path = CACHE_DIR / f"{key}.json"

    try:
        data = fetch_fn()
    except ToolError:
        if not path.exists():
            raise
        cached = json.loads(path.read_text(encoding="utf-8"))
        age_min = int((time.time() - cached["saved_at"]) / 60)
        return cached["data"], age_min

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"saved_at": time.time(), "data": data}, ensure_ascii=False),
        encoding="utf-8",
    )
    return data, None
```

- [ ] **Step 12: 캐시·HTTP 테스트 추가**

`tests/test_common.py` 끝에 이어 붙인다.

```python
def test_with_fallback_returns_fresh_data_and_no_age(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    data, age = cache.with_fallback("k", lambda: {"v": 1})
    assert data == {"v": 1}
    assert age is None


def test_with_fallback_uses_cache_when_fetch_fails(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.with_fallback("k", lambda: {"v": 1})

    def boom():
        raise FetchError("ConnectTimeout")

    data, age = cache.with_fallback("k", boom)
    assert data == {"v": 1}
    assert age == 0


def test_with_fallback_reraises_when_no_cache(tmp_path, monkeypatch):
    from common import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    def boom():
        raise FetchError("ConnectTimeout")

    with pytest.raises(FetchError):
        cache.with_fallback("missing", boom)
```

- [ ] **Step 13: 전체 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: PASS (8 passed)

- [ ] **Step 14: `.gitignore`에 `.cache/`가 있는지 확인**

Run: `grep -n "cache" .gitignore`
Expected: `.cache/` 줄이 보인다. 없으면 추가한다.

- [ ] **Step 15: 커밋**

```bash
git add requirements.txt common/ tools/__init__.py tests/
git commit -m "feat: 공통 HTTP·파싱·캐시·모델 레이어 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 도서관 좌석 툴

**Files:**
- Create: `tools/library_seats.py`, `tests/test_library_seats.py`, `tests/fixtures/library_seats.xml`
- Test: `tests/test_library_seats.py`

**Interfaces:**
- Consumes: `common.http.fetch`, `common.parse.parse_xml`, `common.cache.with_fallback`, `common.errors.ParseError`, `common.models.ReadingRoom`, `common.models.LibrarySeatReport`
- Produces:
  - `tools.library_seats.get_library_seats() -> LibrarySeatReport`
  - `tools.library_seats.parse_seats(content: bytes) -> list[ReadingRoom]`
  - `tools.library_seats.register(mcp) -> None`

- [ ] **Step 1: 실제 응답을 fixture로 저장**

```bash
mkdir -p tests/fixtures
curl -s "http://211.117.47.133:8090/mobile/PA/seatRoomStatusListXML.php?_search=false&nd=1754480000000&rows=30&page=1&sidx=&sord=asc" -o tests/fixtures/library_seats.xml
```

BOM과 CDATA가 그대로 살아 있는지 확인한다.

Run: `head -c 120 tests/fixtures/library_seats.xml | xxd | head -3`
Expected: 첫 3바이트가 `efbb bf`(BOM)이고 이어서 `<?xml`이 보인다.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_library_seats.py`:

```python
from pathlib import Path

import pytest

from common.errors import ParseError
from tools.library_seats import parse_seats

FIXTURE = Path(__file__).parent / "fixtures" / "library_seats.xml"


def test_parses_three_reading_rooms():
    rooms = parse_seats(FIXTURE.read_bytes())
    assert len(rooms) == 3
    assert [r.name for r in rooms] == ["집중학습공간", "개방형학습공간", "미디어실"]


def test_parses_seat_counts():
    rooms = {r.name: r for r in parse_seats(FIXTURE.read_bytes())}
    assert rooms["집중학습공간"].total == 72
    assert rooms["개방형학습공간"].total == 146
    assert rooms["미디어실"].total == 44


def test_available_and_in_use_are_integers():
    for room in parse_seats(FIXTURE.read_bytes()):
        assert isinstance(room.in_use, int)
        assert isinstance(room.available, int)
        assert room.in_use + room.available <= room.total


def test_raises_parse_error_when_no_items():
    with pytest.raises(ParseError):
        parse_seats(b"<root><data><page>1</page></data></root>")
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_library_seats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.library_seats'`

- [ ] **Step 4: `tools/library_seats.py` 구현**

Task 1 Step 1에서 `ToolAnnotations` import에 실패했다면 `register()`에서 `annotations=` 인자를 빼고 쓴다.

```python
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
```

`measured_at`은 캐시에 함께 저장되므로, 폴백 시에도 **조회 당시 시각**이 유지된다. 이것이 `stale_age_min`과 짝을 이뤄 AI가 오래된 값을 현재 값으로 착각하지 않게 한다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_library_seats.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 실제 네트워크로 수동 확인**

```bash
.venv/Scripts/python -c "from tools.library_seats import get_library_seats; r = get_library_seats(); print(r.model_dump_json(indent=2))"
```

Expected: 열람실 3개가 나오고 `measured_at`이 현재 시각, `stale_age_min`이 `null`이다.

- [ ] **Step 7: 폴백 동작 수동 확인**

네트워크를 끊거나 `SEAT_URL`을 잠시 잘못된 값으로 바꾼 뒤 같은 명령을 실행한다.

Expected: 에러 대신 직전 데이터가 나오고 `stale_age_min`이 0 이상의 숫자다. 확인 후 URL을 원래대로 되돌린다.

- [ ] **Step 8: 커밋**

```bash
git add tools/library_seats.py tests/test_library_seats.py tests/fixtures/library_seats.xml
git commit -m "feat: 도서관 실시간 좌석 조회 툴 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 공지 목록 툴

**Files:**
- Create: `tools/notices.py`, `tests/test_notices.py`, `tests/fixtures/notices_academic.html`
- Test: `tests/test_notices.py`

**Interfaces:**
- Consumes: `common.http.fetch`, `common.parse.parse_html`, `common.cache.with_fallback`, `common.errors.ParseError`, `common.models.NoticeSummary`, `common.models.NoticeList`
- Produces:
  - `tools.notices.BOARDS: dict[str, tuple[int, str]]`
  - `tools.notices.NoticeCategory` (Literal 타입)
  - `tools.notices.parse_notice_list(content: bytes, menu_idx: int) -> list[NoticeSummary]`
  - `tools.notices.search_notices(category: NoticeCategory = "academic", limit: int = 10) -> NoticeList`
  - `tools.notices.register(mcp) -> None` (Task 4에서 `get_notice`도 여기에 등록한다)

- [ ] **Step 1: 실제 응답을 fixture로 저장**

```bash
curl -s "https://www.mjc.ac.kr/bbs/data/list.do?menu_idx=169" -o tests/fixtures/notices_academic.html
```

Run: `grep -c "fn_view('BM" tests/fixtures/notices_academic.html`
Expected: 10 이상의 숫자 (목록에 글이 들어 있음)

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_notices.py`:

```python
from pathlib import Path

import pytest

from common.errors import ParseError
from tools.notices import parse_notice_list

FIXTURE = Path(__file__).parent / "fixtures" / "notices_academic.html"


def test_parses_notices():
    notices = parse_notice_list(FIXTURE.read_bytes(), menu_idx=169)
    assert len(notices) > 0


def test_notice_has_title_and_korean_is_not_mojibake():
    notices = parse_notice_list(FIXTURE.read_bytes(), menu_idx=169)
    assert all(n.title for n in notices)
    joined = "".join(n.title for n in notices)
    assert "\ufffd" not in joined  # 인코딩이 깨지면 U+FFFD가 섞인다


def test_notice_id_encodes_menu_idx_and_codes():
    notices = parse_notice_list(FIXTURE.read_bytes(), menu_idx=169)
    menu_idx, bm, bd = notices[0].notice_id.split(":")
    assert menu_idx == "169"
    assert bm.startswith("BM")
    assert bd.startswith("BD")


def test_notice_date_and_views_are_parsed():
    notices = parse_notice_list(FIXTURE.read_bytes(), menu_idx=169)
    first = notices[0]
    assert len(first.posted_on) == 10 and first.posted_on[4] == "-"
    assert isinstance(first.views, int)
    assert first.department


def test_pinned_notices_are_flagged():
    notices = parse_notice_list(FIXTURE.read_bytes(), menu_idx=169)
    assert any(n.pinned for n in notices)


def test_raises_parse_error_when_table_missing():
    with pytest.raises(ParseError):
        parse_notice_list(b"<html><body>no table here</body></html>", menu_idx=169)
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_notices.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.notices'`

- [ ] **Step 4: `tools/notices.py` 구현**

```python
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
from common.models import NoticeList, NoticeSummary
from common.parse import parse_html

LIST_URL = "https://www.mjc.ac.kr/bbs/data/list.do"

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
    notices = parse_notice_list(fetch(LIST_URL, params={"menu_idx": str(menu_idx)}), menu_idx)
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


def register(mcp) -> None:
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    mcp.tool(annotations=read_only)(search_notices)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_notices.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 네 게시판 모두 실제로 동작하는지 수동 확인**

```bash
.venv/Scripts/python -c "
from tools.notices import search_notices
for c in ['general', 'academic', 'scholarship', 'job']:
    r = search_notices(c, limit=2)
    print(c, '|', r.category, '|', len(r.notices), '건 |', r.notices[0].title[:30])
"
```

Expected: 네 줄 모두 게시판 이름과 실제 제목이 한글로 정상 출력된다.

- [ ] **Step 7: 커밋**

```bash
git add tools/notices.py tests/test_notices.py tests/fixtures/notices_academic.html
git commit -m "feat: 공지 게시판 목록 조회 툴 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 공지 상세 툴

**Files:**
- Modify: `tools/notices.py` (`get_notice`, `parse_notice_detail` 추가, `register` 수정)
- Modify: `tests/test_notices.py` (상세 테스트 추가)
- Create: `tests/fixtures/notice_detail.html`

**Interfaces:**
- Consumes: Task 3의 `tools.notices` 모듈 내부 상수(`BOARDS`), `common.models.NoticeDetail`
- Produces:
  - `tools.notices.parse_notice_detail(content: bytes) -> NoticeDetail`
  - `tools.notices.get_notice(notice_id: str) -> NoticeDetail`

- [ ] **Step 1: 실제 상세 페이지를 fixture로 저장**

Task 3의 목록 fixture에서 실제 코드를 뽑아 그대로 내려받는다. 손으로 코드를 옮겨 적지 않도록 한 번에 처리한다.

```bash
.venv/Scripts/python -c "
import urllib.request
from pathlib import Path
from tools.notices import parse_notice_list

notice = parse_notice_list(Path('tests/fixtures/notices_academic.html').read_bytes(), 169)[0]
menu_idx, bm, bd = notice.notice_id.split(':')
url = f'https://www.mjc.ac.kr/bbs/data/view.do?menu_idx={menu_idx}&bbs_mst_idx={bm}&data_idx={bd}'
Path('tests/fixtures/notice_detail.html').write_bytes(urllib.request.urlopen(url, timeout=20).read())
print('saved:', notice.title)
"
```

Run: `grep -c 'class="board_view"' tests/fixtures/notice_detail.html`
Expected: `1`

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_notices.py` 끝에 이어 붙인다.

```python
from tools.notices import parse_notice_detail

DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "notice_detail.html"


def test_parses_detail_metadata():
    detail = parse_notice_detail(DETAIL_FIXTURE.read_bytes())
    assert detail.title
    assert detail.department
    assert len(detail.posted_on) == 10
    assert isinstance(detail.views, int)


def test_detail_body_is_never_empty():
    """본문이 이미지로만 작성된 공지가 흔하다. 빈 문자열을 돌려주면 안 된다."""
    detail = parse_notice_detail(DETAIL_FIXTURE.read_bytes())
    assert detail.body.strip()


def test_detail_has_no_mojibake():
    detail = parse_notice_detail(DETAIL_FIXTURE.read_bytes())
    assert "\ufffd" not in detail.title + detail.body


def test_detail_raises_parse_error_when_view_missing():
    with pytest.raises(ParseError):
        parse_notice_detail(b"<html><body>nothing</body></html>")


def test_get_notice_rejects_malformed_id():
    from tools.notices import get_notice

    with pytest.raises(ParseError):
        get_notice("not-a-valid-id")
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_notices.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_notice_detail'`

- [ ] **Step 4: `tools/notices.py`에 상세 조회 구현**

파일 상단 import에 `NoticeDetail`을 추가한다.

```python
from common.models import NoticeDetail, NoticeList, NoticeSummary
```

상수 영역에 다음을 추가한다.

```python
VIEW_URL = "https://www.mjc.ac.kr/bbs/data/view.do"
MAX_BODY_CHARS = 4000
_IMAGE_ONLY_BODY = (
    "(이 공지의 본문은 이미지로 작성되어 텍스트를 추출할 수 없습니다. "
    "첨부파일 목록과 제목을 참고하세요.)"
)
```

`register` 앞에 다음 함수들을 추가한다.

```python
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
```

`register`를 수정한다.

```python
def register(mcp) -> None:
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    mcp.tool(annotations=read_only)(search_notices)
    mcp.tool(annotations=read_only)(get_notice)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_notices.py -v`
Expected: PASS (11 passed)

- [ ] **Step 6: 목록 → 상세 연결이 실제로 되는지 수동 확인**

```bash
.venv/Scripts/python -c "
from tools.notices import search_notices, get_notice
first = search_notices('academic', limit=1).notices[0]
print('제목:', first.title)
d = get_notice(first.notice_id)
print('부서:', d.department, '| 날짜:', d.posted_on, '| 첨부:', len(d.attachments))
print('본문 앞부분:', d.body[:100])
"
```

Expected: 목록의 첫 글 제목과 상세의 메타데이터가 일치하고, 본문 또는 이미지 안내 문구가 한글로 정상 출력된다.

- [ ] **Step 7: 커밋**

```bash
git add tools/notices.py tests/test_notices.py tests/fixtures/notice_detail.html
git commit -m "feat: 공지 상세 조회 툴 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: MCP 서버 통합 + 클라이언트 등록 + README

**Files:**
- Create: `server.py`, `README.md`
- Test: 수동 — 실제 MCP 클라이언트에 붙여 확인

**Interfaces:**
- Consumes: `tools.library_seats.register`, `tools.notices.register`
- Produces: 실행 가능한 MCP 서버

- [ ] **Step 1: `server.py` 작성**

```python
"""명지전문대 MCP 서버 진입점.

stdio transport에서 stdout은 JSON-RPC 채널이다. 어떤 모듈에서도
print()를 쓰면 안 되며, 로그는 반드시 stderr로 나가야 한다.
"""

import logging
import sys

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Windows 콘솔 기본 인코딩(cp949)에서 한글 응답 시 UnicodeEncodeError가 난다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from mcp.server import MCPServer  # noqa: E402

from tools import library_seats, notices  # noqa: E402

mcp = MCPServer("mjc")
library_seats.register(mcp)
notices.register(mcp)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: 서버가 기동되고 툴 3개가 등록되는지 확인**

```bash
.venv/Scripts/python -c "
import server
print(sorted(t.name for t in server.mcp._tool_manager.list_tools()))
"
```

Expected: `['get_library_seats', 'get_notice', 'search_notices']`

내부 속성명이 SDK 버전에 따라 다를 수 있다. `AttributeError`가 나면 다음으로 확인한다.

```bash
.venv/Scripts/python -c "import server; print([a for a in dir(server.mcp) if 'tool' in a.lower()])"
```

- [ ] **Step 3: stdout이 오염되지 않았는지 확인**

서버를 stdio 모드로 띄우면 stdout에는 JSON-RPC만 나와야 한다.

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' | .venv/Scripts/python server.py 2>/dev/null | head -c 200
```

Expected: `{"jsonrpc":"2.0"...` 로 시작하는 JSON만 보인다. 다른 텍스트가 섞이면 어딘가에 `print()`가 있는 것이므로 찾아서 제거한다.

- [ ] **Step 4: 코드 전체에 `print()`가 없는지 확인**

Run: `grep -rn "print(" --include="*.py" server.py common/ tools/`
Expected: 출력 없음 (테스트 파일은 무관하므로 검사 대상에서 제외)

- [ ] **Step 5: MCP 클라이언트에 등록해 실제로 확인**

프로젝트 루트에 `.mcp.json`을 만든다. 경로는 각자 환경에 맞게 절대 경로로 적는다.

```json
{
  "mcpServers": {
    "mjc": {
      "type": "stdio",
      "command": "C:\\projects\\hachathon_mjc_mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\projects\\hachathon_mjc_mcp\\server.py"]
    }
  }
}
```

Claude Code를 재시작한 뒤 `/mcp`로 `mjc` 서버가 연결되었는지 확인하고, 다음 질문을 실제로 던져본다.

1. "지금 도서관 어디가 제일 한산해?"
2. "이번 주 학사공지 알려줘"
3. "그중 등록금 관련 공지 자세히 보여줘"

Expected: 세 질문 모두 실제 데이터로 답변된다. 특히 3번은 AI가 `search_notices` → `get_notice`를 연달아 호출해야 한다.

- [ ] **Step 6: `README.md` 작성**

심사위원은 스크롤 첫 화면에서 판단한다. 아래 구조를 지킨다.

```markdown
# 명지전문대 MCP 서버

AI 에이전트가 명지전문대 학교 데이터를 직접 조회할 수 있게 해주는 MCP 서버입니다.
챗봇을 새로 만드는 대신, 어떤 AI 클라이언트에나 붙일 수 있는 **어댑터**를 만들었습니다.

## 30초 설치

```bash
git clone https://github.com/4thIS/hachathon_mjc_mcp.git
cd hachathon_mjc_mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

AI 클라이언트 설정에 아래를 추가합니다 (경로는 clone한 위치에 맞게 수정).

```json
{
  "mcpServers": {
    "mjc": {
      "type": "stdio",
      "command": "C:\\경로\\hachathon_mjc_mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\경로\\hachathon_mjc_mcp\\server.py"]
    }
  }
}
```

## 이렇게 물어보세요

- "지금 도서관 어디가 제일 한산해?"
- "이번 주 학사공지 알려줘"
- "장학 공지 중에 마감 임박한 거 있어?"

## 제공하는 툴

| 툴 | 하는 일 | 데이터 출처 |
|---|---|---|
| get_library_seats | 열람실 3곳 실시간 좌석 현황 | 도서관 좌석 시스템 |
| search_notices | 학사·장학·채용·일반 공지 목록 | www.mjc.ac.kr 게시판 |
| get_notice | 공지 본문과 첨부파일 목록 | www.mjc.ac.kr 게시판 |

## 데이터 수집 원칙

- 로그인 없이 볼 수 있는 공개 페이지만 조회합니다.
- robots.txt를 확인했으며, 전체 허용(`Allow: /`)입니다. (2026-08-06 확인)
- 동일 호스트에 최소 1초 간격을 두고 요청합니다.
- 식별 가능한 User-Agent를 사용합니다.
- 조회 결과는 사용자의 AI 클라이언트에만 전달되며, 외부로 전송하거나 저장·재배포하지 않습니다.
- 실제 서비스로 운영하려면 학사팀 협의가 전제입니다.

## 한계 (정직하게)

- 게시판 페이지네이션을 지원하지 않아 첫 페이지 범위 내에서만 조회됩니다.
- 본문이 이미지로 작성된 공지는 텍스트를 추출할 수 없어 첨부파일 목록으로 안내합니다.
- 학교 사이트 구조가 바뀌면 파싱이 깨집니다. 파싱 계층을 분리해 한 파일만 고치면 되도록 설계했습니다.
- 로그인이 필요한 기능(수강신청 등)은 이번 범위에 포함하지 않았습니다. 설계 원칙은 docs/design.md 참고.

## 팀

(팀원 이름과 역할)
```

- [ ] **Step 7: 전체 테스트 최종 확인**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 전부 PASS (총 23개 — common 8, library_seats 4, notices 11)

- [ ] **Step 8: 커밋**

```bash
git add server.py README.md .mcp.json
git commit -m "feat: MCP 서버 진입점과 README 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 데모 전 체크리스트

- [ ] 시연장 네트워크에서 `get_library_seats`가 실제로 되는지 확인한다. 도서관 API는 http에 비표준 포트(8090)라 게스트 Wi-Fi에서 막힐 수 있다. **막히면 폰 테더링으로 전환한다.**
- [ ] 성공한 데모를 미리 화면 녹화해둔다.
- [ ] 데모 직전 각 툴을 한 번씩 호출해 `.cache/`를 채워둔다. 시연 중 서버가 죽어도 폴백이 답을 낸다.
- [ ] 조합 질문(`search_notices` → `get_notice`)을 반드시 시연에 넣는다. 여러 툴을 엮는 장면이 이 프로젝트의 핵심이다.
- [ ] 팀장이 `tier1/merged`를 `main`에 머지하고, `main`에서 전체 테스트가 통과하는지 마지막으로 확인한다.
- [ ] 개인 브랜치 커밋이 3명 각자 이름으로 남아 있는지 확인한다. 심사에서 기여도 질문이 나올 수 있다.
