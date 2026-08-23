from sqlalchemy import Column, String
from app.database import Base


class AgentAssignment(Base):
    # Mappa SAP: per ogni cliente (cliente_sap) e canale (org_cm: OC00=ILSA, OC02=DESCO),
    # indica la zona (zn) dell'agente assegnato.
    # Popolata dall'import SAP via tabella KNVV. Usata per risolvere agente_ilsa/agente_desco su Company.
    __tablename__ = "agent_assignments"

    cliente_sap = Column(String, primary_key=True)
    org_cm      = Column(String, primary_key=True)
    zn          = Column(String, nullable=False, index=True)
