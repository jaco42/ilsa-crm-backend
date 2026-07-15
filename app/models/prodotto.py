import uuid
from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Prodotto(Base):
    __tablename__ = "prodotti"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codice_sap = Column(String, nullable=True, unique=True)
    nome = Column(String, nullable=False)
    categoria = Column(String, nullable=True)
    attivo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
