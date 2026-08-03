from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    user = db.query(User).filter(User.email == email, User.attivo == True).first()
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")
    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "nome": user.nome,
            "email": user.email,
            "ruolo": user.ruolo,
            "zona_assegnata": user.zona_assegnata,
        },
    }


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "nome": current_user.nome,
        "email": current_user.email,
        "ruolo": current_user.ruolo,
        "zona_assegnata": current_user.zona_assegnata,
    }
