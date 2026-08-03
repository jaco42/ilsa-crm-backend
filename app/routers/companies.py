from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import func, case, select
from app.database import get_db
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.auth import get_current_user
from app.services.opportunity_stats import build_scaduta_attiva
from app.config import settings

router = APIRouter(prefix="/companies", tags=["companies"], dependencies=[Depends(get_current_user)])
service_router = APIRouter(prefix="/companies", tags=["companies"])


def _status_dinamico(c: Company) -> str:
    if c.status and c.status.value == "cliente":
        return "cliente"
    if c.sap_customer_id:
        return "potenziale"
    return "lead"


@router.get("/")
def lista_aziende(
    db: Session = Depends(get_db),
    search: str = Query(None),
    status: str = Query(None),
    paese: str = Query(None),
    partita_iva: str = Query(None),
    provincia: str = Query(None),
    storico_contatti: str = Query(None),
    tipo_attivita: str = Query(None),
    agente: str = Query(None),
    sort_by: str = Query("ragione_sociale"),
    sort_dir: str = Query("asc"),
    limit: int = Query(100),
    offset: int = Query(0),
    date_from: date = Query(None),
    date_to: date = Query(None),
    # Checkbox filters
    con_offerte_attive: bool = Query(None),
    con_offerte_scadute: bool = Query(None),
    con_offerte_vinte: bool = Query(None),
    con_offerte_perse: bool = Query(None),
    min_valore_offerte_attive: float = Query(None),
    max_valore_offerte_attive: float = Query(None),
    min_valore_offerte_scadute: float = Query(None),
    max_valore_offerte_scadute: float = Query(None),
    min_ordini: int = Query(None),
    max_ordini: int = Query(None),
    min_valore: float = Query(None),
    max_valore: float = Query(None),
    min_offerte_totali: int = Query(None),
    max_offerte_totali: int = Query(None),
):
    today = date.today()
    scaduta_cond, attiva_cond = build_scaduta_attiva(today)
    opp_q = db.query(
        Opportunity.company_id,
        func.count(case((attiva_cond, 1))).label("offerte_attive"),
        func.coalesce(func.sum(case((attiva_cond, Opportunity.valore_totale))), 0).label("valore_offerte_attive"),
        func.count(case((scaduta_cond, 1))).label("offerte_scadute"),
        func.coalesce(func.sum(case((scaduta_cond, Opportunity.valore_totale))), 0).label("valore_offerte_scadute"),
        func.count(case((Opportunity.stage == "Chiuso Vinto", 1))).label("offerte_vinte"),
        func.count(case((Opportunity.stage == "Chiuso Perso", 1))).label("offerte_perse"),
    )
    if date_from:
        opp_q = opp_q.filter(Opportunity.data_creazione_sap >= date_from)
    if date_to:
        opp_q = opp_q.filter(Opportunity.data_creazione_sap <= date_to)
    opp_stats = opp_q.group_by(Opportunity.company_id).subquery()

    order_q = (
        db.query(
            Order.company_id,
            func.count(func.distinct(Order.id)).label("ordini_totali"),
            func.coalesce(func.sum(OrderLineItem.totale_riga), 0).label("valore_ordini"),
        )
        .join(OrderLineItem, OrderLineItem.order_id == Order.id)
    )
    if date_from:
        order_q = order_q.filter(Order.data_ordine >= date_from)
    if date_to:
        order_q = order_q.filter(Order.data_ordine <= date_to)
    order_stats = order_q.group_by(Order.company_id).subquery()

    # Ultima interazione SAP = max(data_creazione_sap) tra offerte e ordini
    last_opp = (
        db.query(Opportunity.company_id, func.max(Opportunity.data_creazione_sap).label("last_date"))
        .group_by(Opportunity.company_id)
        .subquery()
    )
    last_order = (
        db.query(Order.company_id, func.max(Order.data_creazione_sap).label("last_date"))
        .group_by(Order.company_id)
        .subquery()
    )

    q = (
        db.query(
            Company,
            func.coalesce(opp_stats.c.offerte_attive, 0).label("offerte_attive"),
            func.coalesce(opp_stats.c.valore_offerte_attive, 0).label("valore_offerte_attive"),
            func.coalesce(opp_stats.c.offerte_scadute, 0).label("offerte_scadute"),
            func.coalesce(opp_stats.c.valore_offerte_scadute, 0).label("valore_offerte_scadute"),
            func.coalesce(opp_stats.c.offerte_vinte, 0).label("offerte_vinte"),
            func.coalesce(opp_stats.c.offerte_perse, 0).label("offerte_perse"),
            func.coalesce(order_stats.c.ordini_totali, 0).label("ordini_totali"),
            func.coalesce(order_stats.c.valore_ordini, 0).label("valore_ordini"),
            func.greatest(last_opp.c.last_date, last_order.c.last_date).label("ultima_interazione_sap"),
        )
        .outerjoin(opp_stats, Company.id == opp_stats.c.company_id)
        .outerjoin(order_stats, Company.id == order_stats.c.company_id)
        .outerjoin(last_opp, Company.id == last_opp.c.company_id)
        .outerjoin(last_order, Company.id == last_order.c.company_id)
    )

    if search:
        q = q.filter(Company.ragione_sociale.ilike(f"%{search}%"))
    if partita_iva:
        q = q.filter(Company.partita_iva == partita_iva.strip())
    if status:
        if status == "lead":
            q = q.filter(Company.sap_customer_id == None, Company.status != "cliente")
        elif status in ("prospect", "potenziale"):
            q = q.filter(Company.sap_customer_id != None, Company.status != "cliente")
        else:
            q = q.filter(Company.status == status)
    if paese:
        from sqlalchemy import or_, and_
        paesi = [p.strip().upper() for p in paese.split(",") if p.strip()]
        if provincia:
            # provincia si applica solo alle aziende IT; gli altri paesi passano senza vincolo
            conditions = []
            for p in paesi:
                if p == 'IT':
                    conditions.append(and_(Company.paese.ilike('IT'), Company.provincia.ilike(provincia)))
                else:
                    conditions.append(Company.paese.ilike(p))
            q = q.filter(or_(*conditions))
        else:
            if len(paesi) == 1:
                q = q.filter(Company.paese.ilike(paesi[0]))
            else:
                q = q.filter(or_(*[Company.paese.ilike(p) for p in paesi]))
    elif provincia:
        q = q.filter(Company.provincia.ilike(provincia))
    if storico_contatti:
        q = q.filter(Company.storico_contatti.ilike(f"%{storico_contatti}%"))
    if agente:
        from sqlalchemy import or_
        q = q.filter(or_(Company.agente_ilsa == agente, Company.agente_desco == agente))
    if tipo_attivita:
        q = q.filter(Company.tipo_attivita.ilike(f"%{tipo_attivita}%"))

    if con_offerte_attive:
        q = q.filter(func.coalesce(opp_stats.c.offerte_attive, 0) >= 1)
    if con_offerte_scadute:
        q = q.filter(func.coalesce(opp_stats.c.offerte_scadute, 0) >= 1)
    if con_offerte_vinte:
        q = q.filter(func.coalesce(opp_stats.c.offerte_vinte, 0) >= 1)
    if con_offerte_perse:
        q = q.filter(func.coalesce(opp_stats.c.offerte_perse, 0) >= 1)
    if min_valore_offerte_attive is not None:
        q = q.filter(func.coalesce(opp_stats.c.valore_offerte_attive, 0) >= min_valore_offerte_attive)
    if max_valore_offerte_attive is not None:
        q = q.filter(func.coalesce(opp_stats.c.valore_offerte_attive, 0) <= max_valore_offerte_attive)
    if min_valore_offerte_scadute is not None:
        q = q.filter(func.coalesce(opp_stats.c.valore_offerte_scadute, 0) >= min_valore_offerte_scadute)
    if max_valore_offerte_scadute is not None:
        q = q.filter(func.coalesce(opp_stats.c.valore_offerte_scadute, 0) <= max_valore_offerte_scadute)
    if min_ordini is not None:
        q = q.filter(func.coalesce(order_stats.c.ordini_totali, 0) >= min_ordini)
    if max_ordini is not None:
        q = q.filter(func.coalesce(order_stats.c.ordini_totali, 0) <= max_ordini)

    offerte_totali_expr = (
        func.coalesce(opp_stats.c.offerte_attive, 0) +
        func.coalesce(opp_stats.c.offerte_scadute, 0) +
        func.coalesce(opp_stats.c.offerte_vinte, 0) +
        func.coalesce(opp_stats.c.offerte_perse, 0)
    )
    if min_offerte_totali is not None:
        q = q.filter(offerte_totali_expr >= min_offerte_totali)
    if max_offerte_totali is not None:
        q = q.filter(offerte_totali_expr <= max_offerte_totali)
    if min_valore is not None:
        q = q.filter(func.coalesce(order_stats.c.valore_ordini, 0) >= min_valore)
    if max_valore is not None:
        q = q.filter(func.coalesce(order_stats.c.valore_ordini, 0) <= max_valore)

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()

    sort_map = {
        "ragione_sociale":       Company.ragione_sociale,
        "offerte_attive":        func.coalesce(opp_stats.c.offerte_attive, 0),
        "offerte_scadute":       func.coalesce(opp_stats.c.offerte_scadute, 0),
        "offerte_vinte":         func.coalesce(opp_stats.c.offerte_vinte, 0),
        "offerte_perse":          func.coalesce(opp_stats.c.offerte_perse, 0),
        "valore_offerte_attive":  func.coalesce(opp_stats.c.valore_offerte_attive, 0),
        "valore_offerte_scadute": func.coalesce(opp_stats.c.valore_offerte_scadute, 0),
        "ordini_totali":         func.coalesce(order_stats.c.ordini_totali, 0),
        "valore_ordini":         func.coalesce(order_stats.c.valore_ordini, 0),
        "ultima_interazione_sap": func.greatest(last_opp.c.last_date, last_order.c.last_date),
    }
    col = sort_map.get(sort_by, Company.ragione_sociale)
    order_col = col.desc() if sort_dir == "desc" else col.asc()

    rows = q.order_by(order_col).offset(offset).limit(limit).all()

    items = []
    for row in rows:
        c = row.Company
        items.append({
            "id": str(c.id),
            "ragione_sociale": c.ragione_sociale,
            "citta": c.citta,
            "provincia": c.provincia,
            "paese": c.paese,
            "status": c.status,
            "sap_customer_id": c.sap_customer_id,
            "partita_iva": c.partita_iva,
            "telefono": c.telefono,
            "email": c.email,
            "indirizzo": c.indirizzo,
            "cap": c.cap,
            "offerte_attive": int(row.offerte_attive),
            "valore_offerte_attive": float(row.valore_offerte_attive),
            "offerte_scadute": int(row.offerte_scadute),
            "valore_offerte_scadute": float(row.valore_offerte_scadute),
            "offerte_vinte": int(row.offerte_vinte),
            "offerte_perse": int(row.offerte_perse),
            "offerte_totali": int(row.offerte_attive) + int(row.offerte_scadute) + int(row.offerte_vinte) + int(row.offerte_perse),
            "ordini_totali": int(row.ordini_totali),
            "valore_ordini": float(row.valore_ordini),
            "agente_ilsa": c.agente_ilsa,
            "agente_desco": c.agente_desco,
            "ultima_interazione_sap": row.ultima_interazione_sap.isoformat() if row.ultima_interazione_sap else None,
            "storico_contatti": c.storico_contatti,
            "origin": c.origin,
            "created_by": c.created_by,
            "created_at": c.created_at.date().isoformat() if c.created_at else None,
            "sap_created_at": c.sap_created_at.isoformat() if c.sap_created_at else None,
            "status_dinamico": _status_dinamico(c),
        })

    return {"total": total, "items": items}


@router.get("/stats/counts")
def stats_counts(db: Session = Depends(get_db)):
    clienti = db.query(func.count(Company.id)).filter(Company.status == "cliente").scalar()
    potenziali = db.query(func.count(Company.id)).filter(
        Company.status != "cliente", Company.sap_customer_id != None
    ).scalar()
    lead = db.query(func.count(Company.id)).filter(
        Company.status != "cliente", Company.sap_customer_id == None
    ).scalar()
    return {"clienti": clienti, "potenziali": potenziali, "lead": lead}


@router.get("/{company_id}")
def get_azienda(company_id: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")

    status_dinamico = _status_dinamico(company)

    return {
        "id": str(company.id),
        "ragione_sociale": company.ragione_sociale,
        "partita_iva": company.partita_iva,
        "indirizzo": company.indirizzo,
        "citta": company.citta,
        "cap": company.cap,
        "provincia": company.provincia,
        "paese": company.paese,
        "tipo_attivita": company.tipo_attivita,
        "website": company.website,
        "telefono": company.telefono,
        "telefono_override": company.telefono_override,
        "email": company.email,
        "email_override": company.email_override,
        "status": company.status,
        "agente_ilsa": company.agente_ilsa,
        "agente_desco": company.agente_desco,
        "sap_customer_id": company.sap_customer_id,
        "sap_created_at": company.sap_created_at.isoformat() if company.sap_created_at else None,
        "origin": company.origin,
        "storico_contatti": company.storico_contatti,
        "created_by": company.created_by,
        "created_at": company.created_at.date().isoformat() if company.created_at else None,
        "updated_at": company.updated_at.isoformat() if company.updated_at else None,
        "status_dinamico": status_dinamico,
    }


@router.post("/merge")
def merge_aziende(data: dict, db: Session = Depends(get_db)):
    """data: { survivor_id, duplicate_ids: [id, ...] }"""
    from app.services.dedup import merge_companies, _rank
    survivor = db.query(Company).filter(Company.id == data["survivor_id"]).first()
    if not survivor:
        raise HTTPException(status_code=404, detail="Azienda survivor non trovata")
    duplicate_ids = data.get("duplicate_ids") or ([data["duplicate_id"]] if "duplicate_id" in data else [])
    for dup_id in duplicate_ids:
        duplicate = db.query(Company).filter(Company.id == dup_id).first()
        if not duplicate:
            raise HTTPException(status_code=404, detail=f"Azienda {dup_id} non trovata")
        if _rank(duplicate) > _rank(survivor):
            raise HTTPException(
                status_code=400,
                detail=f"'{duplicate.ragione_sociale}' ha status superiore al survivor scelto. Seleziona il record con status più alto come survivor (cliente > potenziale > lead)."
            )
        merge_companies(survivor, duplicate, db)
    db.commit()
    return {"ok": True, "survivor_id": str(survivor.id)}


@router.post("/")
def crea_azienda(data: dict, db: Session = Depends(get_db)):
    company = Company(**data)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=204)
def elimina_azienda(company_id: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")
    if company.sap_customer_id:
        raise HTTPException(status_code=403, detail="Impossibile eliminare un'azienda sincronizzata da SAP")
    db.delete(company)
    db.commit()



def _auth_service(x_service_key: str):
    if not settings.service_api_key or x_service_key != settings.service_api_key:
        raise HTTPException(status_code=403, detail="Service key non valida")


def _apply_enrichment(company: Company, data: dict, db: Session) -> dict:
    ENRICHMENT_FIELDS = {"website", "email", "telefono"}
    updated = {}
    for field, value in data.items():
        if field not in ENRICHMENT_FIELDS:
            continue
        if value and not getattr(company, field):
            setattr(company, field, value)
            updated[field] = value
    db.commit()
    return updated


@service_router.patch("/{company_id}/enrich")
def enrich_azienda(
    company_id: str,
    data: dict,
    db: Session = Depends(get_db),
    x_service_key: str = Header(None),
):
    _auth_service(x_service_key)
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")
    return {"updated": _apply_enrichment(company, data, db)}


@service_router.patch("/enrich-by-sap/{sap_id}")
def enrich_azienda_by_sap(
    sap_id: str,
    data: dict,
    db: Session = Depends(get_db),
    x_service_key: str = Header(None),
):
    _auth_service(x_service_key)
    company = db.query(Company).filter(Company.sap_customer_id == sap_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")
    return {"updated": _apply_enrichment(company, data, db)}


@service_router.delete("/enrich-by-sap/{sap_id}")
def clear_enrichment_by_sap(
    sap_id: str,
    db: Session = Depends(get_db),
    x_service_key: str = Header(None),
):
    _auth_service(x_service_key)
    company = db.query(Company).filter(Company.sap_customer_id == sap_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")
    cleared = {f: getattr(company, f) for f in ("website", "email", "telefono") if getattr(company, f)}
    company.website = None
    company.email = None
    company.telefono = None
    db.commit()
    return {"cleared": list(cleared.keys())}


@router.patch("/{company_id}")
def aggiorna_azienda(company_id: str, data: dict, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Azienda non trovata")
    for key, value in data.items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company
