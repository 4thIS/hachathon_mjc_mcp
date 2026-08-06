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
