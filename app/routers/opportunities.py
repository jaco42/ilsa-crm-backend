from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, select, exists, nullslast
from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.line_item import LineItem
from app.models.order import Order
from app.models.company import Company
from app.auth import get_current_user, allowed_doc_cond
from app.services import funnel_service
router = APIRouter(prefix="/opportunities", tags=["opportunities"], dependencies=[Depends(get_current_user)])

TODAY = date.today

STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al, categoria=None, prodotto=None, org_cm=None, agente_zona=None, sap_id=None):
    if sap_id:
        sap_sub = select(Company.id).where(Company.sap_customer_id == sap_id)
        q = q.filter(Opportunity.company_id.in_(sap_sub))
    if agente:
        q = q.filter(Opportunity.sap_creato_da == agente)
    if agente_zona:
        from app.models.company import Company as CompanyModel
        from sqlalchemy import or_, and_
        ilsa_sub = select(CompanyModel.id).where(CompanyModel.agente_ilsa == agente_zona)
        desco_sub = select(CompanyModel.id).where(CompanyModel.agente_desco == agente_zona)
        q = q.filter(
            or_(
                and_(Opportunity.company_id.in_(ilsa_sub), Opportunity.org_cm == 'OC00'),
                and_(Opportunity.company_id.in_(desco_sub), Opportunity.org_cm == 'OC02'),
            )
        )
    if org_cm:
        q = q.filter(Opportunity.org_cm == org_cm)
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
    if categoria or prodotto:
        sub = select(LineItem.opportunity_id).where(
            LineItem.opportunity_id == Opportunity.id,
            LineItem.document_type == 'offer',
            LineItem.totale_riga > 0,
        )
        if categoria:
            sub = sub.where(LineItem.categoria == categoria)
        if prodotto:
            sub = sub.where(LineItem.prodotto == prodotto)
        q = q.filter(exists(sub))
    return q


@router.get("/stats")
def stats_opportunity(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    company_id: str = Query(None),
    agente: str = Query(None),
    agente_zona: str = Query(None),
    scadenza_dal: date = Query(None),
    scadenza_al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    creazione_dal: date = Query(None),
    creazione_al: date = Query(None),
    categoria: str = Query(None),
    prodotto: str = Query(None),
    org_cm: str = Query(None),
    sap_id: str = Query(None),
    kpi_dal: date = Query(None),
    kpi_al: date = Query(None),
):
    from datetime import timedelta
    today = date.today()
    un_mese_fa = today - timedelta(days=30)
    scaduta_cond = (Opportunity.stage == 'Offerta Mandata') & (
        (Opportunity.data_scadenza < today) |
        ((Opportunity.data_scadenza == None) & (Opportunity.data_creazione_sap != None) & (Opportunity.data_creazione_sap < un_mese_fa))
    )
    attiva_cond = (Opportunity.stage == 'Offerta Mandata') & (
        (Opportunity.data_scadenza >= today) |
        ((Opportunity.data_scadenza == None) & ((Opportunity.data_creazione_sap == None) | (Opportunity.data_creazione_sap >= un_mese_fa)))
    )

    q = db.query(Opportunity)
    cond = allowed_doc_cond(current_user, Opportunity, Company)
    if cond is not None:
        q = q.filter(cond)
    if company_id:
        merged_ids = [str(r[0]) for r in db.query(Company.id).filter(Company.merged_into == company_id).all()]
        q = q.filter(Opportunity.company_id.in_([company_id] + merged_ids))
    q = _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al, categoria=categoria, prodotto=prodotto, org_cm=org_cm, agente_zona=agente_zona, sap_id=sap_id)

    totale = q.count()

    # Pipeline (attive) — sempre senza filtro YTD: riflette lo stato attuale
    cf = Opportunity.contribuisce_fatturato == True
    attive, valore_pipeline_opp = q.with_entities(
        func.count(case((attiva_cond, 1))),
        func.coalesce(func.sum(case((attiva_cond & cf, Opportunity.valore_totale))), 0),
    ).one()

    # Vinte/perse/scadute — filtrate per periodo KPI (YTD di default dal frontend)
    q_ytd = q
    if kpi_dal:
        q_ytd = q_ytd.filter(Opportunity.data_creazione_sap >= kpi_dal)
    if kpi_al:
        q_ytd = q_ytd.filter(Opportunity.data_creazione_sap <= kpi_al)

    vinte, perse, scadute, valore_vinto_opp, valore_perso_opp = q_ytd.with_entities(
        func.count(case((Opportunity.stage == 'Chiuso Vinto', 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((scaduta_cond, 1))),
        func.coalesce(func.sum(case(((Opportunity.stage == 'Chiuso Vinto') & cf, Opportunity.valore_totale))), 0),
        func.coalesce(func.sum(case(((Opportunity.stage.in_(STAGE_PERSA) | scaduta_cond) & cf, Opportunity.valore_totale))), 0),
    ).one()

    if categoria or prodotto:
        # Con filtro prodotto i valori si calcolano sulle righe offerta, non sull'intera offerta
        li_conds = []
        if categoria:
            li_conds.append(LineItem.categoria == categoria)
        if prodotto:
            li_conds.append(LineItem.prodotto == prodotto)

        base_opp_conds = []
        if company_id:
            base_opp_conds.append(Opportunity.company_id == company_id)
        if agente:
            base_opp_conds.append(Opportunity.sap_creato_da == agente)
        if agente_zona:
            from sqlalchemy import or_, and_
            ilsa_sub = select(Company.id).where(Company.agente_ilsa == agente_zona)
            desco_sub = select(Company.id).where(Company.agente_desco == agente_zona)
            base_opp_conds.append(
                or_(
                    and_(Opportunity.company_id.in_(ilsa_sub), Opportunity.org_cm == 'OC00'),
                    and_(Opportunity.company_id.in_(desco_sub), Opportunity.org_cm == 'OC02'),
                )
            )
        if scadenza_dal:
            base_opp_conds.append(Opportunity.data_scadenza >= scadenza_dal)
        if scadenza_al:
            base_opp_conds.append(Opportunity.data_scadenza <= scadenza_al)
        if valore_min is not None:
            base_opp_conds.append(Opportunity.valore_totale >= valore_min)
        if valore_max is not None:
            base_opp_conds.append(Opportunity.valore_totale <= valore_max)
        if creazione_dal:
            base_opp_conds.append(Opportunity.data_creazione_sap >= creazione_dal)
        if creazione_al:
            base_opp_conds.append(Opportunity.data_creazione_sap <= creazione_al)

        ytd_opp_conds = base_opp_conds[:]
        if kpi_dal:
            ytd_opp_conds.append(Opportunity.data_creazione_sap >= kpi_dal)
        if kpi_al:
            ytd_opp_conds.append(Opportunity.data_creazione_sap <= kpi_al)

        def li_sum(stage_cond, opp_conds):
            return float(
                db.query(func.coalesce(func.sum(LineItem.totale_riga), 0))
                .join(Opportunity, LineItem.opportunity_id == Opportunity.id)
                .filter(LineItem.document_type == 'offer', stage_cond, *li_conds, *opp_conds)
                .scalar() or 0
            )

        valore_vinto = li_sum(Opportunity.stage == 'Chiuso Vinto', ytd_opp_conds)
        valore_perso = li_sum(Opportunity.stage.in_(STAGE_PERSA) | scaduta_cond, ytd_opp_conds)
        valore_pipeline = li_sum(attiva_cond, base_opp_conds)
    else:
        valore_vinto = float(valore_vinto_opp)
        valore_perso = float(valore_perso_opp)
        valore_pipeline = float(valore_pipeline_opp)

    chiuse = vinte + perse + scadute
    return {
        "totale": totale,
        "vinte": vinte,
        "perse": perse,
        "scadute": scadute,
        "attive": attive,
        "chiuse": chiuse,
        "tasso_successo": round(vinte / chiuse * 100) if chiuse else None,
        "valore_pipeline": valore_pipeline,
        "valore_vinto": valore_vinto,
        "valore_perso": valore_perso,
    }


@router.get("/")
def lista_opportunity(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    company_id: str = Query(None),
    agente: str = Query(None),
    agente_zona: str = Query(None),
    stato: str = Query(None),
    scadenza_dal: date = Query(None),
    scadenza_al: date = Query(None),
    valore_min: float = Query(None),
    valore_max: float = Query(None),
    creazione_dal: date = Query(None),
    creazione_al: date = Query(None),
    categoria: str = Query(None),
    prodotto: str = Query(None),
    org_cm: str = Query(None),
    sap_id: str = Query(None),
    search: str = Query(None),
    sort_by: str = Query('data_creazione_sap'),
    sort_dir: str = Query('desc'),
    limit: int = Query(100),
    offset: int = Query(0),
):
    today = date.today()
    company_joined = False
    q = db.query(Opportunity).options(joinedload(Opportunity.company))
    cond = allowed_doc_cond(current_user, Opportunity, Company)
    if cond is not None:
        q = q.filter(cond)
    if company_id:
        merged_ids = [str(r[0]) for r in db.query(Company.id).filter(Company.merged_into == company_id).all()]
        q = q.filter(Opportunity.company_id.in_([company_id] + merged_ids))
    q = _apply_opp_filters(q, agente, scadenza_dal, scadenza_al, valore_min, valore_max, creazione_dal, creazione_al, categoria=categoria, prodotto=prodotto, org_cm=org_cm, agente_zona=agente_zona, sap_id=sap_id)
    if search:
        q = q.join(Company, Opportunity.company_id == Company.id, isouter=True)
        company_joined = True
        q = q.filter(
            Opportunity.sap_document_id.ilike(f"{search}%") |
            Company.ragione_sociale.ilike(f"%{search}%") |
            Company.sap_customer_id.ilike(f"%{search}%")
        )
    if stato == 'vinta':
        q = q.filter(Opportunity.stage == 'Chiuso Vinto')
    elif stato == 'persa':
        q = q.filter(Opportunity.stage.in_(STAGE_PERSA))
    elif stato == 'scaduta':
        from datetime import timedelta
        un_mese_fa = today - timedelta(days=30)
        q = q.filter(
            Opportunity.stage == 'Offerta Mandata',
            (Opportunity.data_scadenza < today) |
            ((Opportunity.data_scadenza == None) & (Opportunity.data_creazione_sap != None) & (Opportunity.data_creazione_sap < un_mese_fa))
        )
    elif stato == 'mandata':
        from datetime import timedelta
        un_mese_fa = today - timedelta(days=30)
        q = q.filter(
            Opportunity.stage == 'Offerta Mandata',
            (Opportunity.data_scadenza >= today) |
            ((Opportunity.data_scadenza == None) & ((Opportunity.data_creazione_sap == None) | (Opportunity.data_creazione_sap >= un_mese_fa)))
        )
    # Ordinamento server-side
    _SORT_COLS = {
        'data_creazione_sap': Opportunity.data_creazione_sap,
        'data_scadenza':      Opportunity.data_scadenza,
        'valore_totale':      Opportunity.valore_totale,
        'sap_document_id':    Opportunity.sap_document_id,
        'sap_creato_da':      Opportunity.sap_creato_da,
        'org_cm':             Opportunity.org_cm,
    }
    if sort_by == 'ragione_sociale':
        if not company_joined:
            q = q.join(Company, Opportunity.company_id == Company.id, isouter=True)
        sort_col = Company.ragione_sociale
    elif sort_by == 'agente':
        if not company_joined:
            q = q.join(Company, Opportunity.company_id == Company.id, isouter=True)
        sort_col = case((Opportunity.org_cm == 'OC00', Company.agente_ilsa), else_=Company.agente_desco)
    else:
        sort_col = _SORT_COLS.get(sort_by, Opportunity.data_creazione_sap)
    order_expr = nullslast(sort_col.asc() if sort_dir == 'asc' else sort_col.desc())
    rows = q.add_columns(func.count().over().label('_total')).order_by(order_expr).offset(offset).limit(limit).all()
    total = rows[0]._total if rows else 0
    items = [r[0] for r in rows]

    opp_ids = [opp.id for opp in items]
    orders = db.query(Order.opportunity_id, Order.id, Order.sap_document_id).filter(
        Order.opportunity_id.in_(opp_ids)
    ).all()
    order_by_opp = {str(o.opportunity_id): {"order_id": str(o.id), "order_sap_document_id": o.sap_document_id} for o in orders}

    serialized = [
        {
            **{c.name: getattr(opp, c.name) for c in Opportunity.__table__.columns},
            "ragione_sociale": opp.company.ragione_sociale if opp.company else None,
            "company_sap_customer_id": opp.company.sap_customer_id if opp.company else None,
            "order_id": order_by_opp.get(str(opp.id), {}).get("order_id"),
            "order_sap_document_id": order_by_opp.get(str(opp.id), {}).get("order_sap_document_id"),
            "agente": (opp.company.agente_ilsa if opp.org_cm == 'OC00' else opp.company.agente_desco) if opp.company else None,
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
    items = db.query(LineItem).filter(LineItem.opportunity_id == opportunity_id, LineItem.document_type == 'offer').all()
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
        }
        for i in items
    ]


@router.patch("/{opportunity_id}/stage")
def cambia_stage(opportunity_id: str, data: dict, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity non trovata")
    return funnel_service.cambia_stage(db, opp, data.get("stage"), data.get("loss_reason"))
