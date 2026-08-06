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
