import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from app.database import Base


class EmailReminder(Base):
    __tablename__ = "email_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
    oggetto = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    destinatario = Column(String, nullable=False)
    cc = Column(ARRAY(String), nullable=True, default=list)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending | sent | failed
    sent_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)        # nome agente mittente
    mittente_email = Column(String, nullable=True)    # email agente mittente (Reply-To)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    company = relationship("Company")
    opportunity = relationship("Opportunity")
