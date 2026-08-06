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
