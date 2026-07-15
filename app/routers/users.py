from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth import hash_password, get_current_user

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_utenti(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/{user_id}")
def get_utente(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return user


@router.post("/")
def crea_utente(data: dict, db: Session = Depends(get_db)):
    user = User(**data)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/set-password")
def set_password(user_id: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    user.password_hash = hash_password(data["password"])
    db.commit()
    return {"ok": True}


@router.patch("/{user_id}")
def aggiorna_utente(user_id: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user
