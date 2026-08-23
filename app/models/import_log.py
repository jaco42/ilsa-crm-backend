import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class ImportLog(Base):
    # Log di un import bulk CSV di aziende o contatti.
    # Registra creati/aggiornati/saltati con snapshot prima/dopo, per permettere l'undo dell'import.
    __tablename__ = "import_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo = Column(String, nullable=False)          # "aziende" | "contatti"
    created_by = Column(String, nullable=True)
    creati = Column(Integer, default=0, nullable=False)
    aggiornati = Column(Integer, default=0, nullable=False)
    saltati = Column(Integer, default=0, nullable=False)
    dettaglio_saltati = Column(JSON, default=list, nullable=False)
    # IDs of records created by this import (str UUIDs)
    created_ids = Column(JSON, default=list, nullable=False)
    # [{id, ragione_sociale/nome, before: {fields}, after: {fields}}]
    updated_snapshots = Column(JSON, default=list, nullable=False)
    # IDs of Note records created by this import
    note_ids = Column(JSON, default=list, nullable=False)
    undone_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
