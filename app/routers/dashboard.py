from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.database import get_db
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.offer_line_item import OfferLineItem
from app.models.opportunity import Opportunity
from app.models.company import Company
from app.auth import get_current_user, allowed_company_ids
from datetime import timedelta

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])

MESI_SHORT = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']
STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def _since(months_back: int) -> date:
    today = date.today()
    total = (today.year * 12 + today.month - 1) - months_back
    return date(total // 12, total % 12 + 1, 1)


def _agente_subq(agente, db):
    from sqlalchemy import or_
    from app.models.company import Company
    if not agente:
        return None
    return db.query(Company.id).filter(
        or_(Company.agente_ilsa == agente, Company.agente_desco == agente)
    ).subquery()


@router.get("/chart")
def dashboard_chart(
    dal: date = Query(None),
    al: date = Query(None),
    metrica: str = Query("fatturato"),
    data_dim: str = Query("ordine"),
    categoria: str = Query(None),
    prodotto: str = Query(None),
    company_id: str = Query(None),
    org_cm: str = Query(None),
    agente: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    today = date.today()
    since = dal or _since(12)
    until = al or today
    months = (until.year - since.year) * 12 + (until.month - since.month)
    by_year = months > 48
    by_quarter = not by_year and months > 13
    period_fn = "year" if by_year else ("quarter" if by_quarter else "month")

    allowed = allowed_company_ids(current_user, db)
    agente_ids = _agente_subq(agente, db)

    def date_filters(col):
        return [col >= since, col <= until, col.isnot(None)]

    if metrica == "fatturato":
        if categoria or prodotto:
            date_col = Order.data_ordine
            li_filters = date_filters(date_col)
            li_filters.append(Order.contribuisce_fatturato == True)
            li_filters.append(OrderLineItem.categoria != 'Trasporti')
            if categoria:
                li_filters.append(OrderLineItem.categoria == categoria)
            if prodotto:
                li_filters.append(OrderLineItem.prodotto == prodotto)
            if allowed is not None:
                li_filters.append(Order.company_id.in_(allowed))
            if agente_ids is not None:
                li_filters.append(Order.company_id.in_(agente_ids))
            if company_id:
                li_filters.append(Order.company_id == company_id)
            if org_cm:
                li_filters.append(Order.org_cm == org_cm)
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore"),
                )
                .join(OrderLineItem, OrderLineItem.order_id == Order.id)
                .filter(*li_filters)
            )
        elif data_dim == "cliente":
            date_col = Company.sap_created_at
            cliente_filters = date_filters(date_col)
            cliente_filters.append(Order.contribuisce_fatturato == True)
            cliente_filters.append(OrderLineItem.categoria != 'Trasporti')
            if allowed is not None:
                cliente_filters.append(Company.id.in_(allowed))
            if agente_ids is not None:
                cliente_filters.append(Company.id.in_(agente_ids))
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore"),
                )
                .join(Company, Order.company_id == Company.id)
                .join(OrderLineItem, OrderLineItem.order_id == Order.id)
                .filter(*cliente_filters)
            )
        else:
            date_col = Order.data_ordine if data_dim == "ordine" else Order.data_creazione_sap
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore"),
                )
                .join(OrderLineItem, OrderLineItem.order_id == Order.id)
                .filter(*date_filters(date_col), Order.contribuisce_fatturato == True, OrderLineItem.categoria != 'Trasporti')
            )
            if allowed is not None:
                q = q.filter(Order.company_id.in_(allowed))
            if agente_ids is not None:
                q = q.filter(Order.company_id.in_(agente_ids))
            if company_id:
                q = q.filter(Order.company_id == company_id)
            if org_cm:
                q = q.filter(Order.org_cm == org_cm)

    elif metrica == "offerte":
        date_col = Opportunity.data_creazione_sap
        q = (
            db.query(
                func.extract("year", date_col).label("anno"),
                func.extract(period_fn, date_col).label("periodo"),
                func.count(Opportunity.id).label("valore"),
            )
            .filter(*date_filters(date_col))
        )
        if allowed is not None:
            q = q.filter(Opportunity.company_id.in_(allowed))
        if agente_ids is not None:
            q = q.filter(Opportunity.company_id.in_(agente_ids))
        if company_id:
            q = q.filter(Opportunity.company_id == company_id)
        if org_cm:
            q = q.filter(Opportunity.org_cm == org_cm)

    elif metrica == "nuovi_clienti":
        date_col = Company.sap_created_at
        q = (
            db.query(
                func.extract("year", date_col).label("anno"),
                func.extract(period_fn, date_col).label("periodo"),
                func.count(func.distinct(Company.id)).label("valore"),
            )
            .join(Order, Order.company_id == Company.id)
            .filter(*date_filters(date_col))
        )
        if allowed is not None:
            q = q.filter(Company.id.in_(allowed))
        if agente_ids is not None:
            q = q.filter(Company.id.in_(agente_ids))

    else:
        return []

    rows = q.group_by("anno", "periodo").order_by("anno", "periodo").all()

    result = []
    for r in rows:
        anno = int(r.anno)
        p = int(r.periodo)
        if by_year:
            label = str(anno)
        elif by_quarter:
            label = f"Q{p}'{str(anno)[2:]}"
        else:
            label = f"{MESI_SHORT[p - 1]}'{str(anno)[2:]}"
        result.append({"label": label, "valore": float(r.valore or 0)})

    return result


@router.get("/kpi")
def dashboard_kpi(
    dal: date = Query(...),
    al: date = Query(...),
    agente: str = Query(None),
    org_cm: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    today = date.today()
    allowed = allowed_company_ids(current_user, db)
    agente_ids = _agente_subq(agente, db)

    fat_q = (
        db.query(func.coalesce(func.sum(OrderLineItem.totale_riga), 0))
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(
            Order.data_ordine >= dal, Order.data_ordine <= al,
            Order.contribuisce_fatturato == True,
            OrderLineItem.categoria != 'Trasporti',
        )
    )
    if allowed is not None:
        fat_q = fat_q.filter(Order.company_id.in_(allowed))
    if agente_ids is not None:
        fat_q = fat_q.filter(Order.company_id.in_(agente_ids))
    if org_cm:
        fat_q = fat_q.filter(Order.org_cm == org_cm)
    fatturato = float(fat_q.scalar() or 0)

    nc_q = (
        db.query(func.count(func.distinct(Company.id)))
        .join(Order, Order.company_id == Company.id)
        .filter(Company.sap_created_at >= dal, Company.sap_created_at <= al)
    )
    if allowed is not None:
        nc_q = nc_q.filter(Company.id.in_(allowed))
    if agente_ids is not None:
        nc_q = nc_q.filter(Company.id.in_(agente_ids))
    if org_cm:
        nc_q = nc_q.filter(Order.org_cm == org_cm)
    nuovi_clienti = int(nc_q.scalar() or 0)

    un_mese_fa = today - timedelta(days=30)
    scaduta_cond = (Opportunity.stage == "Offerta Mandata") & (
        (Opportunity.data_scadenza < today) |
        ((Opportunity.data_scadenza == None) & (Opportunity.data_creazione_sap != None) & (Opportunity.data_creazione_sap < un_mese_fa))
    )
    attiva_cond = (Opportunity.stage == "Offerta Mandata") & (
        (Opportunity.data_scadenza >= today) |
        ((Opportunity.data_scadenza == None) & ((Opportunity.data_creazione_sap == None) | (Opportunity.data_creazione_sap >= un_mese_fa)))
    )

    opp_q = db.query(
        func.count(case((Opportunity.stage == "Chiuso Vinto", 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((scaduta_cond, 1))),
    ).filter(
        Opportunity.data_creazione_sap >= dal,
        Opportunity.data_creazione_sap <= al,
    )
    if allowed is not None:
        opp_q = opp_q.filter(Opportunity.company_id.in_(allowed))
    if agente_ids is not None:
        opp_q = opp_q.filter(Opportunity.company_id.in_(agente_ids))
    if org_cm:
        opp_q = opp_q.filter(Opportunity.org_cm == org_cm)
    vinte, perse, scadute = opp_q.one()
    chiuse = vinte + perse + scadute
    win_rate = round(vinte / chiuse * 100) if chiuse else None

    pipe_q = db.query(func.coalesce(func.sum(Opportunity.valore_totale), 0)).filter(attiva_cond)
    pipe_count_q = db.query(func.count(Opportunity.id)).filter(attiva_cond)
    if allowed is not None:
        pipe_q = pipe_q.filter(Opportunity.company_id.in_(allowed))
        pipe_count_q = pipe_count_q.filter(Opportunity.company_id.in_(allowed))
    if agente_ids is not None:
        pipe_q = pipe_q.filter(Opportunity.company_id.in_(agente_ids))
        pipe_count_q = pipe_count_q.filter(Opportunity.company_id.in_(agente_ids))
    if org_cm:
        pipe_q = pipe_q.filter(Opportunity.org_cm == org_cm)
        pipe_count_q = pipe_count_q.filter(Opportunity.org_cm == org_cm)
    pipeline_valore = float(pipe_q.scalar() or 0)
    pipeline_count = int(pipe_count_q.scalar() or 0)

    return {
        "fatturato": fatturato,
        "nuovi_clienti": nuovi_clienti,
        "win_rate": win_rate,
        "pipeline_valore": pipeline_valore,
        "pipeline_count": pipeline_count,
    }


@router.get("/per-famiglia")
def dashboard_per_famiglia(
    dal: date = Query(...),
    al: date = Query(...),
    company_id: str = Query(None),
    agente: str = Query(None),
    org_cm: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    allowed = allowed_company_ids(current_user, db)
    agente_ids = _agente_subq(agente, db)
    base_ord = [
        Order.data_ordine >= dal, Order.data_ordine <= al,
        Order.contribuisce_fatturato == True,
        OrderLineItem.categoria.isnot(None), OrderLineItem.categoria != "",
        OrderLineItem.categoria != "Trasporti",
    ]
    base_opp = [Opportunity.data_creazione_sap >= dal, Opportunity.data_creazione_sap <= al,
                OfferLineItem.categoria.isnot(None), OfferLineItem.categoria != ""]
    if allowed is not None:
        base_ord.append(Order.company_id.in_(allowed))
        base_opp.append(Opportunity.company_id.in_(allowed))
    if agente_ids is not None:
        base_ord.append(Order.company_id.in_(agente_ids))
        base_opp.append(Opportunity.company_id.in_(agente_ids))
    if company_id:
        base_ord.append(Order.company_id == company_id)
        base_opp.append(Opportunity.company_id == company_id)
    if org_cm:
        base_ord.append(Order.org_cm == org_cm)
        base_opp.append(Opportunity.org_cm == org_cm)

    fam_rows = (
        db.query(
            OrderLineItem.categoria.label("famiglia"),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
            func.count(func.distinct(Order.id)).label("ordini"),
        )
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(*base_ord)
        .group_by(OrderLineItem.categoria)
        .order_by(func.sum(OrderLineItem.totale_riga).desc())
        .all()
    )

    cat_rows = (
        db.query(
            OrderLineItem.categoria.label("famiglia"),
            OrderLineItem.prodotto.label("prodotto"),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
            func.count(func.distinct(Order.id)).label("ordini"),
        )
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(*base_ord, OrderLineItem.prodotto.isnot(None), OrderLineItem.prodotto != "")
        .group_by(OrderLineItem.categoria, OrderLineItem.prodotto)
        .order_by(OrderLineItem.categoria, func.sum(OrderLineItem.totale_riga).desc())
        .all()
    )

    fam_opp_rows = (
        db.query(
            OfferLineItem.categoria.label("famiglia"),
            func.count(func.distinct(Opportunity.id)).label("offerte"),
        )
        .join(Opportunity, OfferLineItem.opportunity_id == Opportunity.id)
        .filter(*base_opp)
        .group_by(OfferLineItem.categoria)
        .all()
    )

    cat_opp_rows = (
        db.query(
            OfferLineItem.categoria.label("famiglia"),
            OfferLineItem.prodotto.label("prodotto"),
            func.count(func.distinct(Opportunity.id)).label("offerte"),
        )
        .join(Opportunity, OfferLineItem.opportunity_id == Opportunity.id)
        .filter(*base_opp, OfferLineItem.prodotto.isnot(None), OfferLineItem.prodotto != "")
        .group_by(OfferLineItem.categoria, OfferLineItem.prodotto)
        .all()
    )

    offerte_fam = {r.famiglia: int(r.offerte) for r in fam_opp_rows}
    offerte_cat = {(r.famiglia, r.prodotto): int(r.offerte) for r in cat_opp_rows}
    cats_by_fam: dict = {}
    for r in cat_rows:
        cats_by_fam.setdefault(r.famiglia, []).append(r)

    # Tutte le famiglie note (senza filtri data/agente/org) per mostrare anche quelle a 0
    all_famiglie = [
        r[0] for r in db.query(OrderLineItem.categoria).filter(
            OrderLineItem.categoria.isnot(None),
            OrderLineItem.categoria != "",
            OrderLineItem.categoria != "Trasporti",
        ).distinct().all()
    ]

    fam_dict = {r.famiglia: r for r in fam_rows}
    totale = sum(float(r.fatturato) for r in fam_rows)

    # Trasporti: query separata, stessi filtri di accesso ma categoria == 'Trasporti'
    trasp_base = [Order.data_ordine >= dal, Order.data_ordine <= al, Order.contribuisce_fatturato == True, OrderLineItem.categoria == 'Trasporti']
    if allowed is not None:
        trasp_base.append(Order.company_id.in_(allowed))
    if agente_ids is not None:
        trasp_base.append(Order.company_id.in_(agente_ids))
    if company_id:
        trasp_base.append(Order.company_id == company_id)
    if org_cm:
        trasp_base.append(Order.org_cm == org_cm)

    trasp_row = (
        db.query(
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
            func.count(func.distinct(Order.id)).label("ordini"),
        )
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(*trasp_base)
        .one()
    )

    def _build_row(famiglia: str):
        r = fam_dict.get(famiglia)
        fat = max(0.0, float(r.fatturato)) if r else 0.0
        ordini = int(r.ordini) if r else 0
        return {
            "famiglia": famiglia,
            "fatturato": fat,
            "ordini": ordini,
            "offerte": offerte_fam.get(famiglia, 0),
            "pct": round(fat / totale * 100) if totale else 0,
            "sub": [
                {
                    "prodotto": s.prodotto or "—",
                    "fatturato": float(s.fatturato),
                    "ordini": int(s.ordini),
                    "offerte": offerte_cat.get((famiglia, s.prodotto), 0),
                    "pct": round(float(s.fatturato) / totale * 100) if totale else 0,
                }
                for s in cats_by_fam.get(famiglia, [])
            ],
        }

    result = sorted(
        [_build_row(f) for f in all_famiglie],
        key=lambda x: x["fatturato"],
        reverse=True,
    )

    result.append({
        "famiglia": "Trasporti",
        "fatturato": float(trasp_row.fatturato),
        "ordini": int(trasp_row.ordini),
        "offerte": offerte_fam.get("Trasporti", 0),
        "pct": None,
        "non_contribuisce": True,
        "sub": [],
    })

    return result
