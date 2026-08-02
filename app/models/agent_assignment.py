from sqlalchemy import Column, String
from app.database import Base


class AgentAssignment(Base):
    __tablename__ = "agent_assignments"

    cliente_sap = Column(String, primary_key=True)
    org_cm      = Column(String, primary_key=True)
    zn          = Column(String, nullable=False, index=True)
