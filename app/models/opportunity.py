import uuid
from sqlalchemy import Column, String, Text, Numeric, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


STAGE_VALIDI = [
    "Offerta Mandata",
    "Scaduta",
    "Chiuso Vinto",
    "Chiuso Perso",
]


class Opportunity(Base):
    # Offerta commerciale importata da SAP (tabella VBAK, sap_document_id inizia per 5).
    # Non si crea manualmente nel CRM.
    # Stage: Offerta Mandata → Scaduta (job giornaliero) / Chiuso Vinto (import SAP) / Chiuso Perso (operatore CRM).
    __tablename__ = "opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True)
    stage = Column(String, nullable=False, default="Offerta Mandata")
    sap_document_id = Column(String, nullable=True, unique=True)
    # Canale commerciale SAP: OC00 = ILSA, OC02 = DESCO
    org_cm = Column(String, nullable=True)
    # Tipo documento SAP (TpDV): ZOI0/ZOC0/ZOE0=standard, ZRAS=riparazione, ZSOG=garanzia, ZFIN=fiera, ZVIN=visione, ZAMM=amministrativo
    tipo_doc = Column(String, nullable=True)
    # SAP ID del cliente che ha ricevuto l'offerta (può differire dalla company principale)
    committente_sap = Column(String, nullable=True)
    nota = Column(Text, nullable=True)
    # Se True, il documento entra nel fatturato della dashboard. False per garanzie, fiere, visioni, ZAMM senza sfridi/royalties
    contribuisce_fatturato = Column(Boolean, nullable=False, default=True)
    valore_totale = Column(Numeric, nullable=True)
    data_scadenza = Column(Date, nullable=True)
    data_creazione_sap = Column(Date, nullable=True)
    # Utente/postazione SAP che ha creato il documento
    sap_creato_da = Column(String, nullable=True)
    loss_reason = Column(String, nullable=True)
    # Data ultima modifica dello stage, usata per visualizzazione in frontend
    stage_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", backref="opportunities")
    contact = relationship("Contact", backref="opportunities")
    line_items = relationship("LineItem", back_populates="opportunity", foreign_keys="LineItem.opportunity_id")
