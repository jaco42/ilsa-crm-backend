import uuid
import enum
from sqlalchemy import Column, String, Boolean, Enum, DateTime, Date, func, ForeignKey, Index
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
    # Azienda nel CRM. Stato dinamico calcolato a runtime: lead = prospect senza sap_customer_id,
    # prospect = sincronizzata da SAP con ID che inizia per 2 (es. 2001234),
    # cliente = sincronizzata da SAP con ID numerico crescente (es. 10012345).
    # Le company duplicate vengono fuse: quella inglobata diventa is_visible=False con merged_into → superstite.
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
    # Se True, il valore è stato modificato manualmente nel CRM e l'import SAP non lo sovrascrive
    # Es: utente aggiorna il telefono → telefono_override=True → SAP non tocca più quel campo
    telefono_override = Column(Boolean, nullable=False, default=False)
    email = Column(String, nullable=True)
    # Se True, il valore è stato modificato manualmente nel CRM e l'import SAP non lo sovrascrive
    # Es: utente aggiorna l'email → email_override=True → SAP non tocca più quel campo
    email_override = Column(Boolean, nullable=False, default=False)
    status = Column(Enum(CompanyStatus), nullable=False, default=CompanyStatus.prospect)
    sap_customer_id = Column(String, nullable=True, unique=True)
    sap_created_at = Column(Date, nullable=True)
    origin = Column(Enum(CompanyOrigin), nullable=False, default=CompanyOrigin.crm_manual)
    agente_ilsa = Column(String, nullable=True, index=True)
    agente_desco = Column(String, nullable=True, index=True)
    # Se True, l'agente è stato assegnato da SAP e non è modificabile manualmente nel CRM
    # Es: SAP assegna "Mario Rossi" → locked=True → il CRM blocca qualsiasi modifica manuale
    # SAP può comunque sovrascriverlo ad ogni import
    agente_ilsa_locked = Column(Boolean, nullable=False, default=False)
    # Se True, l'agente è stato assegnato da SAP e non è modificabile manualmente nel CRM
    # Es: SAP assegna "Luigi Bianchi" → locked=True → il CRM blocca qualsiasi modifica manuale
    # SAP può comunque sovrascriverlo ad ogni import
    agente_desco_locked = Column(Boolean, nullable=False, default=False)
    storico_contatti = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    merged_into = Column(UUID(as_uuid=True), ForeignKey('companies.id'), nullable=True)
    merged_at = Column(DateTime(timezone=True), nullable=True)
    is_visible = Column(Boolean, nullable=False, default=True)

    contacts = relationship("Contact", back_populates="company")
    sap_ids_secondari = relationship("CompanySapId", back_populates="company")
    aziende_inglobate = relationship("Company", foreign_keys=[merged_into], primaryjoin="Company.merged_into==Company.id")
