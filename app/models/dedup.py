import uuid
from sqlalchemy import Column, String, Boolean, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class DeduplicaAlert(Base):
    __tablename__ = "dedup_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_a_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    company_b_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String, nullable=False)  # "piva_identica" | "nome_e_via_identici"
    score_nome = Column(Float, nullable=True)
    score_via = Column(Float, nullable=True)
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_action = Column(String, nullable=True)  # "merged" | "dismissed" | "auto_merged"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    company_a = relationship("Company", foreign_keys=[company_a_id])
    company_b = relationship("Company", foreign_keys=[company_b_id])
