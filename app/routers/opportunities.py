from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case
from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.offer_line_item import OfferLineItem
from app.models.order import Order
from app.auth import get_current_user
from app.services import funnel_service

router = APIRouter(prefix="/opportunities", tags=["opportunities"], dependencies=[Depends(get_current_user)])

TODAY = date.today

STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al):
    if agente:
        q = q.filter(Opportunity.sap_creato_da == agente)
    if scadenza_dal:
        q = q.filter(Opportunity.data_scadenza >= scadenza_dal)
    if scadenza_al:
        q = q.filter(Opportunity.data_scadenza <= scadenza_al)
    if valore_min is not None:
        q = q.filter(Opportunity.valore_totale >= valore_min)
    if valore_max is not None:
        q = q.filter(Opportunity.valore_totale <= valore_max)
    if creazione_dal:
        q = q.filter(Opportunity.data_creazione_sap >= creazione_dal)
    if creazione_al:
        q = q.filter(Opportunity.data_creazione_sap <= creazione_al)
    return q


@router.get("/stats")
def stats_opportunity(
    db: Session = Depends(get_db),
    company_id: str = Query(None),
    agente: str = Query(None),
    scadenza_dal: date = Query(None),
    scadenza_al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    creazione_dal: date = Query(None),
    creazione_al: date = Query(None),
):
    today = date.today()
    q = db.query(Opportunity)
    if company_id:
        q = q.filter(Opportunity.company_id == company_id)
    q = _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al)

    row = q.with_entities(
        func.count(Opportunity.id),
        func.coalesce(func.sum(Opportunity.valore_totale), 0),
        func.count(case((Opportunity.stage == 'Chiuso Vinto', 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((
            (Opportunity.stage == 'Offerta Mandata') & (Opportunity.data_scadenza < today), 1
        ))),
        func.count(case((
            (Opportunity.stage == 'Offerta Mandata') &
            ((Opportunity.data_scadenza >= today) | (Opportunity.data_scadenza == None)), 1
        ))),
        func.coalesce(func.sum(case((Opportunity.stage == 'Chiuso Vinto', Opportunity.valore_totale))), 0),
        func.coalesce(func.sum(case((
            (Opportunity.stage.in_(STAGE_PERSA)) |
            ((Opportunity.stage == 'Offerta Mandata') & (Opportunity.data_scadenza < today)),
            Opportunity.valore_totale
        ))), 0),
        func.coalesce(func.sum(case((
            (Opportunity.stage == 'Offerta Mandata') &
            ((Opportunity.data_scadenza >= today) | (Opportunity.data_scadenza == None)),
            Opportunity.valore_totale
        ))), 0),
    ).one()

    totale, valore_tot, vinte, perse, scadute, attive, valore_vinto, valore_perso, valore_pipeline = row
    chiuse = vinte + perse + scadute
    return {
        "totale": totale,
        "vinte": vinte,
        "perse": perse,
        "scadute": scadute,
        "attive": attive,
        "chiuse": chiuse,
        "tasso_successo": round(vinte / chiuse * 100) if chiuse else None,
        "valore_pipeline": float(valore_pipeline),
        "valore_vinto": float(valore_vinto),
        "valore_perso": float(valore_perso),
    }


@router.get("/")
def lista_opportunity(
    db: Session = Depends(get_db),
    company_id: str = Query(None),
    agente: str = Query(None),
    stato: str = Query(None),
    scadenza_dal: date = Query(None),
    scadenza_al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    creazione_dal: date = Query(None),
    creazione_al: date = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
):
    today = date.today()
    q = db.query(Opportunity).options(joinedload(Opportunity.company))
    if company_id:
        q = q.filter(Opportunity.company_id == company_id)
    q = _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al)
    if stato == 'vinta':
        q = q.filter(Opportunity.stage == 'Chiuso Vinto')
    elif stato == 'persa':
        q = q.filter(Opportunity.stage.in_(STAGE_PERSA))
    elif stato == 'scaduta':
        q = q.filter(Opportunity.stage == 'Offerta Mandata', Opportunity.data_scadenza < today)
    elif stato == 'mandata':
        q = q.filter(Opportunity.stage == 'Offerta Mandata',
                     (Opportunity.data_scadenza >= today) | (Opportunity.data_scadenza == None))
    total = q.count()
    items = q.order_by(Opportunity.data_creazione_sap.desc()).offset(offset).limit(limit).all()

    opp_ids = [opp.id for opp in items]
    orders = db.query(Order.opportunity_id, Order.id, Order.sap_document_id).filter(
        Order.opportunity_id.in_(opp_ids)
    ).all()
    order_by_opp = {str(o.opportunity_id): {"order_id": str(o.id), "order_sap_document_id": o.sap_document_id} for o in orders}

    serialized = [
        {
            **{c.name: getattr(opp, c.name) for c in Opportunity.__table__.columns},
            "ragione_sociale": opp.company.ragione_sociale if opp.company else None,
            "order_id": order_by_opp.get(str(opp.id), {}).get("order_id"),
            "order_sap_document_id": order_by_opp.get(str(opp.id), {}).get("order_sap_document_id"),
        }
        for opp in items
    ]
    return {"total": total, "items": serialized}


@router.get("/{opportunity_id}")
def get_opportunity(opportunity_id: str, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity non trovata")
    return opp


@router.post("/")
def crea_opportunity(data: dict, db: Session = Depends(get_db)):
    return funnel_service.crea_opportunity(db, data)


@router.patch("/{opportunity_id}")
def aggiorna_opportunity(opportunity_id: str, data: dict, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity non trovata")
    for key, value in data.items():
        setattr(opp, key, value)
    db.commit()
    db.refresh(opp)
    return opp


@router.get("/{opportunity_id}/line_items")
def get_line_items(opportunity_id: str, db: Session = Depends(get_db)):
    items = db.query(OfferLineItem).filter(OfferLineItem.opportunity_id == opportunity_id).all()
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


@router.patch("/{opportunity_id}/stage")
def cambia_stage(opportunity_id: str, data: dict, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity non trovata")
    return funnel_service.cambia_stage(db, opp, data.get("stage"), data.get("loss_reason"))
