"""bytes 응답을 파서에 넘기는 유일한 통로.

인코딩 판단을 이 파일 한 곳에 모은다. 호출자는 절대 resp.text를 쓰지 않는다.
"""

from bs4 import BeautifulSoup
from lxml import etree

_UTF8_BOM = b"\xef\xbb\xbf"


def parse_html(content: bytes) -> BeautifulSoup:
    """bytes를 그대로 넘겨 파서가 meta charset 선언을 보고 판단하게 한다."""
    return BeautifulSoup(content, "lxml")


def parse_xml(content: bytes) -> etree._Element:
    """XML 선언이 있는 bytes에 BOM이 붙어 있으면 lxml이 거부하므로 먼저 제거한다."""
    if content.startswith(_UTF8_BOM):
        content = content[len(_UTF8_BOM):]
    return etree.fromstring(content)
