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
