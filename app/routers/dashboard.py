from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.order import Order
from app.models.opportunity import Opportunity
from app.models.company import Company
from app.auth import get_current_user

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
    db: Session = Depends(get_db),
):
    months_back = 36 if tf == "3A" else 12
    since = _since(months_back)
    by_quarter = tf == "3A"
    period_fn = "quarter" if by_quarter else "month"

    if metrica == "fatturato":
        if data_dim == "cliente":
            date_col = Company.sap_created_at
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(Order.valore_totale), 0).label("valore"),
                )
                .join(Company, Order.company_id == Company.id)
                .filter(date_col >= since, date_col.isnot(None))
            )
        else:
            date_col = Order.data_ordine if data_dim == "ordine" else Order.data_creazione_sap
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(Order.valore_totale), 0).label("valore"),
                )
                .filter(date_col >= since, date_col.isnot(None))
            )

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
        db.query(func.coalesce(func.sum(Order.valore_totale), 0))
        .filter(Order.data_ordine >= dal, Order.data_ordine <= al)
        .scalar() or 0
    )

    nuovi_clienti = int(
        db.query(func.count(Company.id))
        .filter(Company.sap_created_at >= dal, Company.sap_created_at <= al)
        .scalar() or 0
    )

    base_opp = db.query(Opportunity).filter(
        Opportunity.data_creazione_sap >= dal,
        Opportunity.data_creazione_sap <= al,
    )
    vinte = base_opp.filter(Opportunity.stage == "Chiuso Vinto").count()
    perse = base_opp.filter(Opportunity.stage.in_(STAGE_PERSA)).count()
    chiuse = vinte + perse
    win_rate = round(vinte / chiuse * 100) if chiuse else None

    pipeline_valore = float(
        db.query(func.coalesce(func.sum(Opportunity.valore_totale), 0))
        .filter(
            Opportunity.stage == "Offerta Mandata",
            (Opportunity.data_scadenza >= today) | (Opportunity.data_scadenza == None),
        )
        .scalar() or 0
    )
    pipeline_count = int(
        db.query(func.count(Opportunity.id))
        .filter(
            Opportunity.stage == "Offerta Mandata",
            (Opportunity.data_scadenza >= today) | (Opportunity.data_scadenza == None),
        )
        .scalar() or 0
    )

    return {
        "fatturato": fatturato,
        "nuovi_clienti": nuovi_clienti,
        "win_rate": win_rate,
        "pipeline_valore": pipeline_valore,
        "pipeline_count": pipeline_count,
    }
