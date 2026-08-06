# 명지전문대 MCP 서버 Tier 2 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Task 1 실제 코딩 착수 직전, 반드시 `/security-review`를 먼저 호출한다** (전역 지침 B9 — 인증·인증정보·세션·토큰을 다루는 작업). `docs/design.md` 8장에도 명시되어 있다.

**Goal:** 로그인이 필요한 sugang(수강신청) 시스템에서 개설 강좌를 검색할 수 있게 한다. 비밀번호를 저장하지 않고, 캐시된 세션으로 먼저 시도한 뒤 실패 시에만 사용자에게 재로그인을 안내하는 "선시도 후재로그인" 패턴을 따른다.

**Architecture:** 로그인 헬퍼(`auth/login_helper.py`)는 사용자가 별도 터미널에서 직접 실행하는 독립 CLI로, 세션 쿠키만 저장소 바깥(`%LOCALAPPDATA%\mjc-mcp\`)에 저장한다. `common/session.py`가 세션 파일을 읽고 쓰는 공용 레이어이며, `common/http.py`에 인증 요청용 함수를 추가해 재사용한다. 그 위에 `list_departments`(학과 목록)와 `search_courses`(강좌 검색) 두 툴을 "목록 → 상세" 관용구로 조합한다.

**Tech Stack:** Tier 1과 동일 — Python, 공식 `mcp` SDK v2, `httpx`, `pydantic`, `pytest`. Tier 2는 새 의존성을 추가하지 않는다.

설계 근거는 `docs/design.md` 8장 참고. 학사공지 등 Tier 1 툴의 기존 코드(`common/http.py`, `common/parse.py`, `common/cache.py`, `common/errors.py`, `common/models.py`, `tools/library_seats.py`, `tools/notices.py`)는 이미 `main`에 있으며 이 계획에서 건드리지 않는다(단, `common/http.py`에 함수를 **추가**는 한다 — 아래 Task 1 참고).

## Global Constraints

- **비밀번호를 어떤 파일에도 저장하지 않는다.** 로그인 헬퍼는 매번 입력받아 1회성으로만 쓴다.
- **로그인 헬퍼는 사용자가 별도 터미널에서 직접 실행한다.** Claude/에이전트 세션 안에서 실행하지 않는다.
- **자동 재로그인을 하지 않는다.** 세션 실패 감지 시 "헬퍼를 실행하세요" 에러만 반환한다. 시간 기반 만료 추적도 하지 않는다.
- **세션 파일은 저장소 바깥에 둔다.** Windows는 `%LOCALAPPDATA%\mjc-mcp\`, 그 외는 `~/.cache/mjc-mcp/`. `.gitignore`에 의존하지 않는다(이미 추적된 파일엔 효력 없음).
- **에러 메시지·로그·테스트 fixture에 쿠키 값·응답 헤더·학번·비밀번호·JSON 원문을 담지 않는다.** 예외 타입명과 고정 문구만 쓴다.
- **로그인 POST는 재시도하지 않는다.** 계정 잠금 정책 미확인 상태이므로.
- **`print()` 절대 금지** (`common/`, `tools/`, `auth/`, `server.py`). stdio에서 stdout은 JSON-RPC 채널이다. 로깅은 stderr에만.
- 모든 인증 요청에 `httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)`, `follow_redirects=False`, 기존 User-Agent(`common.http.USER_AGENT`)를 그대로 쓴다.
- 동일 호스트 연속 요청 최소 1초 간격 (`common.http`의 기존 쓰로틀링 재사용).
- 커밋 메시지는 한 줄로 짧게, 빈 줄 후 `Co-Authored-By: Claude <noreply@anthropic.com>`.
- 커밋은 각자 개인 브랜치(`tier2/<이름>`)에. `main`이나 `tier2/merged`에 직접 커밋하지 않는다 — **단 Task 1(로그인 기반)은 예외로 `tier2/merged`에 직접 커밋한다** (Tier 1의 공통 레이어와 동일한 선례, `docs/design.md` 8.2).
- 머지는 로컬 `git merge`가 아니라 `gh pr create --base tier2/merged --head tier2/<이름>`로 PR을 올린다. `--base`를 반드시 명시한다.

## 검증된 사실 (실제 조사 결과)

**로그인 요청** (2026-08-06, 정적 JS 소스 분석으로 확인 — 실제 제출은 안 함)
```
POST https://sugang.mjc.ac.kr/loginChk?fake=<ms timestamp>
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest

txtUserID=<학번>&txtPwd=<비밀번호>
```
응답 JSON: `{"code": "200|201", "msg": "...", "token": "...", "uri": "..."}`. `code`가 `"200"` 또는 `"201"`이면 성공(201은 비밀번호 만료 임박 등 안내 있음). 그 외는 실패, `msg`가 실패 사유. `token` 필드는 프론트에서 실사용 여부 불확실 — 무시한다. **세션 확립은 이 응답에 딸려오는 `Set-Cookie`로 이루어지는 것으로 추정되나, 실제 로그인 성공 시점에 응답 헤더로 확정된 적은 없다.** Task 1의 첫 스텝에서 확정한다.

**강좌 검색** (2026-08-07, 팀장이 본인 계정으로 실제 로그인 후 Playwright로 실측 — 아래는 전부 [확인])
```
POST https://sugang.mjc.ac.kr/core/d/lectList?fake=<ms timestamp>
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest

pCourseCd=&pSugangGbn=S&pSelMetaA=&pSelMetaB=&pSelMetaUnionA=&pSelMetaUnionB=&pSelMetaUnionC=&pParams=&pComboSugangCd=<강좌구분코드>&pComboGrade=<학년>&pComboClsMajCd=<학과코드>&pSearchNm=<검색어>
```
쿠키는 브라우저가 same-origin으로 자동 첨부했다(별도 `Referer` 헤더 없이도 200 성공). `fake=` 파라미터 없으면 500(status 999) 확정 필수(Tier 1 때부터 알려진 사실).

**학과코드(`pComboClsMajCd`) — 이전 계획의 예시가 틀렸다.** `1201001`은 정보통신공학과가 아니라 **"교양"**이었다(로그인 시 기본 선택되어 있던 값을 캡처해서 생긴 착오). 실측으로 전체 36개를 확보했다:

```
1200205=AI게임소프트웨어학과   1200509=AI미디어디자인학과      1200301=경영학과
1200305=공공행정서비스과       1201001=교양                    1200102=기계공학과
1200207=드론정보공학과         1200406=문예창작과              1201402=보건의료정보과
1200303=부동산경영과           1200505=뷰티매니지먼트과메이크업·네일전공
1200508=뷰티매니지먼트과방송스타일디렉터전공  1200506=뷰티매니지먼트과스킨케어메디컬코스메틱전공
1200507=뷰티매니지먼트과헤어디자인전공        1200304=사회복지과   1200603=사회체육과
1200101=산업경영공학과         1200501=산업디자인학과          1200302=세무회계과
1200602=실용음악과             1200604=연극영상학과            1200404=유아교육학과
1200403=일본어과               1200201=전기공학과              1200202=전자공학과
1200204=정보통신공학과         1200402=중국어비즈니스과        1200306=지적공간정보학과
1200405=청소년교육상담과       1200503=커뮤니케이션디자인과    1200203=컴퓨터공학과
1200206=컴퓨터보안공학과       1200103=토목공학과              1201301=통합전공
1200502=패션·리빙디자인과      1200409=항공서비스과
```

**강좌구분코드(`pComboSugangCd`)** — 확정: `10=교양, 30=전공, 60=원격강좌, 61=메타모포시스`.

**학년(`pComboGrade`)** — 확정: `1`~`4`, 단순 정수 문자열.

**응답 JSON 실제 필드명 — 이전 계획의 추정(과목코드/과목명/교수명 등 한글 키)은 전부 틀렸다.** 실제 `rows` 배열 원소:

| 실제 키 | 의미 | 예시 |
|---|---|---|
| `subjectCd` | 과목코드 | `"J04661"` |
| `subjectNmKor` | 과목명 | `"캡스톤디자인"` |
| `nm` | 담당교수명 | `"정필성"` |
| `bunban` | 분반 | `"101"` |
| `isuCdNm` | 이수구분명 | `"전공과정"` |
| `credit` | 학점 | `"4"` (문자열) |
| `grade` | 학년 | `"3"` (문자열) |
| `time` | 강의시간+강의실. `<br>`로 여러 교시 구분, 각 교시에 `( 강의실 )` 포함 | `"수 09:00 - 09:50 ( 공803 ) <br> 수 10:00 - 10:50 ( 공803 )"` |
| `limitNum` | 정원 | `"40"` |
| `clsMajCd` | 학과코드 (요청에 넣은 값 그대로 돌아옴) | `"1200204"` |
| `memberNo` | 교수 내부 사번(6자리) — **개인정보, fixture에 저장 금지·마스킹 필수** | `"213434"` |

**`inManNum`/`outManNum`/`sugangNum`은 실시간 신청 인원이 아니다.** 화면 문구("신청인원은 실시간으로 조회되지 않습니다")와 일치 — `sugangNum` 값 자체가 문자열 `"조회하세요"`로 온다. 실시간 신청 인원은 과목별로 별도 새로고침 호출이 필요한 것으로 보이며, 이번 Tier 2 범위에서는 다루지 않는다(`search_courses`는 정원까지만 제공).

**학과/강좌구분 드롭다운은 별도 GET 엔드포인트가 없다.** 로그인 후 화면 안에서 JS 라우팅(SPA 방식)으로 "전체조회" 메뉴를 눌러야 나타나며, 페이지 소스나 별도 URL로 조회되지 않는다. `curl`로 루트에 접근하면 "한 개의 브라우저탭만 사용가능" 경고만 뜬다(세션/탭 상태를 실제 브라우저처럼 유지해야 통과된다).

**→ 이 사실이 Task 2의 설계를 바꾼다.** 학과 목록은 요청마다 조회할 대상이 아니라 위에 있는 것처럼 **거의 안 바뀌는 정적 데이터**이므로, 매번 인증된 스크래핑을 하는 대신 **하드코딩된 매핑을 코드에 직접 넣는다.** 부수 이득으로 `list_departments`는 로그인이 전혀 필요 없는 툴이 된다 — Tier 2에서 인증이 필요한 건 `search_courses`뿐이다.

## File Structure

| 파일 | 책임 | 담당 |
|---|---|---|
| `common/http.py` (수정) | `fetch_authenticated()` 함수 추가 — 세션 쿠키를 실어 보내고 status/redirect를 그대로 노출 | Task 1 |
| `common/session.py` (신규) | 세션 파일 read/write, `require_session()`, `SessionRequiredError`, `require_active_session()` | Task 1 |
| `auth/login_helper.py` (신규) | 독립 CLI. 사용자가 직접 실행 | Task 1 |
| `tools/departments.py` (신규) | 학과 코드 정적 매핑 + `list_departments()` + `register(mcp)`. **로그인 불필요** | Task 2 |
| `tools/course_search.py` (신규) | `search_courses()` + `register(mcp)`. 로그인 필요 | Task 3 |
| `common/models.py` (수정) | `Department`, `DepartmentList`, `CourseSummary`, `CourseList` 모델 추가 | Task 2, 3 (각자 자기 모델만 추가 — 충돌 시 먼저 머지된 쪽 기준으로 rebase) |
| `server.py` (수정) | `departments.register(mcp)`, `course_search.register(mcp)` 호출 추가 | Task 4(통합, 팀장) |

**병렬 작업 안내:** Task 1(로그인 기반)이 끝나 `tier2/merged`에 푸시되면, Task 2와 Task 3은 서로 다른 파일이라 병렬로 진행한다. **Task 2는 사실 Task 1을 기다릴 필요도 없다** — 정적 데이터라 로그인/세션 인프라에 의존하지 않는다. 팀원이 먼저 시작해도 된다. 둘 다 `common/models.py`를 수정하므로 — 각자 자기 모델 클래스만 파일 끝에 추가하고, 먼저 PR이 머지된 쪽을 기준으로 나중 PR이 `git fetch && git rebase origin/tier2/merged`로 반영한다. Task 4는 둘 다 머지된 뒤 팀장이 진행한다.

---

### Task 1: 로그인 헬퍼 + 세션 인프라

**담당:** 팀장. `tier2/merged`에 직접 커밋한다(개인 브랜치 없이 — Tier 1 공통 레이어와 동일한 예외).

**착수 전 필수:** `/security-review`를 먼저 호출한다.

**Files:**
- Modify: `common/http.py` — `fetch_authenticated()` 추가
- Create: `common/session.py`
- Create: `auth/login_helper.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `common.http.TIMEOUT`, `common.http.USER_AGENT`, `common.errors.ToolError`
- Produces:
  - `common.http.fetch_authenticated(url: str, *, cookies: dict[str, str], method: str = "GET", data: dict[str, str] | None = None, params: dict[str, str] | None = None) -> httpx.Response`
  - `common.session.save_session(system: str, cookies: dict[str, str]) -> None`
  - `common.session.load_session(system: str) -> dict[str, str] | None`
  - `common.session.require_session(system: str) -> dict[str, str]` (파일 없으면 `SessionRequiredError`)
  - `common.session.require_active_session(response: httpx.Response, system: str) -> None` (3xx 리다이렉트면 `SessionRequiredError`)
  - `common.session.SessionRequiredError(ToolError)`

- [ ] **Step 1: `common/http.py`에 `fetch_authenticated` 추가 — 실패하는 테스트 먼저**

`tests/test_session.py` 새로 만들면서 이 함수도 같이 테스트한다(session.py와 같은 파일에 몰아서 — 둘 다 "인증 인프라"라는 하나의 관심사).

```python
import httpx
import pytest

from common.http import fetch_authenticated


def test_fetch_authenticated_sends_cookies_and_returns_full_response(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["cookie_header"] = request.headers.get("cookie", "")
        captured["method"] = request.method
        return httpx.Response(302, headers={"location": "/logOut"})

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.Client(*args, **kwargs)

    import common.http as http_mod
    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(http_mod, "httpx", httpx)
    monkeypatch.setattr(httpx, "Client", fake_client)

    resp = fetch_authenticated(
        "https://sugang.mjc.ac.kr/core/d/lectList",
        cookies={"JSESSIONID": "abc123"},
    )
    assert "JSESSIONID=abc123" in captured["cookie_header"]
    assert captured["method"] == "GET"
    assert resp.status_code == 302
    assert resp.is_redirect


def test_fetch_authenticated_posts_form_data(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        captured["method"] = request.method
        return httpx.Response(200, json={"rows": []})

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.Client(*args, **kwargs)

    import common.http as http_mod
    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(httpx, "Client", fake_client)

    resp = fetch_authenticated(
        "https://sugang.mjc.ac.kr/core/d/lectList",
        cookies={"JSESSIONID": "abc123"},
        method="POST",
        data={"pComboClsMajCd": "1201001"},
    )
    assert captured["method"] == "POST"
    assert "pComboClsMajCd=1201001" in captured["body"]
    assert resp.status_code == 200
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_authenticated'`

- [ ] **Step 3: `common/http.py`에 함수 추가**

기존 `fetch()` 바로 아래에 추가한다. 기존 `fetch()`, `_get_once()`, `TIMEOUT`, `USER_AGENT`, `MIN_INTERVAL_SEC`, `_last_request_at`는 **건드리지 않는다.**

**재시도 범위에 주의한다.** "로그인 POST는 재시도하지 않는다"(Global Constraints)는 자격증명을 실제로 제출하는 `auth/login_helper.py`의 로그인 요청에만 적용된다. `fetch_authenticated`는 이미 발급된 세션으로 조회만 하는 함수라 계정 잠금 리스크가 없으므로, `fetch()`와 동일하게 네트워크 오류·4xx/5xx에 대해 1회 재시도한다. 3xx는 `raise_for_status()`가 예외로 취급하지 않으므로 재시도 없이 그대로 반환되고, 호출자가 `require_active_session()`으로 판단한다.

```python
def _request_once(
    url: str,
    *,
    cookies: dict[str, str],
    method: str,
    data: dict[str, str] | None,
    params: dict[str, str] | None,
) -> httpx.Response:
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        cookies=cookies,
    ) as client:
        response = client.request(method, url, params=params, data=data)
        if response.status_code >= 400:
            response.raise_for_status()
    return response


def fetch_authenticated(
    url: str,
    *,
    cookies: dict[str, str],
    method: str = "GET",
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """세션 쿠키가 필요한 요청.

    fetch()와 달리 bytes가 아니라 httpx.Response 전체를 반환한다. 3xx
    리다이렉트는 예외로 취급하지 않고 그대로 반환하므로, 호출자가
    require_active_session()으로 세션 만료 여부를 판단해야 한다.
    네트워크 오류나 4xx/5xx는 fetch()와 동일하게 1회 재시도한다.
    """
    host = httpx.URL(url).host
    elapsed = time.monotonic() - _last_request_at.get(host, 0.0)
    if elapsed < MIN_INTERVAL_SEC:
        time.sleep(MIN_INTERVAL_SEC - elapsed)

    try:
        try:
            return _request_once(url, cookies=cookies, method=method, data=data, params=params)
        except httpx.HTTPError:
            time.sleep(MIN_INTERVAL_SEC)
            return _request_once(url, cookies=cookies, method=method, data=data, params=params)
    except httpx.HTTPError as exc:
        raise FetchError(type(exc).__name__) from None
    finally:
        _last_request_at[host] = time.monotonic()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: `common/session.py` 작성 — 세션 read/write 실패하는 테스트 먼저**

`tests/test_session.py`에 이어서 추가:

```python
import json

from common.session import (
    SessionRequiredError,
    load_session,
    require_active_session,
    require_session,
    save_session,
)


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    save_session("sugang", {"JSESSIONID": "abc123"})
    assert load_session("sugang") == {"JSESSIONID": "abc123"}


def test_load_returns_none_when_missing(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    assert load_session("sugang") is None


def test_load_returns_none_when_corrupted(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    (tmp_path / "session_sugang.json").write_text("not json", encoding="utf-8")
    assert load_session("sugang") is None


def test_require_session_raises_when_missing(tmp_path, monkeypatch):
    import common.session as session_mod

    monkeypatch.setattr(session_mod, "_session_dir", lambda: tmp_path)
    with pytest.raises(SessionRequiredError):
        require_session("sugang")


def test_session_required_error_message_has_no_cookie_value():
    err = SessionRequiredError("sugang")
    assert "abc123" not in str(err)
    assert "login_helper" in str(err)


def test_require_active_session_raises_on_redirect():
    resp = httpx.Response(302, headers={"location": "/logOut"}, request=httpx.Request("GET", "https://x"))
    with pytest.raises(SessionRequiredError):
        require_active_session(resp, "sugang")


def test_require_active_session_passes_on_200():
    resp = httpx.Response(200, request=httpx.Request("GET", "https://x"))
    require_active_session(resp, "sugang")  # 예외 없이 통과해야 함
```

- [ ] **Step 6: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.session'`

- [ ] **Step 7: `common/session.py` 구현**

```python
"""세션 쿠키 로컬 캐시.

auth/login_helper.py가 쓰고, 인증이 필요한 tools/의 툴이 읽는다. 세션 파일은
저장소 바깥(OS 사용자 데이터 경로)에 둔다 — .gitignore만으로는 부족하다.
비밀번호는 이 파일에 절대 들어가지 않는다. 저장하는 것은 세션 쿠키뿐이다.
"""

import json
import os
import sys
from pathlib import Path

import httpx

from common.errors import ToolError


def _session_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    path = base / "mjc-mcp"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SessionRequiredError(ToolError):
    def __init__(self, system: str) -> None:
        super().__init__(
            f"{system} 세션이 없거나 만료되었습니다. "
            f"별도 터미널에서 `python auth/login_helper.py {system}`를 실행해 "
            "로그인한 뒤 다시 시도해주세요."
        )


def save_session(system: str, cookies: dict[str, str]) -> None:
    path = _session_dir() / f"session_{system}.json"
    path.write_text(
        json.dumps({"cookies": cookies}, ensure_ascii=False), encoding="utf-8"
    )


def load_session(system: str) -> dict[str, str] | None:
    path = _session_dir() / f"session_{system}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    cookies = data.get("cookies") if isinstance(data, dict) else None
    return cookies if isinstance(cookies, dict) else None


def require_session(system: str) -> dict[str, str]:
    cookies = load_session(system)
    if not cookies:
        raise SessionRequiredError(system)
    return cookies


def require_active_session(response: httpx.Response, system: str) -> None:
    """3xx 응답이면 세션이 끊긴 것으로 간주한다.

    sugang은 follow_redirects=False 상태에서 세션이 무효화되면 다른 경로로
    리다이렉트하는 것으로 보인다(실제 무효 세션 응답은 Task 2/3에서 실측 확인).
    본문 기반의 추가 판별이 필요하면 그 툴 파일 안에서 로컬로 확장한다.
    """
    if response.is_redirect:
        raise SessionRequiredError(system)
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: PASS (9 passed)

- [ ] **Step 9: `auth/login_helper.py` 작성 (테스트 없음 — 자격증명을 다루는 대화형 CLI라 자동 테스트 대상이 아니다)**

```python
"""sugang 로그인 헬퍼 — 독립 실행 CLI.

**이 스크립트는 사용자가 별도 터미널에서 직접 실행한다.** Claude/에이전트
세션 안에서 실행하지 않는다 — 입출력이 대화 기록에 남기 때문이다.

비밀번호를 디스크에 저장하지 않는다. 매번 입력받아 로그인 요청에만
1회성으로 쓰고, 저장하는 것은 로그인 성공 후 받은 세션 쿠키뿐이다.
교내 SSO가 90일마다 비밀번호를 강제로 재설정시키므로, 저장해봐야 어차피
주기적으로 무효가 된다.

사용법:
    python auth/login_helper.py sugang
"""

import getpass
import sys
import time

import httpx

from common.http import TIMEOUT, USER_AGENT
from common.session import save_session

LOGIN_URL = "https://sugang.mjc.ac.kr/loginChk"


def _login_sugang() -> dict[str, str] | None:
    student_id = input("학번: ").strip()
    password = getpass.getpass("비밀번호: ")

    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=False,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    ) as client:
        try:
            response = client.post(
                LOGIN_URL,
                params={"fake": str(int(time.time() * 1000))},
                data={"txtUserID": student_id, "txtPwd": password},
            )
        except httpx.HTTPError as exc:
            print(f"로그인 요청 실패: {type(exc).__name__}", file=sys.stderr)
            return None

        # 비밀번호는 여기서 스코프를 벗어나며 더 이상 참조되지 않는다.
        del password

        try:
            body = response.json()
        except ValueError:
            print("로그인 응답을 해석하지 못했습니다.", file=sys.stderr)
            return None

        code = body.get("code")
        if code not in ("200", "201"):
            print(f"로그인 실패: {body.get('msg', '(사유 불명)')}", file=sys.stderr)
            return None

        if code == "201":
            print(f"안내: {body.get('msg', '')}")

        cookies = dict(client.cookies)
        if not cookies:
            print(
                "경고: 로그인은 성공했으나 세션 쿠키를 받지 못했습니다. "
                "실제 Set-Cookie 구조를 재확인해야 합니다.",
                file=sys.stderr,
            )
            return None
        return cookies


SYSTEMS = {"sugang": _login_sugang}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in SYSTEMS:
        print(f"사용법: python auth/login_helper.py {{{'|'.join(SYSTEMS)}}}", file=sys.stderr)
        return 1

    system = sys.argv[1]
    cookies = SYSTEMS[system]()
    if cookies is None:
        return 1

    save_session(system, cookies)
    print(f"로그인 성공. 세션을 저장했습니다 ({system}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10: 전체 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 기존 45개 + 신규 9개 = PASS (54 passed)

- [ ] **Step 11: `print()` 검사**

Run: `grep -rn "print(" --include="*.py" common/ tools/ server.py`
Expected: 매치 없음. (`auth/login_helper.py`는 이 검사에서 **제외**한다 — 독립 CLI로, 사용자가 직접 실행하는 터미널 프로그램이라 표준입출력을 쓰는 게 정상이며 MCP stdio 채널과 무관하다.)

- [ ] **Step 12: 실제 로그인으로 세션 확립 방식 확정 (사용자가 직접 실행)**

**이 스텝은 Claude가 실행하지 않는다.** 팀장이 별도 터미널에서 직접:

```bash
.venv/Scripts/python auth/login_helper.py sugang
```

실행 후 `%LOCALAPPDATA%\mjc-mcp\session_sugang.json`이 생성되고 `cookies`에 실제 키(예: `JSESSIONID`)가 들어 있는지 확인한다. 없다면(Step 9의 경고가 뜬다면) `login_helper.py`의 쿠키 캡처 방식을 다시 조사해야 한다 — 예를 들어 로그인 성공 후 `uri` 필드가 가리키는 URL을 한 번 더 GET해야 세션이 실제로 확립되는 구조일 수 있다.

- [ ] **Step 13: 커밋**

```bash
git add common/http.py common/session.py auth/login_helper.py tests/test_session.py
git commit -m "feat: 로그인 헬퍼와 세션 인프라 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin tier2/merged
```

---

### Task 2: 학과 목록 조회 (list_departments)

**담당:** 팀원 A. `tier2/<이름>` 브랜치에서 진행 후 `tier2/merged`로 PR. **Task 1을 기다릴 필요 없이 바로 시작 가능** — 로그인/세션과 무관한 정적 데이터다.

학과 드롭다운은 로그인 후 화면 안에서 JS 라우팅으로만 나타나고 별도 GET 엔드포인트가 없다는 게 실측으로 확인됐다("검증된 사실" 참고). 학과 코드는 학기마다 거의 바뀌지 않는 정적 데이터이므로, 매번 인증된 스크래핑을 하는 대신 **하드코딩된 매핑을 코드에 직접 넣는다.** 덕분에 이 툴은 로그인이 전혀 필요 없다.

**Files:**
- Create: `tools/departments.py`
- Modify: `common/models.py` — `Department`, `DepartmentList` 추가
- Test: `tests/test_departments.py`

**Interfaces:**
- Consumes: 없음 (정적 데이터, 다른 모듈에 의존하지 않는다)
- Produces:
  - `common.models.Department(code: str, name: str)`
  - `common.models.DepartmentList(departments: list[Department])`
  - `tools.departments.DEPARTMENTS: dict[str, str]` (code → name, `search_courses`가 `department_code` 유효성 검사에 재사용할 수 있음)
  - `tools.departments.list_departments() -> DepartmentList`
  - `tools.departments.register(mcp) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_departments.py`:

```python
import pytest

from tools.departments import DEPARTMENTS, list_departments


def test_known_department_present():
    assert DEPARTMENTS.get("1200204") == "정보통신공학과"


def test_general_education_present():
    assert DEPARTMENTS.get("1201001") == "교양"


def test_at_least_thirty_departments():
    assert len(DEPARTMENTS) >= 30


def test_no_duplicate_codes():
    # dict 자체가 키 중복을 허용하지 않으므로, 원본 리스트 정의 단계에서
    # 중복이 있었다면 조용히 마지막 값으로 덮어써졌을 수 있다. 이를 잡아낸다.
    assert len(DEPARTMENTS) == len(set(DEPARTMENTS))


def test_list_departments_returns_all():
    result = list_departments()
    assert len(result.departments) == len(DEPARTMENTS)
    names = {d.name for d in result.departments}
    assert "정보통신공학과" in names


def test_list_departments_no_login_required():
    """이 함수를 호출하는 데 세션/쿠키 인자가 전혀 없어야 한다."""
    import inspect

    sig = inspect.signature(list_departments)
    assert len(sig.parameters) == 0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_departments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.departments'`

- [ ] **Step 3: `common/models.py`에 모델 추가**

파일 끝에 추가한다 (기존 클래스는 건드리지 않는다):

```python
class Department(BaseModel):
    code: str = Field(description="search_courses의 department_code에 그대로 넘길 학과 코드")
    name: str = Field(description="학과명")


class DepartmentList(BaseModel):
    departments: list[Department] = Field(description="sugang에 등록된 전체 학과 목록")
```

- [ ] **Step 4: `tools/departments.py` 구현**

2026-08-07 실측으로 확인된 전체 36개 매핑을 그대로 쓴다(위 "검증된 사실" 표와 동일 — 아래 코드가 원본이다).

```python
"""sugang 학과 목록.

학과 코드는 학기마다 거의 바뀌지 않는 정적 데이터라, 매번 스크래핑하는 대신
하드코딩한다(2026-08-07 실제 로그인 세션으로 학과 드롭다운을 직접 읽어 확보).
이 덕분에 이 툴은 로그인이 필요 없다 — search_courses만 인증이 필요하다.

매 학기 개편이 있으면 이 표를 갱신해야 한다는 뜻이기도 하다.
"""

from mcp.types import ToolAnnotations

from common.models import Department, DepartmentList

DEPARTMENTS: dict[str, str] = {
    "1200205": "AI게임소프트웨어학과",
    "1200509": "AI미디어디자인학과",
    "1200301": "경영학과",
    "1200305": "공공행정서비스과",
    "1201001": "교양",
    "1200102": "기계공학과",
    "1200207": "드론정보공학과",
    "1200406": "문예창작과",
    "1201402": "보건의료정보과",
    "1200303": "부동산경영과",
    "1200505": "뷰티매니지먼트과메이크업·네일전공",
    "1200508": "뷰티매니지먼트과방송스타일디렉터전공",
    "1200506": "뷰티매니지먼트과스킨케어메디컬코스메틱전공",
    "1200507": "뷰티매니지먼트과헤어디자인전공",
    "1200304": "사회복지과",
    "1200603": "사회체육과",
    "1200101": "산업경영공학과",
    "1200501": "산업디자인학과",
    "1200302": "세무회계과",
    "1200602": "실용음악과",
    "1200604": "연극영상학과",
    "1200404": "유아교육학과",
    "1200403": "일본어과",
    "1200201": "전기공학과",
    "1200202": "전자공학과",
    "1200204": "정보통신공학과",
    "1200402": "중국어비즈니스과",
    "1200306": "지적공간정보학과",
    "1200405": "청소년교육상담과",
    "1200503": "커뮤니케이션디자인과",
    "1200203": "컴퓨터공학과",
    "1200206": "컴퓨터보안공학과",
    "1200103": "토목공학과",
    "1201301": "통합전공",
    "1200502": "패션·리빙디자인과",
    "1200409": "항공서비스과",
}


def list_departments() -> DepartmentList:
    """sugang에 등록된 학과 목록을 조회한다. 로그인이 필요 없다.

    반환된 각 항목의 code를 search_courses의 department_code에 그대로 넘긴다.
    """
    return DepartmentList(
        departments=[Department(code=c, name=n) for c, n in DEPARTMENTS.items()]
    )


def register(mcp) -> None:
    mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True)
    )(list_departments)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_departments.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 실제 호출로 수동 확인**

```bash
.venv/Scripts/python -c "
from tools.departments import list_departments
r = list_departments()
print(len(r.departments), '개 학과')
print([d for d in r.departments if d.name == '정보통신공학과'])
"
```

Expected: `36개 학과`, 정보통신공학과가 `code='1200204'`로 나온다.

- [ ] **Step 7: 커밋 및 PR**

```bash
git add tools/departments.py common/models.py tests/test_departments.py
git commit -m "feat: 학과 목록 조회 툴 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin tier2/<이름>
gh pr create --base tier2/merged --head tier2/<이름> --title "feat: 학과 목록 조회 툴 추가" --body "Task 2 구현. 로그인 불필요 — 정적 데이터."
```

---

### Task 3: 강좌 검색 (search_courses)

**담당:** 팀원 B. `tier2/<이름>` 브랜치에서 진행 후 `tier2/merged`로 PR. Task 2와 병렬 가능.

**착수 전:** `.venv/Scripts/python auth/login_helper.py sugang`을 먼저 실행해 유효한 세션을 확보한다.

**fixture는 이미 확보되어 있다.** `tests/fixtures/lect_list_response.json`은 2026-08-07 팀장이 실제 로그인 세션으로 `search_courses(department_code="1200204", course_type="major", grade=3)`에 해당하는 요청(원시 파라미터로는 `pComboClsMajCd=1200204&pComboSugangCd=30&pComboGrade=3`)을 1회 호출해 받은 실제 응답이다(강좌 3건: 캡스톤디자인/ICT최신기술/iOS프로그래밍고급). 교수 사번(`memberNo`)은 개인정보라 `MASKED1`~`MASKED3`로 마스킹했다. **이 fixture는 새로 받을 필요 없다** — Step 1부터 바로 시작한다.

**Files:**
- Create: `tools/course_search.py`
- Modify: `common/models.py` — `CourseSummary`, `CourseList` 추가
- Test: `tests/test_course_search.py`
- Test fixture: `tests/fixtures/lect_list_response.json` (이미 존재)

**Interfaces:**
- Consumes: `common.session.require_session`, `common.session.require_active_session`, `common.http.fetch_authenticated`, `common.errors.ParseError`, `tools.departments.DEPARTMENTS` (department_code 유효성 검사용)
- Produces:
  - `common.models.CourseSummary(course_code, name, professor, category, credit, grade, schedule, capacity)`
  - `common.models.CourseList(courses: list[CourseSummary])`
  - `tools.course_search.CourseType = Literal["general", "major", "remote", "metamorphosis"]`
  - `tools.course_search.parse_courses(content: bytes) -> list[CourseSummary]`
  - `tools.course_search.search_courses(department_code: str, course_type: CourseType = "major", grade: int | None = None, keyword: str = "") -> CourseList`
  - `tools.course_search.register(mcp) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_course_search.py` — fixture의 실제 필드명(`subjectCd`, `subjectNmKor`, `nm`, `bunban`, `isuCdNm`, `credit`, `grade`, `time`, `limitNum`)을 그대로 쓴다("검증된 사실" 참고).

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/Scripts/python -m pytest tests/test_course_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.course_search'`

- [ ] **Step 3: `common/models.py`에 모델 추가**

파일 끝에 추가 (Task 2가 먼저 머지됐다면 그 아래에 이어 붙인다). `room`과 `enrolled`는 넣지 않는다 — `room`은 `schedule` 문자열 안에 이미 포함되고, 실시간 신청 인원(`enrolled`)은 이 응답에 없다("검증된 사실" 참고).

```python
class CourseSummary(BaseModel):
    course_code: str = Field(description="강좌 코드")
    name: str = Field(description="과목명")
    professor: str = Field(description="담당 교수명")
    category: str = Field(description="이수구분 (예: 전공과정, 교양필수)")
    credit: int = Field(description="학점")
    grade: int = Field(description="대상 학년")
    schedule: str = Field(description="강의 시간과 강의실. 교시마다 줄바꿈으로 구분")
    capacity: int = Field(description="정원. 실시간 신청 인원은 제공하지 않는다")


class CourseList(BaseModel):
    courses: list[CourseSummary] = Field(description="검색된 개설 강좌 목록")
```

- [ ] **Step 4: `tools/course_search.py` 구현**

```python
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_course_search.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: 실제 호출로 수동 확인**

```bash
.venv/Scripts/python -c "
from tools.course_search import search_courses
r = search_courses(department_code='1200204', course_type='major', grade=3)
print(len(r.courses), '개 강좌')
for c in r.courses[:3]:
    print(c.name, '|', c.professor, '|', c.credit, '학점 |', c.capacity, '명')
"
```

Expected: 정보통신공학과 3학년 전공 강좌가 실제로 나온다.

- [ ] **Step 7: 커밋 및 PR**

```bash
git add tools/course_search.py common/models.py tests/test_course_search.py tests/fixtures/lect_list_response.json
git commit -m "feat: 강좌 검색 툴 추가

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin tier2/<이름>
gh pr create --base tier2/merged --head tier2/<이름> --title "feat: 강좌 검색 툴 추가" --body "Task 3 구현"
```

---

### Task 4: 서버 통합

**담당:** 팀장. Task 2, 3 PR이 모두 `tier2/merged`에 머지된 뒤 진행.

**Files:**
- Modify: `server.py`

**Interfaces:**
- Consumes: `tools.departments.register`, `tools.course_search.register`

- [ ] **Step 1: `server.py`에 등록 추가**

```python
from tools import course_search, departments, library_seats, notices  # noqa: E402

mcp = MCPServer("mjc")
library_seats.register(mcp)
notices.register(mcp)
departments.register(mcp)
course_search.register(mcp)
```

- [ ] **Step 2: 툴 5개 등록 확인**

Run: `.venv/Scripts/python -c "import server; print(sorted(t.name for t in server.mcp._tool_manager.list_tools()))"`
Expected: `['get_library_seats', 'get_notice', 'list_departments', 'search_courses', 'search_notices']`

- [ ] **Step 3: 전체 테스트 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 전부 PASS (Task 1~3 신규분 포함)

- [ ] **Step 4: 실제 MCP 클라이언트로 다중 툴 조합 확인**

`list_departments()` → `search_courses(department_code=<정보통신공학과 코드>)` 순서로 실제 호출해 이어지는지 확인한다.

- [ ] **Step 5: README 갱신**

`README.md`의 "제공하는 툴" 표에 `list_departments`, `search_courses` 행을 추가하고, "이렇게 물어보세요"에 조합 질문 예시("정보통신공학과 1학년 개설 강좌 알려줘" 등)를 추가한다.

- [ ] **Step 6: 커밋 및 PR**

```bash
git add server.py README.md
git commit -m "feat: Tier 2 툴 서버 통합

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin tier2/<이름>
gh pr create --base tier2/merged --head tier2/<이름> --title "feat: Tier 2 서버 통합" --body "Task 4"
```

머지 후 `tier2/merged`를 `main`으로 PR — Tier 1과 동일한 2단계 흐름(`docs/superpowers/plans/2026-08-06-mjc-mcp-tier1.md`의 "브랜치 운영과 역할 분담" 참고).

---

## 데모 전 체크리스트 (Tier 2 포함 시)

- [ ] sugang 세션 수명이 관찰치로 30~40분이다. **시연 직전 로그인 헬퍼를 재실행**한다.
- [ ] 시연장 네트워크에서 sugang(`https://sugang.mjc.ac.kr`)이 접속되는지 확인한다.
- [ ] Tier 1과 달리 폴백 캐시가 없다(세션 만료 시 캐시로 답할 수 없는 성격의 데이터라서다) — 시연 중 세션이 끊기면 재로그인 안내만 나온다는 것을 인지하고 있는다.
