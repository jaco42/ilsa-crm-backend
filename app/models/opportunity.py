import uuid
from sqlalchemy import Column, String, Text, Numeric, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


STAGE_VALIDI = [
    "Offerta Mandata",
    "Chiuso Vinto",
    "Drop pre-offerta",
    "Drop post-offerta",
    "Chiuso Perso",
]


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True)
    stage = Column(String, nullable=False, default="Offerta Mandata")
    canale_acquisizione = Column(String, nullable=True)
    sap_document_id = Column(String, nullable=True, unique=True)
    org_cm = Column(String, nullable=True)
    tipo_doc = Column(String, nullable=True)
    committente_sap = Column(String, nullable=True)
    nota = Column(Text, nullable=True)
    contribuisce_fatturato = Column(Boolean, nullable=False, default=True)
    valore_totale = Column(Numeric, nullable=True)
    data_scadenza = Column(Date, nullable=True)
    data_creazione_sap = Column(Date, nullable=True)
    sap_creato_da = Column(String, nullable=True)
    loss_reason = Column(String, nullable=True)
    stage_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", backref="opportunities")
    contact = relationship("Contact", backref="opportunities")
    line_items = relationship("LineItem", back_populates="opportunity", foreign_keys="LineItem.opportunity_id")
