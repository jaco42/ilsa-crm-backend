from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.prodotto import Prodotto
from app.auth import get_current_user

router = APIRouter(prefix="/prodotti", tags=["prodotti"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_prodotti(db: Session = Depends(get_db)):
    return db.query(Prodotto).all()


@router.get("/{prodotto_id}")
def get_prodotto(prodotto_id: str, db: Session = Depends(get_db)):
    prodotto = db.query(Prodotto).filter(Prodotto.id == prodotto_id).first()
    if not prodotto:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")
    return prodotto
