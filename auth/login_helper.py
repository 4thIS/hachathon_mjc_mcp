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
import uuid
from pathlib import Path

import httpx

# 스크립트로 직접 실행하면 sys.path[0]이 auth/가 되어 common/을 못 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.http import TIMEOUT, USER_AGENT  # noqa: E402
from common.session import save_session  # noqa: E402

LOGIN_URL = "https://sugang.mjc.ac.kr/loginChk"
APP_HOST = "sugang.mjc.ac.kr"

# /loginChk만 jQuery $.ajax로 보내는 요청이라 이 헤더가 필요하다. 그 외
# (창 등록, 로그인 성공 후 페이지 이동)는 브라우저의 일반 폼 제출/내비게이션이라
# 이 헤더를 보내지 않는다 — 붙이면 서버가 다르게 분기해 세션이 안 생긴다.
_AJAX_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def _cookies_for_host(cookies: httpx.Cookies, host: str) -> dict[str, str]:
    """도메인이 host와 일치하는 쿠키만 골라 dict로 평탄화한다.

    SSO 리다이렉트 체인이 여러 도메인을 거치면 같은 이름의 쿠키가 도메인만
    다르게 여러 개 잡힐 수 있다. dict(httpx.Cookies)는 이때 이름 충돌로
    CookieConflict를 던지므로, 실제 요청 대상 호스트에 붙는 것만 고른다.
    """
    result: dict[str, str] = {}
    for cookie in cookies.jar:
        domain = cookie.domain.lstrip(".")
        if host == domain or host.endswith("." + domain):
            result[cookie.name] = cookie.value
    return result


def _login_sugang() -> dict[str, str] | None:
    student_id = input("학번: ").strip()
    password = getpass.getpass("비밀번호: ")

    with httpx.Client(
        base_url="https://sugang.mjc.ac.kr",
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        # 0단계: 창 등록. 루트 페이지 로드 시 JS가 실제 <form>.submit()으로
        # POST /loginPage(appInfo, wName)를 보내는 것을 재현한다 — AJAX가 아니라
        # 일반 폼 제출이라 X-Requested-With가 없다. appInfo는 fnAppInfo()의
        # 실측값(항상 "0"), wName은 브라우저가 탭마다 새로 생성하는 UUID라
        # 여기서도 새로 만든다. 이 단계 없이 곧장 로그인하면 "유효한 창 없음"
        # 상태가 되어 로그인 자체는 성공해도 이후 API가 전부 세션 무효로 본다.
        try:
            client.post("/loginPage", data={"appInfo": "0", "wName": str(uuid.uuid4())})
        except httpx.HTTPError as exc:
            print(f"세션 초기화 요청 실패: {type(exc).__name__}", file=sys.stderr)
            return None

        try:
            response = client.post(
                LOGIN_URL,
                params={"fake": str(int(time.time() * 1000))},
                data={"txtUserID": student_id, "txtPwd": password},
                headers=_AJAX_HEADERS,
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

        # 로그인 JS는 성공 시 location.href = uri + "?fake=" + Date.now()로 실제
        # 페이지 이동을 한다. Referer가 없으면 서버가 세션을 무효로 본다(실측 확인) —
        # 로그인 폼이 있던 페이지를 출처로 표시해야 진짜 내비게이션처럼 취급된다.
        # client는 이미 follow_redirects=True에 User-Agent만 기본 헤더로 걸려
        # 있다(AJAX 헤더는 /loginChk 요청에만 개별적으로 붙였다).
        uri = body.get("uri")
        if uri:
            try:
                client.get(
                    uri,
                    params={"fake": str(int(time.time() * 1000))},
                    headers={"Referer": "https://sugang.mjc.ac.kr/loginPage"},
                )
            except httpx.HTTPError as exc:
                print(f"세션 확립 요청 실패: {type(exc).__name__}", file=sys.stderr)
                return None

        cookies = _cookies_for_host(client.cookies, APP_HOST)
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
