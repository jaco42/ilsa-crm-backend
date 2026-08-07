import uuid
from sqlalchemy import Column, String, Text, Numeric, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True)
    sap_document_id = Column(String, nullable=True, unique=True)
    org_cm = Column(String, nullable=True)
    tipo_doc = Column(String, nullable=True)
    committente_sap = Column(String, nullable=True)
    nota = Column(Text, nullable=True)
    contribuisce_fatturato = Column(Boolean, nullable=False, default=True)
    valore_totale = Column(Numeric, nullable=True)
    data_ordine = Column(Date, nullable=True)
    data_creazione_sap = Column(Date, nullable=True)
    sap_creato_da = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", backref="orders")
    opportunity = relationship("Opportunity", backref="orders")
    line_items = relationship("OrderLineItem", backref="order")
