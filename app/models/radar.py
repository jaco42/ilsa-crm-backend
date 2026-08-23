import uuid
from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class RadarProdotto(Base):
    # Prodotto censito nel catalogo Radar, creato manualmente dagli agenti.
    # Supporta merge tra duplicati (merged_into_id).
    # Distinto dalle stringhe libere nei line_items SAP: qui i prodotti sono strutturati e categorizzati.
    __tablename__ = "radar_prodotti"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    categoria_l1 = Column(String, nullable=True)
    categoria_l2 = Column(String, nullable=True)
    merged_into_id = Column(UUID(as_uuid=True), ForeignKey("radar_prodotti.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    segnalazioni = relationship("RadarSegnalazione", back_populates="prodotto")


class RadarSegnalazione(Base):
    # Interesse di una company per un prodotto del catalogo Radar, inserito dall'agente.
    # Traccia quantità, urgenza e zona — permette di misurare la domanda di mercato.
    __tablename__ = "radar_segnalazioni"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prodotto_id = Column(UUID(as_uuid=True), ForeignKey("radar_prodotti.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    quantita = Column(Float, nullable=True)
    unita = Column(String, nullable=True)  # pz | m3
    urgenza = Column(String, nullable=True)  # bassa | media | alta
    note = Column(Text, nullable=True)
    zona = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("agenti.id"), nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    prodotto = relationship("RadarProdotto", back_populates="segnalazioni")
    company = relationship("Company")
    agente = relationship("Agente")
