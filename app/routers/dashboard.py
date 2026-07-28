from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.database import get_db
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.opportunity import Opportunity
from app.models.company import Company
from app.auth import get_current_user
from app.services.opportunity_stats import opportunity_stats as _opp_stats, build_scaduta_attiva

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])

MESI_SHORT = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']


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
    db: Session = Depends(get_db),
):
    months_back = 36 if tf == "3A" else 12
    since = _since(months_back)
    by_quarter = tf == "3A"
    period_fn = "quarter" if by_quarter else "month"

    if metrica == "fatturato":
        if gr_merci:
            date_col = Order.data_ordine
            q = (
                db.query(
                    func.extract("year", date_col).label("anno"),
                    func.extract(period_fn, date_col).label("periodo"),
                    func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore"),
                )
                .join(OrderLineItem, OrderLineItem.order_id == Order.id)
                .filter(date_col >= since, date_col.isnot(None), OrderLineItem.gr_merci == gr_merci)
            )
        elif data_dim == "cliente":
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

    stats = _opp_stats(db, today, creazione_dal=dal, creazione_al=al)
    win_rate = stats["tasso_successo"]

    _, attiva_cond = build_scaduta_attiva(today)
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
    db: Session = Depends(get_db),
):
    # Fatturato per gr_merci dalle righe ordine nel periodo
    rows = (
        db.query(
            OrderLineItem.gr_merci.label("famiglia"),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
            func.count(OrderLineItem.id).label("righe"),
        )
        .join(Order, OrderLineItem.order_id == Order.id)
        .filter(
            Order.data_ordine >= dal,
            Order.data_ordine <= al,
            OrderLineItem.gr_merci.isnot(None),
            OrderLineItem.gr_merci != "",
        )
        .group_by(OrderLineItem.gr_merci)
        .order_by(func.sum(OrderLineItem.totale_riga).desc())
        .all()
    )

    totale = sum(float(r.fatturato) for r in rows)

    result = []
    for r in rows:
        fat = float(r.fatturato)
        # Sub-breakdown per codice_sap / descrizione
        sub_rows = (
            db.query(
                OrderLineItem.codice_sap,
                OrderLineItem.descrizione_riga,
                func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("fatturato"),
                func.count(OrderLineItem.id).label("righe"),
            )
            .join(Order, OrderLineItem.order_id == Order.id)
            .filter(
                Order.data_ordine >= dal,
                Order.data_ordine <= al,
                OrderLineItem.gr_merci == r.famiglia,
            )
            .group_by(OrderLineItem.codice_sap, OrderLineItem.descrizione_riga)
            .order_by(func.sum(OrderLineItem.totale_riga).desc())
            .limit(10)
            .all()
        )

        result.append({
            "famiglia": r.famiglia,
            "fatturato": fat,
            "righe": int(r.righe),
            "pct": round(fat / totale * 100) if totale else 0,
            "sub": [
                {
                    "cat": s.descrizione_riga or s.codice_sap or "—",
                    "codice": s.codice_sap,
                    "fatturato": float(s.fatturato),
                    "righe": int(s.righe),
                    "pct": round(float(s.fatturato) / fat * 100) if fat else 0,
                }
                for s in sub_rows
            ],
        })

    return result
