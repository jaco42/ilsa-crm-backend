import uuid
import enum
from sqlalchemy import Column, String, Boolean, Enum, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from app.database import Base


class RuoloUtente(str, enum.Enum):
    admin = "admin"
    rep = "rep"
    support = "support"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    ruolo = Column(Enum(RuoloUtente), nullable=False)
    zone_assegnate = Column(ARRAY(String), nullable=True, default=[])
    attivo = Column(Boolean, default=True, nullable=False)
    password_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
