from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, exists
from app.database import get_db
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.opportunity import Opportunity
from app.models.company import Company
from app.auth import get_current_user

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


def _apply_order_filters(q, agente, dal, al, valore_min, valore_max, gr_merci=None, categoria=None):
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
    if gr_merci or categoria:
        sub = select(OrderLineItem.order_id).where(
            OrderLineItem.order_id == Order.id
        ).correlate(Order)
        if gr_merci:
            sub = sub.where(OrderLineItem.gr_merci == gr_merci)
        if categoria:
            sub = sub.where(OrderLineItem.categoria == categoria)
        q = q.filter(exists(sub))
    return q


@router.get("/stats")
def stats_ordini(
    company_id: str = Query(None),
    agente: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    gr_merci: str = Query(None),
    categoria: str = Query(None),
    kpi_dal: date = Query(None),
    kpi_al: date = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if company_id:
        q = q.filter(Order.company_id == company_id)
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max, gr_merci=gr_merci, categoria=categoria)

    totale = q.count()

    q_ytd = q
    if kpi_dal:
        q_ytd = q_ytd.filter(Order.data_ordine >= kpi_dal)
    if kpi_al:
        q_ytd = q_ytd.filter(Order.data_ordine <= kpi_al)

    q_joined = q_ytd.join(OrderLineItem, OrderLineItem.order_id == Order.id)
    if gr_merci:
        q_joined = q_joined.filter(OrderLineItem.gr_merci == gr_merci)
    if categoria:
        q_joined = q_joined.filter(OrderLineItem.categoria == categoria)
    totale_ytd, valore_totale, da_offerte = (
        q_joined.with_entities(
            func.count(func.distinct(Order.id)),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0),
            func.count(func.distinct(Order.opportunity_id)),
        ).one()
    )

    return {
        "totale": totale,
        "totale_ytd": totale_ytd,
        "valore_totale": float(valore_totale),
        "valore_medio": float(valore_totale / totale_ytd) if totale_ytd else 0,
        "da_offerte": da_offerte,
        "diretti": totale_ytd - da_offerte,
    }


@router.get("/")
def lista_ordini(
    company_id: str = Query(None),
    agente: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    gr_merci: str = Query(None),
    categoria: str = Query(None),
    search: str = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(Order).options(joinedload(Order.company))
    if company_id:
        q = q.filter(Order.company_id == company_id)
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max, gr_merci=gr_merci, categoria=categoria)
    if search:
        q = q.join(Company, Order.company_id == Company.id, isouter=True)
        q = q.filter(
            Order.sap_document_id.ilike(f"%{search}%") |
            Company.ragione_sociale.ilike(f"%{search}%")
        )
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
            "gr_merci": i.gr_merci,
            "categoria": i.categoria,
        }
        for i in items
    ]
