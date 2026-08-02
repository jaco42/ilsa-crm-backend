from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, union
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.offer_line_item import OfferLineItem
from app.models.order_line_item import OrderLineItem
from app.models.prodotto import Prodotto
from app.auth import get_current_user

router = APIRouter(prefix="/prodotti", tags=["prodotti"], dependencies=[Depends(get_current_user)])


@router.get("/famiglie")
def famiglie_prodotti(db: Session = Depends(get_db)):
    """Restituisce le coppie L1/L2 presenti nel DB, raggruppate per L1."""
    q = union(
        select(OfferLineItem.categoria, OfferLineItem.prodotto),
        select(OrderLineItem.categoria, OrderLineItem.prodotto),
    ).subquery()
    rows = db.execute(
        select(q.c.categoria, q.c.prodotto)
        .where(q.c.categoria.isnot(None))
        .where(q.c.prodotto.isnot(None))
        .distinct()
        .order_by(q.c.categoria, q.c.prodotto)
    ).fetchall()

    result = {}
    for l1, l2 in rows:
        result.setdefault(l1, []).append(l2)
    return result


@router.get("/")
def lista_prodotti(db: Session = Depends(get_db)):
    return db.query(Prodotto).all()


@router.get("/{prodotto_id}")
def get_prodotto(prodotto_id: str, db: Session = Depends(get_db)):
    prodotto = db.query(Prodotto).filter(Prodotto.id == prodotto_id).first()
    if not prodotto:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")
    return prodotto
