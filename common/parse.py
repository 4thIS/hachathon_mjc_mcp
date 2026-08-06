"""bytes 응답을 파서에 넘기는 유일한 통로.

인코딩 판단을 이 파일 한 곳에 모은다. 호출자는 절대 resp.text를 쓰지 않는다.
파싱 실패는 여기서 ParseError로 바꿔 올린다. 호출자가 감쌀 필요가 없고,
학교 서버가 XML 대신 오류 HTML을 줘도 ToolError 경계 안에 머문다.
"""

from bs4 import BeautifulSoup
from bs4.exceptions import ParserRejectedMarkup
from lxml import etree

from common.errors import ParseError

_UTF8_BOM = b"\xef\xbb\xbf"


def parse_html(content: bytes) -> BeautifulSoup:
    """bytes를 그대로 넘겨 파서가 meta charset 선언을 보고 판단하게 한다."""
    try:
        return BeautifulSoup(content, "lxml")
    except ParserRejectedMarkup:
        # 원문이 메시지에 섞이지 않도록 예외 체인을 끊는다.
        raise ParseError("HTML 응답") from None


def parse_xml(content: bytes) -> etree._Element:
    """XML 선언이 있는 bytes에 BOM이 붙어 있으면 lxml이 거부하므로 먼저 제거한다."""
    if content.startswith(_UTF8_BOM):
        content = content[len(_UTF8_BOM):]
    try:
        return etree.fromstring(content)
    except (etree.LxmlError, ValueError):
        # XMLSyntaxError 메시지에는 원문 토큰이 섞이므로 체인을 끊고 버린다.
        raise ParseError("XML 응답") from None
