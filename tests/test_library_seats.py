from pathlib import Path

import pytest

from common.errors import ParseError
from tools.library_seats import parse_seats

FIXTURE = Path(__file__).parent / "fixtures" / "library_seats.xml"


def test_parses_three_reading_rooms():
    rooms = parse_seats(FIXTURE.read_bytes())
    assert len(rooms) == 3
    assert [r.name for r in rooms] == ["집중학습공간", "개방형학습공간", "미디어실"]


def test_parses_seat_counts():
    rooms = {r.name: r for r in parse_seats(FIXTURE.read_bytes())}
    assert rooms["집중학습공간"].total == 72
    assert rooms["개방형학습공간"].total == 146
    assert rooms["미디어실"].total == 44


def test_available_and_in_use_are_integers():
    for room in parse_seats(FIXTURE.read_bytes()):
        assert isinstance(room.in_use, int)
        assert isinstance(room.available, int)
        assert room.in_use + room.available <= room.total


def test_raises_parse_error_when_no_items():
    with pytest.raises(ParseError):
        parse_seats(b"<root><data><page>1</page></data></root>")
