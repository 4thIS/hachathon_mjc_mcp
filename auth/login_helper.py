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
from pathlib import Path

import httpx

# 스크립트로 직접 실행하면 sys.path[0]이 auth/가 되어 common/을 못 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.http import TIMEOUT, USER_AGENT  # noqa: E402
from common.session import save_session  # noqa: E402

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
