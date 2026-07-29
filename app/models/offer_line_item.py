import uuid
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class OfferLineItem(Base):
    __tablename__ = "offer_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False)
    codice_sap = Column(String, nullable=True)
    descrizione_riga = Column(String, nullable=True)
    quantita = Column(Numeric, nullable=True)
    unita_misura = Column(String, nullable=True)
    prezzo_unitario = Column(Numeric, nullable=True)
    totale_riga = Column(Numeric, nullable=True)
    gr_merci = Column(String, nullable=True)
    categoria = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
