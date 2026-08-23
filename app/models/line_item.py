import uuid
from sqlalchemy import Column, String, Text, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class LineItem(Base):
    # Riga singola di un'offerta o ordine, importata da SAP (tabella VBAP).
    # document_type='offer' → link a opportunity_id, 'order' → link a order_id.
    __tablename__ = "line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_type = Column(String, nullable=False)  # 'offer' | 'order'
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    codice_sap = Column(String, nullable=True)
    descrizione_riga = Column(String, nullable=True)
    quantita = Column(Numeric, nullable=True)
    unita_misura = Column(String, nullable=True)
    prezzo_unitario = Column(Numeric, nullable=True)
    totale_riga = Column(Numeric, nullable=True)
    categoria = Column(String, nullable=True)
    # Sottocategoria L2 del prodotto (stringa libera importata da SAP, non un FK)
    prodotto = Column(String, nullable=True)
    nota = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    opportunity = relationship("Opportunity", back_populates="line_items", foreign_keys=[opportunity_id])
    order = relationship("Order", back_populates="line_items", foreign_keys=[order_id])
