from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth import hash_password, get_current_user

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.ruolo != "admin":
        raise HTTPException(status_code=403, detail="Solo gli admin possono eseguire questa operazione")
    return current_user


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


@router.delete("/{user_id}", status_code=204)
def elimina_utente(user_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if str(admin.id) == user_id:
        raise HTTPException(status_code=400, detail="Non puoi eliminare il tuo account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    db.delete(user)
    db.commit()
