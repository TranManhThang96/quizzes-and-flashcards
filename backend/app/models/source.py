from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Source(Base):
    """Văn bản nguồn đã trích xuất: admin dán, PDF hoặc URL.

    `text` là văn bản đã bóc; tệp PDF gốc không được lưu lại. Không có endpoint
    xoá nguồn trong bản này, và FK từ `items`/`generation_jobs` dùng RESTRICT
    nên một nguồn đang được tham chiếu không thể bị xoá.
    """

    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("kind in ('text', 'pdf', 'url')", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
