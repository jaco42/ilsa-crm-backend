from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.line_item import LineItem
from app.auth import get_current_user

router = APIRouter(prefix="/prodotti", tags=["prodotti"], dependencies=[Depends(get_current_user)])


@router.get("/famiglie")
def famiglie_prodotti(db: Session = Depends(get_db)):
    """Restituisce le coppie L1/L2 presenti nel DB, raggruppate per L1."""
    rows = db.execute(
        select(LineItem.categoria, LineItem.prodotto)
        .where(LineItem.categoria.isnot(None))
        .where(LineItem.prodotto.isnot(None))
        .distinct()
        .order_by(LineItem.categoria, LineItem.prodotto)
    ).fetchall()

    result = {}
    for l1, l2 in rows:
        result.setdefault(l1, []).append(l2)
    return result
