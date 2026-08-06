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
