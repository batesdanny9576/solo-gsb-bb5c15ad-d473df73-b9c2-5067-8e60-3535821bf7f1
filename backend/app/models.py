"""SQLAlchemy 数据模型。"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 仅组织者持有，用于管理活动；不出现在参与者的揭晓链接里
    organizer_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # pending -> drawn；无解时保持 pending 并记录 failure_reason，可修改后重抽
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Participant.id",
    )
    forbidden_pairs: Mapped[list["ForbiddenPair"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("event_id", "name", name="uq_participant_event_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 一人一链：只有持有者能看到 ta 送出的对象
    reveal_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # 抽签结果（drawn 后写入）；组织者接口永不返回该字段
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("participants.id", ondelete="SET NULL"), nullable=True
    )
    revealed: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    event: Mapped[Event] = relationship(back_populates="participants")


class ForbiddenPair(Base):
    """禁配关系按无向对存储：a 与 b 互不能抽中对方（双向生效）。"""

    __tablename__ = "forbidden_pairs"
    __table_args__ = (
        UniqueConstraint("event_id", "lower_id", "higher_id", name="uq_forbidden_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lower_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    higher_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )

    event: Mapped[Event] = relationship(back_populates="forbidden_pairs")
