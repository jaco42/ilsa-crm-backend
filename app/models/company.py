import uuid
import enum
from sqlalchemy import Column, String, Boolean, Enum, DateTime, Date, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class CompanyOrigin(str, enum.Enum):
    crm_manual = "crm_manual"
    sap_sync = "sap_sync"


class CompanyStatus(str, enum.Enum):
    prospect = "prospect"
    cliente = "cliente"


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ragione_sociale = Column(String, nullable=False)
    partita_iva = Column(String, nullable=True)
    indirizzo = Column(String, nullable=True)
    citta = Column(String, nullable=True)
    cap = Column(String, nullable=True)
    provincia = Column(String, nullable=True)
    paese = Column(String, nullable=True)
    tipo_attivita = Column(String, nullable=True)
    website = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    telefono_override = Column(Boolean, nullable=False, default=False)
    email = Column(String, nullable=True)
    email_override = Column(Boolean, nullable=False, default=False)
    status = Column(Enum(CompanyStatus), nullable=False, default=CompanyStatus.prospect)
    sap_customer_id = Column(String, nullable=True, unique=True)
    sap_created_at = Column(Date, nullable=True)
    origin = Column(Enum(CompanyOrigin), nullable=False, default=CompanyOrigin.crm_manual)
    agente = Column(String, nullable=True)
    storico_contatti = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    contacts = relationship("Contact", back_populates="company")
    sap_ids_secondari = relationship("CompanySapId", back_populates="company")
