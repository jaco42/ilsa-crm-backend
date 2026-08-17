from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, exists, nullslast, case
from app.database import get_db
from app.models.order import Order
from app.models.line_item import LineItem
from app.models.opportunity import Opportunity
from app.models.company import Company
from app.auth import get_current_user, allowed_doc_cond

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


TIPO_DOC_GROUPS = {
    "standard":  ["ZOI0", "ZOC0", "ZOE0"],
    "garanzia":  ["ZSOG"],
    "riparazione": ["ZRAS"],
    "fiera":     ["ZFIN"],
    "visione":   ["ZVIN"],
    "amministrativo": ["ZAMM"],
}

def _apply_order_filters(q, agente, dal, al, valore_min, valore_max, categoria=None, prodotto=None, org_cm=None, agente_zona=None, tipo_doc=None, sap_id=None):
    if sap_id:
        from app.models.company import Company as CompanyModel
        sap_sub = select(CompanyModel.id).where(CompanyModel.sap_customer_id == sap_id)
        q = q.filter(Order.company_id.in_(sap_sub))
    if agente:
        q = q.filter(Order.sap_creato_da == agente)
    if agente_zona:
        from app.models.company import Company as CompanyModel
        from sqlalchemy import or_, and_
        ilsa_sub = select(CompanyModel.id).where(CompanyModel.agente_ilsa == agente_zona)
        desco_sub = select(CompanyModel.id).where(CompanyModel.agente_desco == agente_zona)
        q = q.filter(
            or_(
                and_(Order.company_id.in_(ilsa_sub), Order.org_cm == 'OC00'),
                and_(Order.company_id.in_(desco_sub), Order.org_cm == 'OC02'),
            )
        )
    if org_cm:
        q = q.filter(Order.org_cm == org_cm)
    if dal:
        q = q.filter(Order.data_ordine >= dal)
    if al:
        q = q.filter(Order.data_ordine <= al)
    if valore_min is not None:
        q = q.filter(Order.valore_totale >= valore_min)
    if valore_max is not None:
        q = q.filter(Order.valore_totale <= valore_max)
    if categoria or prodotto:
        sub = select(LineItem.order_id).where(
            LineItem.order_id == Order.id,
            LineItem.document_type == 'order',
        ).correlate(Order)
        if not categoria:
            sub = sub.where(LineItem.totale_riga > 0)
        if categoria:
            sub = sub.where(LineItem.categoria == categoria)
        if prodotto:
            sub = sub.where(LineItem.prodotto == prodotto)
        q = q.filter(exists(sub))
    if tipo_doc and tipo_doc in TIPO_DOC_GROUPS:
        q = q.filter(Order.tipo_doc.in_(TIPO_DOC_GROUPS[tipo_doc]))
    return q


@router.get("/stats")
def stats_ordini(
    company_id: str = Query(None),
    agente: str = Query(None),
    agente_zona: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    categoria: str = Query(None),
    prodotto: str = Query(None),
    org_cm: str = Query(None),
    tipo_doc: str = Query(None),
    sap_id: str = Query(None),
    kpi_dal: date = Query(None),
    kpi_al: date = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(Order)
    cond = allowed_doc_cond(current_user, Order, Company)
    if cond is not None:
        q = q.filter(cond)
    if company_id:
        merged_ids = [str(r[0]) for r in db.query(Company.id).filter(Company.merged_into == company_id).all()]
        q = q.filter(Order.company_id.in_([company_id] + merged_ids))
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max, categoria=categoria, prodotto=prodotto, org_cm=org_cm, agente_zona=agente_zona, tipo_doc=tipo_doc, sap_id=sap_id)

    totale = q.count()

    q_ytd = q
    if kpi_dal:
        q_ytd = q_ytd.filter(Order.data_ordine >= kpi_dal)
    if kpi_al:
        q_ytd = q_ytd.filter(Order.data_ordine <= kpi_al)

    q_joined = q_ytd.join(LineItem, (LineItem.order_id == Order.id) & (LineItem.document_type == 'order'))
    if categoria:
        q_joined = q_joined.filter(LineItem.categoria == categoria)
    if prodotto:
        q_joined = q_joined.filter(LineItem.prodotto == prodotto)
    if categoria == 'Trasporti':
        valore_expr = func.coalesce(func.sum(case(
            (Order.contribuisce_fatturato == True, LineItem.totale_riga), else_=0
        )), 0)
    else:
        valore_expr = func.coalesce(func.sum(case(((Order.contribuisce_fatturato == True) & (LineItem.categoria != 'Trasporti'), LineItem.totale_riga), else_=0)), 0)
    totale_ytd, valore_totale, da_offerte = (
        q_joined.with_entities(
            func.count(func.distinct(Order.id)),
            valore_expr,
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
    agente_zona: str = Query(None),
    dal: date = Query(None),
    al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    categoria: str = Query(None),
    prodotto: str = Query(None),
    org_cm: str = Query(None),
    tipo_doc: str = Query(None),
    sap_id: str = Query(None),
    search: str = Query(None),
    sort_by: str = Query('data_ordine'),
    sort_dir: str = Query('desc'),
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(Order).options(joinedload(Order.company))
    cond = allowed_doc_cond(current_user, Order, Company)
    if cond is not None:
        q = q.filter(cond)
    if company_id:
        merged_ids = [str(r[0]) for r in db.query(Company.id).filter(Company.merged_into == company_id).all()]
        q = q.filter(Order.company_id.in_([company_id] + merged_ids))
    q = _apply_order_filters(q, agente, dal, al, valore_min, valore_max, categoria=categoria, prodotto=prodotto, org_cm=org_cm, agente_zona=agente_zona, tipo_doc=tipo_doc, sap_id=sap_id)
    if search:
        q = q.join(Company, Order.company_id == Company.id, isouter=True)
        q = q.filter(
            Order.sap_document_id.ilike(f"{search}%") |
            Company.ragione_sociale.ilike(f"%{search}%") |
            Company.sap_customer_id.ilike(f"%{search}%")
        )
    _SORT_COLS = {
        'data_ordine':    Order.data_ordine,
        'valore_totale':  Order.valore_totale,
        'sap_document_id': Order.sap_document_id,
        'org_cm':         Order.org_cm,
        'sap_creato_da':  Order.sap_creato_da,
    }
    if sort_by == 'agente':
        q = q.join(Company, Order.company_id == Company.id, isouter=True)
        sort_col = case((Order.org_cm == 'OC00', Company.agente_ilsa), else_=Company.agente_desco)
    else:
        sort_col = _SORT_COLS.get(sort_by, Order.data_ordine)
    order_expr = nullslast(sort_col.asc() if sort_dir == 'asc' else sort_col.desc())
    rows = q.add_columns(func.count().over().label('_total')).order_by(order_expr).offset(offset).limit(limit).all()
    total = rows[0]._total if rows else 0
    orders = [r[0] for r in rows]

    opp_ids = [o.opportunity_id for o in orders if o.opportunity_id]
    opps = db.query(Opportunity.id, Opportunity.sap_document_id).filter(Opportunity.id.in_(opp_ids)).all()
    opp_sap = {str(op.id): op.sap_document_id for op in opps}

    items = [
        {
            "id": str(o.id),
            "company_id": str(o.company_id),
            "ragione_sociale": o.company.ragione_sociale if o.company else None,
            "company_sap_customer_id": o.company.sap_customer_id if o.company else None,
            "sap_document_id": o.sap_document_id,
            "opportunity_id": str(o.opportunity_id) if o.opportunity_id else None,
            "opp_sap_document_id": opp_sap.get(str(o.opportunity_id)) if o.opportunity_id else None,
            "valore_totale": float(o.valore_totale) if o.valore_totale else 0,
            "data_ordine": o.data_ordine.isoformat() if o.data_ordine else None,
            "data_creazione_sap": o.data_creazione_sap.isoformat() if o.data_creazione_sap else None,
            "sap_creato_da": o.sap_creato_da,
            "agente": (o.company.agente_ilsa if o.org_cm == 'OC00' else o.company.agente_desco) if o.company else None,
            "org_cm": o.org_cm,
            "tipo_doc": o.tipo_doc,
            "nota": o.nota,
            "contribuisce_fatturato": o.contribuisce_fatturato,
        }
        for o in orders
    ]
    return {"total": total, "items": items}


@router.get("/{order_id}/line_items")
def get_order_line_items(order_id: str, db: Session = Depends(get_db)):
    items = db.query(LineItem).filter(LineItem.order_id == order_id, LineItem.document_type == 'order').all()
    return [
        {
            "id": str(i.id),
            "codice_sap": i.codice_sap,
            "descrizione_riga": i.descrizione_riga,
            "quantita": float(i.quantita) if i.quantita is not None else None,
            "unita_misura": i.unita_misura,
            "prezzo_unitario": float(i.prezzo_unitario) if i.prezzo_unitario is not None else None,
            "totale_riga": float(i.totale_riga) if i.totale_riga is not None else None,
            "categoria": i.categoria,
            "prodotto": i.prodotto,
            "nota": i.nota,
        }
        for i in items
    ]
