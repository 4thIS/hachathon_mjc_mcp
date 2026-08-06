# 명지전문대 MCP 서버 — 설계 문서

> 2026년 명지전문대 캡스톤 경진대회 출품작. 작성 2026-08-06.

## 1. 문제 정의와 포지셔닝

학생이 "지금 도서관에 자리 있나", "이번 주 장학 공지가 뭐지"를 확인하려면 서로 다른 학교 사이트를 각각 들어가야 한다. 각 시스템은 잘 동작하지만 **서로 연결되어 있지 않고, AI가 읽을 수 있는 형태도 아니다.**

이 프로젝트는 챗봇 UI를 새로 만들지 않는다. **AI 에이전트가 학교 데이터에 직접 접근할 수 있게 하는 어댑터(MCP 서버)** 를 만든다.

이 구분이 핵심이다. 학교가 챗봇을 만들면 그 챗봇에서만 쓸 수 있지만, MCP는 **규격**이므로 Claude든 앞으로 나올 다른 AI 클라이언트든 그대로 붙는다. 우리가 미리 만들어두지 않은 질문에도 AI가 툴을 조합해 답할 수 있다.

## 2. 설계 우선순위

대회 심사 배점(기술 구현 완성도 30 / 문제 정의 및 기획성 20 / AI 활용 역량 20 / 실용성 20 / 산출물 완성도 10)에 맞춰 다음과 같이 판단했다.

- 완성도 계열이 40점으로 가장 크고 "창의성" 항목이 없다 → **툴 개수를 늘리는 것보다 안 깨지게 만드는 것이 우선.** 구조가 검증되지 않은 툴은 과감히 제외한다.
- AI 활용 역량 → **여러 툴을 조합해야 답이 나오는 질문**이 이 프로젝트의 본질이다. 단일 툴 호출은 API 래퍼로 보이지만, AI가 여러 데이터를 엮어 판단하는 것이 실제 가치다.
- 발표가 5분 라이브 데모이므로 **시연 중 실패는 곧 완성도 감점**이다. 견고성 작업을 부가 기능이 아니라 핵심 요구사항으로 다룬다.

## 3. 기술 스택

| 항목 | 선택 | 비고 |
|---|---|---|
| 언어 | Python | 팀 숙련도, 스크래핑 생태계 |
| MCP SDK | 공식 `mcp` SDK v2 | `from mcp.server import MCPServer`. `FastMCP`는 v1 이름이며 v2에서 개명되었다(공식 문서 확인). 동명의 서드파티 패키지와 혼동하지 않도록 requirements에 버전을 고정한다 |
| HTTP | `httpx` | 타임아웃 명시 |
| 파싱 | `beautifulsoup4` + `lxml` | |
| 스키마 | `pydantic` | 반환 타입 어노테이션이 곧 output schema |
| Transport | stdio | 로컬 연결 |

## 4. 아키텍처

```
server.py               # 진입점. 각 모듈의 register(mcp) 호출만
common/
  http.py               # httpx 클라이언트 팩토리: timeout, User-Agent, follow_redirects=False
  parse.py              # 인코딩 규칙을 이 한 곳에만
  errors.py
  cache.py              # 폴백용 디스크 캐시
  models.py             # Pydantic 반환 모델
tools/
  library_seats.py      # 각각 register(mcp)를 노출
  notices.py
  academic_calendar.py  # 조건부 — 구조 조사 결과에 따라 (7장)
tests/fixtures/         # 실제 응답 원본(bytes)
README.md
```

**Tier 2(인증 필요 기능)를 위한 추가 구조** — 8장 참고.

```
common/
  session.py            # 세션 파일 read/write + require_session() (auth/·tools/ 공용)
auth/
  login_helper.py        # 독립 CLI. 사용자가 직접 실행 (Claude가 실행하지 않음)
tools/
  departments.py         # list_departments() — 학과코드 스크래핑 + 캐시
  course_search.py       # search_courses() — 강좌 검색
```

**설계 근거**

- **툴 등록을 `server.py`에 몰지 않는다.** 3인 병렬 개발에서 한 파일을 여럿이 고치면 충돌한다. 각 툴 모듈이 `register(mcp)`를 노출하고 진입점은 호출만 한다.
- 확장 시 세션 저장소 접근은 `auth/`가 아니라 `common/`에 둔다. `tools/`도 읽어야 하므로 `tools → auth` 역방향 의존을 만들지 않기 위함이다.
- 툴 함수는 MCP 프레임워크에 의존하지 않는 평범한 함수로 작성하고 등록만 데코레이터로 한다 → 단독 실행과 테스트가 쉽다.

## 5. 툴 인터페이스

**내부 코드를 에이전트에게 노출하지 않는다.** 게시판 내부 파라미터 같은 값은 AI가 알 방법이 없으므로 서버가 흡수하고 의미 있는 enum만 노출한다.

```python
NoticeCategory = Literal["general", "academic", "scholarship", "job"]

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def get_library_seats() -> LibrarySeatReport: ...

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def search_notices(category: NoticeCategory = "academic", limit: int = 10) -> NoticeList: ...

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def get_notice(notice_id: str) -> NoticeDetail:
    """공지 본문 전문. notice_id는 반드시 search_notices 결과에서 얻을 것."""
```

- **목록과 상세를 분리한다.** 본문 전문은 토큰이 크므로 목록에 싣지 않는다.
- `get_notice`의 인자는 내부 코드가 아니라 목록이 돌려준 **불투명 ID 하나**다.
- `LibrarySeatReport`에는 **`measured_at`이 필수**다. 실시간 데이터인데 측정 시각이 없으면 AI가 과거 값을 현재 값으로 재사용한다.
- 본문에는 길이 제한과 `truncated` 플래그를 둔다. 원시 HTML이나 전체 필드 덤프는 반환하지 않는다.
- 모든 툴에 `read_only_hint=True, open_world_hint=True`를 붙인다. 클라이언트의 자동 승인 판단에 쓰여 사용 흐름이 매끄러워진다.

**반환 형식** — Pydantic `BaseModel`을 반환하면 SDK가 output schema를 자동 생성하고 구조화 데이터와 텍스트를 **둘 다** 채운다. `Field(description=...)`이 스키마 설명이 된다. 추가 비용이 거의 없으므로 dict 대신 모델을 쓴다.

## 6. 견고성

라이브 데모가 심사 기준이므로 다음을 부가 기능이 아닌 요구사항으로 다룬다.

| 위험 | 대응 |
|---|---|
| 시연장 네트워크에서 학교 서버 도달 실패 | 디스크 캐시 폴백. 실패 시 마지막 성공 데이터를 `stale=true, age_min=N`과 함께 반환. `MJC_MCP_OFFLINE=1`이면 fixture 재생. **시연 전 현장 네트워크에서 실측** |
| **stdout 오염으로 서버 정지** | stdio에서 stdout은 JSON-RPC 채널이다. `print()` 한 줄이나 라이브러리 경고 하나로 프로토콜이 깨진다. 로깅은 반드시 stderr로 보내고, 코드 리뷰에서 `print`를 금지한다 |
| Windows 콘솔 인코딩(cp949)에서 한글 출력 오류 | `sys.stdout.reconfigure(encoding="utf-8")` |
| 문자 인코딩 | 국내 사이트는 헤더가 utf-8인데 본문이 EUC-KR인 경우가 흔하다. **`resp.text`를 쓰지 않고 `resp.content`(bytes)를 파서에 넘긴다.** 결과에 U+FFFD가 있으면 euc-kr 디코드로 폴백 |
| fixture가 인코딩 버그를 감춤 | **fixture는 bytes 원본으로 저장한다.** 텍스트로 저장하면 테스트는 통과하고 실제 호출에서만 깨진다 |
| 무한 대기 | `httpx.Timeout(connect=3, read=5)` 명시 |
| 리다이렉트 감지 실패 | `follow_redirects=False` |

**재시도** — 조회 요청만 1회(0.5초 간격). 인증 요청은 재시도하지 않는다. 계정 잠금 정책을 확인하지 않은 상태에서 시연 당일 계정이 잠기면 복구할 수 없다.

**에러 처리** — 실패를 평범한 결과 문자열로 반환하면 AI가 성공으로 착각한다. 명시적 에러로 올리되 메시지는 **행동 지시형**으로 작성한다. 에러에 원문 HTML·헤더·쿠키를 싣지 않고 예외 타입명과 고정 문구만 쓴다.

## 7. 툴 구성

**확정 (구조 검증 완료)**
1. `get_library_seats` — 도서관 실시간 좌석 현황. 열람실 3개(집중학습공간 72석 / 개방형학습공간 146석 / 미디어실 44석). 인증 불필요, XML 응답.
2. `search_notices` / `get_notice` — 학사·장학·채용·일반 공지. 인증 불필요, 순수 HTML 파싱(JS 불필요).

**조사 후 결정**
3. `get_academic_calendar` — 학사일정. **날짜** 데이터라서 다른 모든 툴과 조합된다("다음 주에 시험 시작이야? 그럼 도서관 언제 가야 해?"). AI 활용 역량을 직접 보여주는 조합 질문이 가능해지는 것이 채택 이유다. 스크래핑 구조는 별도 조사가 진행 중이며, 결과가 확보되면 추가한다. 다른 툴과 독립된 모듈이므로 나중에 붙여도 기존 코드에 영향이 없다.

원래 후보였던 교수학습센터 프로그램 목록은 구조가 검증되지 않아 제외했다. 배점상 미완성 툴을 늘리는 것이 손해라고 판단했다.

## 8. Tier 2 — 인증이 필요한 기능

sugang(수강신청) 시스템 연동. Tier 1과 달리 로그인이 필요하므로 아래 원칙과 구조를 따른다.

**작업 시작 전 `/security-review`를 호출한다.** 전역 지침 B9(인증·인증정보·세션·토큰을 다룰 때)에 해당하므로, 구현 계획(writing-plans) 직후·실제 코딩 착수 직전에 실행한다.

### 8.1 원칙

- **비밀번호를 저장하지 않는다.** 교내 SSO는 90일마다 비밀번호 재설정을 강제하므로 저장된 비밀번호는 어차피 주기적으로 무효가 된다. 로그인 헬퍼가 실행될 때마다 입력받아 1회성으로 사용하고, 보관하는 것은 세션 정보뿐이다. 비밀번호 교체 주기와 캐시 무효화가 자연스럽게 맞아떨어진다.
- **로그인 헬퍼는 사용자가 별도 터미널에서 직접 실행한다.** AI 세션 안에서 실행하면 입출력이 대화 기록에 남는다.
- **자동 재로그인을 하지 않는다.** 캐시된 세션으로 먼저 시도하고, 실패가 감지되면 그때 사용자에게 헬퍼 재실행을 안내한다. 시간 기반으로 만료를 추적하지 않는다 — AI 에이전트는 호출 사이의 경과 시간을 알 수 없기 때문이다.
- **세션 정보는 저장소 바깥의 OS 사용자 데이터 경로에 둔다.** `.gitignore`만으로는 부족하다. 이미 추적된 파일에는 효력이 없고, 마감 직전 전체 스테이징 한 번으로 뚫린다. 프로젝트가 클라우드 동기화 폴더에 있으면 함께 동기화되는 문제도 있다.

**보호 범위를 정확히 적는다** — 파일 시스템 권한은 *다른 사용자 계정*으로부터 보호한다. **보호되지 않는 것**: 동일 계정으로 실행되는 모든 프로세스, 파일 복사·백업·git. OS 수준 암호화(Windows DPAPI 등)를 쓰면 *다른 PC로 복사된 사본*까지 범위가 넓어지지만 **동일 계정 프로세스는 여전히 막지 못한다.** 도입 대비 효용이 낮다고 판단해 채택하지 않고, 경로 분리와 짧은 세션 수명으로 대응한다.

**자격증명 취급** — 인증이 필요한 엔드포인트의 응답은 테스트 fixture로 저장하지 않는다. 학번·이름 등이 섞이면 공개 저장소에 영구히 남는다. 인증 응답 본문을 그대로 출력하지 않고 성공 여부만 다룬다.

### 8.2 담당자와 병렬 구조

로그인 기반(`auth/login_helper.py`, `common/session.py`)은 **팀장 혼자** 구현한다. 자격증명을 다루는 코드는 실수의 파급력이 되돌릴 수 없는 종류(B8/B9)라 범위를 좁게 유지한다. 완료 즉시 `tier2/merged`에 푸시하면, 그 위의 두 툴은 세션 쿠키를 캐시에서 읽어 쓰기만 할 뿐 자격증명 자체를 만지지 않으므로 팀원에게 병렬로 맡긴다.

| 담당 | 작업 | 비고 |
|---|---|---|
| 팀장 | `auth/login_helper.py`, `common/session.py` | `tier2/merged`에 직접 (Tier 1의 공통 레이어와 동일한 예외) |
| 팀원 A | `tools/departments.py` (`list_departments`) | 학과 드롭다운 스크래핑 + 캐시 |
| 팀원 B | `tools/course_search.py` (`search_courses`) | 강좌 검색. `department_code`는 `list_departments`가 준 값을 그대로 받음 |

두 툴 모두 세션 실패 감지를 반복 구현하지 않도록 `common/session.py`에 `require_session(system: str) -> httpx.Cookies`(세션 없으면 표준 에러를 던짐)를 공용 인터페이스로 둔다.

### 8.3 툴 인터페이스

내부 코드를 에이전트에게 노출하지 않는다는 Tier 1 원칙을 그대로 따른다. 학과코드는 고정 enum이 아니라 스크래핑으로 얻는 동적 값이므로, `search_notices`/`get_notice`와 같은 "목록 → 상세" 관용구를 재사용한다.

```python
@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def list_departments() -> DepartmentList:
    """sugang에 등록된 학과 목록을 조회한다.
    반환된 code를 search_courses의 department_code에 그대로 넘긴다."""

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def search_courses(department_code: str, grade: int | None = None, keyword: str = "") -> CourseList:
    """개설 강좌를 검색한다. department_code는 list_departments 결과에서 얻을 것."""
```

시간표 조합(여러 `search_courses` 호출을 엮어 시간표를 짜는 것)은 별도 툴로 만들지 않는다. AI가 스스로 할 수 있는 조합 추론이며, 따로 만드는 것은 중복 투자다.

### 8.4 데이터 흐름

```
1. 사용자가 별도 터미널에서 login_helper.py 실행
   → 학번/비밀번호 입력(에코 없음, 저장 안 함) → POST /loginChk
   → 성공 시 세션 쿠키만 %LOCALAPPDATA%\mjc-mcp\session_sugang.json 에 저장

2. AI가 list_departments() 호출
   → require_session()으로 세션 확인 → 실패 시 "로그인 헬퍼를 실행하세요" 에러
   → 성공 시 sugang 학과 드롭다운 GET → {code, name} 목록 반환 (로컬 캐시)

3. AI가 search_courses(department_code, ...) 호출
   → 같은 세션으로 POST /core/d/lectList → 강좌 목록 반환
```

### 8.5 에러 처리

- 세션 없음/만료(로그인 페이지로 리다이렉트 감지) → `"세션이 없거나 만료되었습니다. 별도 터미널에서 python auth/login_helper.py를 실행해 로그인해주세요."` — 자동 재로그인 없음
- 로그인 헬퍼 자체는 재시도 없음 (계정 잠금 리스크, Tier 1과 동일 원칙)
- 세션 관련 예외 메시지에 쿠키 값·응답 헤더를 절대 담지 않음

## 9. 테스트 전략

- **파서** — `tests/fixtures/`의 실제 응답 원본(bytes)으로 Pydantic 모델까지 검증하는 pytest. 데모 직전에 코드를 손볼 때 회귀를 잡아주는 안전망이다.
- **네트워크 호출** — 자동화하지 않고 수동 확인한다. 외부 실서비스에 의존하므로 모킹 인프라를 만드는 시간 대비 이득이 적다.
- 순서: fixture 확보(1회 실제 호출) → 실패하는 테스트 작성 → 파서 구현.

## 10. 데이터 수집 원칙

- 로그인 없이 볼 수 있는 **공개 페이지만** 조회한다.
- 동일 호스트에 대한 연속 요청 사이에 최소 1초 간격을 둔다. 사람이 브라우저로 접근하는 것보다 높은 빈도로 호출하지 않는다.
- 식별 가능한 User-Agent를 사용한다.
- `robots.txt`를 확인하고 결과를 README에 명기한다.
- 수집한 데이터를 외부로 전송하거나 저장·재배포하지 않는다. 조회 결과는 사용자의 AI 클라이언트에만 전달된다.
- 실제 서비스로 운영하려면 학사팀 협의가 전제임을 명시한다.

## 11. 범위 밖 (YAGNI)

자동 재로그인 · 백오프 라이브러리 · 구조화 로깅 · 게시판 페이지네이션 · 시간표 자동생성 툴(AI의 조합 추론으로 대체) · E-class/커리어 시스템 연동 · 시스템 간 SSO 세션 공유 검증.

## 12. 남은 확인 사항

1. 학사일정 스크래핑 구조 — 별도 세션에서 병렬 조사 중. 결과가 나오는 대로 툴을 추가하고, 어려우면 툴 2개로 확정한다 (7장)
2. ~~`robots.txt` 및 이용약관 내용~~ — **해결됨.** `www.mjc.ac.kr`은 `Allow: /`(전면 허용, 2026-08-06). `sugang.mjc.ac.kr`은 `robots.txt` 자체가 없음(2026-08-07). Tier 3 후보였던 `cyber.mjc.ac.kr`은 `Disallow: /`(전면 거부) — 이 때문에 Tier 3 진행을 보류했다(§13 참고).
3. 시연장 네트워크에서 도서관 API 도달 여부
4. 게시판 페이지네이션 파라미터 (범위 밖이지만 목록 개수 한계와 관련)
5. ~~**(Tier 2)** 로그인 성공 시 `Set-Cookie`(JSESSIONID 추정)의 실체~~ — **해결됨(2026-08-07).** 팀장이 `auth/login_helper.py`를 실제로 실행해 확인 — `httpx.Client`의 쿠키 잭이 로그인 응답의 `Set-Cookie`를 정상적으로 반영하고, `%LOCALAPPDATA%\mjc-mcp\session_sugang.json`에 세션이 정상 저장됨. 쿠키의 정확한 필드명은 자격증명 인접 정보라 여기 기록하지 않는다.
6. ~~**(Tier 2)** 강좌구분코드(`pComboSugangCd`)의 전체 매핑~~ — **해결됨(2026-08-07).** `10=교양, 30=전공, 60=원격강좌, 61=메타모포시스`. 학과코드와 함께 실제 로그인 세션으로 확보했다.
7. **(Tier 2)** sugang 세션 수명이 관찰치로 30~40분이다. 데모에 포함한다면 시연 직전 로그인 헬퍼 재실행을 체크리스트에 넣는다

## 13. Tier 3 조사 결과 (2026-08-07, 보류)

원래 후보였던 두 시스템을 조사했으나 둘 다 보류했다.

- **E-class(`cyber.mjc.ac.kr`)** — `robots.txt`가 `Disallow: /`로 전면 크롤링 거부. CSRF 토큰 요구(계획 문서 기존 기록)에 더해 정책적으로도 명시적 거부라 진행하지 않는다.
- **커리어정보(`mpu.mjc.ac.kr`)** — `robots.txt`는 없지만, 응답 헤더 `X-Frame-Options: SAMEORIGIN ALLOW-FROM https://cyber.mjc.ac.kr`로 **cyber 안에 iframe으로 삽입되는 종속 시스템**임을 확인. `Content-Security-Policy`의 `connect-src`에 `wss://aws.huno.kr:4443`(제3자 도메인)이 있어 **외부 벤더의 화이트라벨 제품**으로 추정된다. 원래 계획 문서의 "ASP.NET 추정"은 근거를 찾지 못했다(관련 흔적 없음, 오히려 SPA 구조). cyber에 종속된 데다 제3자 서비스라 판단이 더 필요해 보류.
