"""툴 반환 모델.

반환 타입 어노테이션이 곧 MCP output schema가 되므로,
Field(description=...)이 AI가 읽는 스키마 설명이 된다.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ReadingRoom(BaseModel):
    name: str = Field(description="열람실 이름")
    total: int = Field(description="총 좌석 수")
    in_use: int = Field(description="현재 사용 중인 좌석 수")
    available: int = Field(description="현재 이용 가능한 잔여 좌석 수")


class LibrarySeatReport(BaseModel):
    rooms: list[ReadingRoom] = Field(description="열람실별 좌석 현황")
    measured_at: datetime = Field(
        description="이 좌석 수치를 실제로 조회한 시각(KST). "
        "실시간 데이터이므로 오래된 값을 현재 값처럼 인용하지 말 것."
    )
    stale_age_min: int | None = Field(
        default=None,
        description="학교 서버 조회에 실패해 캐시된 값을 반환한 경우, "
        "그 값이 몇 분 전 것인지. 실시간 조회에 성공했다면 null.",
    )


class NoticeSummary(BaseModel):
    notice_id: str = Field(
        description="get_notice에 그대로 넘길 식별자. 형식은 내부 구현이므로 해석하지 말 것."
    )
    title: str = Field(description="공지 제목")
    department: str = Field(description="작성 부서")
    posted_on: str = Field(description="작성일 (YYYY-MM-DD)")
    views: int = Field(description="조회수")
    pinned: bool = Field(description="상단 고정 공지 여부")


class NoticeList(BaseModel):
    category: str = Field(description="조회한 게시판 이름")
    notices: list[NoticeSummary] = Field(description="공지 목록. 최신순.")
    stale_age_min: int | None = Field(
        default=None,
        description="학교 서버 조회에 실패해 캐시된 값을 반환한 경우, "
        "그 값이 몇 분 전 것인지. 실시간 조회에 성공했다면 null.",
    )


class NoticeDetail(BaseModel):
    title: str = Field(description="공지 제목")
    department: str = Field(description="작성 부서")
    posted_on: str = Field(description="작성일 (YYYY-MM-DD)")
    views: int = Field(description="조회수")
    body: str = Field(
        description="본문 텍스트. 본문이 이미지로만 작성된 공지는 "
        "그 사실을 알리는 안내 문구가 들어간다."
    )
    attachments: list[str] = Field(description="첨부파일 이름 목록")
    truncated: bool = Field(description="본문이 길이 제한으로 잘렸는지 여부")
    stale_age_min: int | None = Field(
        default=None,
        description="학교 서버 조회에 실패해 캐시된 값을 반환한 경우, "
        "그 값이 몇 분 전 것인지. 실시간 조회에 성공했다면 null.",
    )
