"""ORM 模型：交易表与固定分类表；金额统一以「分」存储。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# 固定 8 类，模型输出必须落在其中，否则由 service 归入「其他」
CATEGORIES: tuple[str, ...] = ("餐饮", "交通", "购物", "居住", "娱乐", "医疗", "学习", "其他")
SOURCES: tuple[str, ...] = ("text", "image", "audio")
STATUSES: tuple[str, ...] = ("pending", "confirmed")


class Category(Base):
    """固定分类表，启动时由 seed 幂等写入 8 行。"""

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)


class Transaction(Base):
    """一笔交易。amount_cents 为整数分；status 区分草稿与已确认。"""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    merchant: Mapped[str] = mapped_column(String(128), nullable=False, default="", comment="商户")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="其他", index=True)
    occurred_at: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="消费日期")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="备注")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="text", comment="text/image/audio")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="原始输入（文本/ASR/OCR）")
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="图片去重哈希")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    def to_yuan_str(self) -> str:
        """展示用：分转元字符串，避免浮点误差。"""
        sign = "-" if self.amount_cents < 0 else ""
        cents = abs(self.amount_cents)
        return f"{sign}{cents // 100}.{cents % 100:02d}"
