import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_nome   = Column(String, nullable=False)
    action      = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id   = Column(String, nullable=True)
    company_id  = Column(String, nullable=True)
    company_nome= Column(String, nullable=True)
    detail      = Column(JSONB, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
