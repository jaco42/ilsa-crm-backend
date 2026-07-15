from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.opportunity import Opportunity
from app.auth import get_current_user

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


def _apply_order_filters(q, agente, dal, al, valore_min, valore_max):
    if agente:
        q = q.filter(Order.sap_creato_da == agente)
    if dal:
        q = q.filter(Order.data_ordine >= dal)
    if al:
        q = q.filter(Order.data_ordine <= al)
    if valore_min is not None:
        q = q.filter(Order.valore_totale >= valore_min)
    if valore_max is not None:
        q = q.filter(Order.valore_totale <= valore_max)
    return q


@router.get("/stats")
def stats_ordini(
    company_id: str = Query(None),
    agente: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if company_id:
        q = q.filter(Order.company_id == company_id)
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max)

    row = q.with_entities(
        func.count(Order.id),
        func.coalesce(func.sum(Order.valore_totale), 0),
        func.count(Order.opportunity_id),
    ).one()
    totale, valore_totale, da_offerte = row
    return {
        "totale": totale,
        "valore_totale": float(valore_totale),
        "valore_medio": float(valore_totale / totale) if totale else 0,
        "da_offerte": da_offerte,
        "diretti": totale - da_offerte,
    }


@router.get("/")
def lista_ordini(
    company_id: str = Query(None),
    agente: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(Order).options(joinedload(Order.company))
    if company_id:
        q = q.filter(Order.company_id == company_id)
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max)
    total = q.count()
    orders = q.order_by(Order.data_ordine.desc()).offset(offset).limit(limit).all()

    opp_ids = [o.opportunity_id for o in orders if o.opportunity_id]
    opps = db.query(Opportunity.id, Opportunity.sap_document_id).filter(Opportunity.id.in_(opp_ids)).all()
    opp_sap = {str(op.id): op.sap_document_id for op in opps}

    items = [
        {
            "id": str(o.id),
            "company_id": str(o.company_id),
            "ragione_sociale": o.company.ragione_sociale if o.company else None,
            "sap_document_id": o.sap_document_id,
            "opportunity_id": str(o.opportunity_id) if o.opportunity_id else None,
            "opp_sap_document_id": opp_sap.get(str(o.opportunity_id)) if o.opportunity_id else None,
            "valore_totale": float(o.valore_totale) if o.valore_totale else 0,
            "data_ordine": o.data_ordine.isoformat() if o.data_ordine else None,
            "data_creazione_sap": o.data_creazione_sap.isoformat() if o.data_creazione_sap else None,
            "sap_creato_da": o.sap_creato_da,
        }
        for o in orders
    ]
    return {"total": total, "items": items}


@router.get("/{order_id}/line_items")
def get_order_line_items(order_id: str, db: Session = Depends(get_db)):
    items = db.query(OrderLineItem).filter(OrderLineItem.order_id == order_id).all()
    return [
        {
            "id": str(i.id),
            "codice_sap": i.codice_sap,
            "descrizione_riga": i.descrizione_riga,
            "quantita": float(i.quantita) if i.quantita is not None else None,
            "unita_misura": i.unita_misura,
            "prezzo_unitario": float(i.prezzo_unitario) if i.prezzo_unitario is not None else None,
            "totale_riga": float(i.totale_riga) if i.totale_riga is not None else None,
        }
        for i in items
    ]
