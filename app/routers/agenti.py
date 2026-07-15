from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.agent import Agente
from app.auth import get_current_user

router = APIRouter(prefix="/agenti", tags=["agenti"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_agenti(db: Session = Depends(get_db)):
    return db.query(Agente).all()


@router.get("/{agente_id}")
def get_agente(agente_id: str, db: Session = Depends(get_db)):
    agente = db.query(Agente).filter(Agente.id == agente_id).first()
    if not agente:
        raise HTTPException(status_code=404, detail="Agente non trovato")
    return agente


@router.post("/")
def crea_agente(data: dict, db: Session = Depends(get_db)):
    agente = Agente(**data)
    db.add(agente)
    db.commit()
    db.refresh(agente)
    return agente


@router.patch("/{agente_id}")
def aggiorna_agente(agente_id: str, data: dict, db: Session = Depends(get_db)):
    agente = db.query(Agente).filter(Agente.id == agente_id).first()
    if not agente:
        raise HTTPException(status_code=404, detail="Agente non trovato")
    for key, value in data.items():
        setattr(agente, key, value)
    db.commit()
    db.refresh(agente)
    return agente
