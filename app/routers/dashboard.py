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
from app.auth import get_current_user
from datetime import timedelta

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])

MESI_SHORT = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']
STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def _since(months_back: int) -> date:
    today = date.today()
    total = (today.year * 12 + today.month - 1) - months_back
    return date(total // 12, total % 12 + 1, 1)


@router.get("/chart")
def dashboard_chart(
    tf: str = Query("1A"),
    metrica: str = Query("fatturato"),
    data_dim: str = Query("ordine"),  # ordine | offerta | cliente (solo per fatturato)
    gr_merci: str = Query(None),      # filtro per famiglia (usa OrderLineItem.gr_merci)
    categoria: str = Query(None),     # filtro per categoria L2 (usa OrderLineItem.categoria)
    company_id: str = Query(None),    # filtra per singola azienda
    db: Session = Depends(get_db),
):
    months_back = 36 if tf == "3A" else 12
    since = _since(months_back)
    by_quarter = tf == "3A"
    period_fn = "quarter" if by_quarter else "month"

    if metrica == "fatturato":
        if gr_merci or categoria:
            date_col = Order.data_ordine
            li_filters = [date_col >= since, date_col.isnot(None)]
            if gr_merci:
                li_filters.append(OrderLineItem.gr_merci == gr_merci)
            if categoria:
                li_filters.append(OrderLineItem.categoria == categoria)
            if company_id:
                li_filters.append(Order.company_id == company_id)
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
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore"),
                )
                .join(Company, Order.company_id == Company.id)
                .join(OrderLineItem, OrderLineItem.order_id == Order.id)
                .filter(date_col >= since, date_col.isnot(None))
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
                .filter(date_col >= since, date_col.isnot(None))
            )
            if company_id:
                q = q.filter(Order.company_id == company_id)

    elif metrica == "offerte":
        date_col = Opportunity.data_creazione_sap
        q = (
            db.query(
                func.extract("year", date_col).label("anno"),
                func.extract(period_fn, date_col).label("periodo"),
                func.count(Opportunity.id).label("valore"),
            )
            .filter(date_col >= since, date_col.isnot(None))
        )
        if company_id:
            q = q.filter(Opportunity.company_id == company_id)

    elif metrica == "nuovi_clienti":
        date_col = Company.sap_created_at
        q = (
            db.query(
                func.extract("year", date_col).label("anno"),
                func.extract(period_fn, date_col).label("periodo"),
                func.count(Company.id).label("valore"),
            )
            .filter(date_col >= since, date_col.isnot(None))
        )

    else:
        return []

    rows = q.group_by("anno", "periodo").order_by("anno", "periodo").all()

    result = []
    for r in rows:
        anno = int(r.anno)
        p = int(r.periodo)
        label = f"Q{p}'{str(anno)[2:]}" if by_quarter else f"{MESI_SHORT[p - 1]}'{str(anno)[2:]}"
        result.append({"label": label, "valore": float(r.valore or 0)})

    return result


@router.get("/kpi")
def dashboard_kpi(
    dal: date = Query(...),
    al: date = Query(...),
    db: Session = Depends(get_db),
):
    today = date.today()

    fatturato = float(
        db.query(func.coalesce(func.sum(OrderLineItem.totale_riga), 0))
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(Order.data_ordine >= dal, Order.data_ordine <= al)
        .scalar() or 0
    )

    nuovi_clienti = int(
        db.query(func.count(Company.id))
        .filter(Company.sap_created_at >= dal, Company.sap_created_at <= al)
        .scalar() or 0
    )

    un_mese_fa = today - timedelta(days=30)
    scaduta_cond = (Opportunity.stage == "Offerta Mandata") & (
        (Opportunity.data_scadenza < today) |
        ((Opportunity.data_scadenza == None) & (Opportunity.data_creazione_sap != None) & (Opportunity.data_creazione_sap < un_mese_fa))
    )
    attiva_cond = (Opportunity.stage == "Offerta Mandata") & (
        (Opportunity.data_scadenza >= today) |
        ((Opportunity.data_scadenza == None) & ((Opportunity.data_creazione_sap == None) | (Opportunity.data_creazione_sap >= un_mese_fa)))
    )

    vinte, perse, scadute = db.query(
        func.count(case((Opportunity.stage == "Chiuso Vinto", 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((scaduta_cond, 1))),
    ).filter(
        Opportunity.data_creazione_sap >= dal,
        Opportunity.data_creazione_sap <= al,
    ).one()
    chiuse = vinte + perse + scadute
    win_rate = round(vinte / chiuse * 100) if chiuse else None

    pipeline_valore = float(
        db.query(func.coalesce(func.sum(Opportunity.valore_totale), 0))
        .filter(attiva_cond)
        .scalar() or 0
    )
    pipeline_count = int(
        db.query(func.count(Opportunity.id))
        .filter(attiva_cond)
        .scalar() or 0
    )

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
    db: Session = Depends(get_db),
):
    ord_filters = [
        Order.data_ordine >= dal,
        Order.data_ordine <= al,
        OrderLineItem.gr_merci.isnot(None),
        OrderLineItem.gr_merci != "",
    ]
    if company_id:
        ord_filters.append(Order.company_id == company_id)

    rows = (
        db.query(
            OrderLineItem.gr_merci.label("famiglia"),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
            func.count(func.distinct(Order.id)).label("ordini"),
        )
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(*ord_filters)
        .group_by(OrderLineItem.gr_merci)
        .order_by(func.sum(OrderLineItem.totale_riga).desc())
        .all()
    )

    opp_filters = [
        Opportunity.data_creazione_sap >= dal,
        Opportunity.data_creazione_sap <= al,
        OfferLineItem.gr_merci.isnot(None),
        OfferLineItem.gr_merci != "",
    ]
    if company_id:
        opp_filters.append(Opportunity.company_id == company_id)

    offerte_rows = (
        db.query(
            OfferLineItem.gr_merci.label("famiglia"),
            func.count(func.distinct(Opportunity.id)).label("offerte"),
        )
        .join(Opportunity, OfferLineItem.opportunity_id == Opportunity.id)
        .filter(*opp_filters)
        .group_by(OfferLineItem.gr_merci)
        .all()
    )
    offerte_map = {r.famiglia: int(r.offerte) for r in offerte_rows}

    totale = sum(float(r.fatturato) for r in rows)

    result = []
    for r in rows:
        fat = float(r.fatturato)
        famiglia = r.famiglia

        sub_filters = [
            Order.data_ordine >= dal,
            Order.data_ordine <= al,
            OrderLineItem.gr_merci == famiglia,
            OrderLineItem.categoria.isnot(None),
            OrderLineItem.categoria != "",
        ]
        if company_id:
            sub_filters.append(Order.company_id == company_id)

        sub_rows = (
            db.query(
                OrderLineItem.categoria.label("categoria"),
                func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
                func.count(func.distinct(Order.id)).label("ordini"),
            )
            .join(Order, OrderLineItem.order_id == Order.id)
            .filter(*sub_filters)
            .group_by(OrderLineItem.categoria)
            .order_by(func.sum(OrderLineItem.totale_riga).desc())
            .all()
        )

        sub_opp_filters = [
            Opportunity.data_creazione_sap >= dal,
            Opportunity.data_creazione_sap <= al,
            OfferLineItem.gr_merci == famiglia,
            OfferLineItem.categoria.isnot(None),
            OfferLineItem.categoria != "",
        ]
        if company_id:
            sub_opp_filters.append(Opportunity.company_id == company_id)

        sub_offerte_rows = (
            db.query(
                OfferLineItem.categoria.label("categoria"),
                func.count(func.distinct(Opportunity.id)).label("offerte"),
            )
            .join(Opportunity, OfferLineItem.opportunity_id == Opportunity.id)
            .filter(*sub_opp_filters)
            .group_by(OfferLineItem.categoria)
            .all()
        )
        sub_offerte_map = {row.categoria: int(row.offerte) for row in sub_offerte_rows}

        result.append({
            "famiglia": famiglia,
            "fatturato": fat,
            "ordini": int(r.ordini),
            "offerte": offerte_map.get(famiglia, 0),
            "pct": round(fat / totale * 100) if totale else 0,
            "sub": [
                {
                    "categoria": s.categoria or "—",
                    "fatturato": float(s.fatturato),
                    "ordini": int(s.ordini),
                    "offerte": sub_offerte_map.get(s.categoria, 0),
                    "pct": round(float(s.fatturato) / totale * 100) if totale else 0,
                }
                for s in sub_rows
            ],
        })

    return result
