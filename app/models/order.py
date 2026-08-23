import uuid
from sqlalchemy import Column, String, Text, Numeric, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Order(Base):
    # Ordine confermato importato da SAP (tabella VBAK, documenti di tipo ordine).
    # Collegato all'offerta di origine tramite opportunity_id, risolto dall'import SAP via tabella VBFA.
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True)
    sap_document_id = Column(String, nullable=True, unique=True)
    # Canale commerciale SAP: OC00 = ILSA, OC02 = DESCO
    org_cm = Column(String, nullable=True, index=True)
    # Tipo documento SAP (TpDV): ZOI0/ZOC0/ZOE0=standard, ZRAS=riparazione, ZSOG=garanzia, ZFIN=fiera, ZVIN=visione, ZAMM=amministrativo
    tipo_doc = Column(String, nullable=True)
    # SAP ID del cliente che ha ricevuto l'ordine (può differire dalla company principale)
    committente_sap = Column(String, nullable=True)
    nota = Column(Text, nullable=True)
    # Se True, il documento entra nel fatturato della dashboard. False per garanzie, fiere, visioni, ZAMM senza sfridi/royalties
    contribuisce_fatturato = Column(Boolean, nullable=False, default=True)
    valore_totale = Column(Numeric, nullable=True)
    data_ordine = Column(Date, nullable=True)
    data_creazione_sap = Column(Date, nullable=True)
    # Utente/postazione SAP che ha creato il documento
    sap_creato_da = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", backref="orders")
    opportunity = relationship("Opportunity", backref="orders")
    line_items = relationship("LineItem", back_populates="order", foreign_keys="LineItem.order_id")
