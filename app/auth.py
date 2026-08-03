from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.config import settings

SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Non autenticato")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")
    user = db.query(User).filter(User.id == user_id, User.attivo == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non trovato")
    return user


def require_admin(current_user=Depends(get_current_user)):
    from app.models.user import RuoloUtente
    if current_user.ruolo != RuoloUtente.admin:
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")
    return current_user


def is_admin(user) -> bool:
    from app.models.user import RuoloUtente
    return user.ruolo == RuoloUtente.admin


def company_agente_filter(user, query, Company):
    """Applica filtro agente sulla query di Company se l'utente non è admin."""
    if is_admin(user) or not user.zona_assegnata:
        return query
    from sqlalchemy import or_
    return query.filter(
        or_(
            Company.agente_ilsa == user.zona_assegnata,
            Company.agente_desco == user.zona_assegnata,
        )
    )


def allowed_company_ids(user, db):
    """Ritorna una subquery degli UUID di company accessibili dall'utente, o None se admin."""
    if is_admin(user) or not user.zona_assegnata:
        return None
    from app.models.company import Company
    from sqlalchemy import or_
    return db.query(Company.id).filter(
        or_(
            Company.agente_ilsa == user.zona_assegnata,
            Company.agente_desco == user.zona_assegnata,
        )
    ).subquery()
