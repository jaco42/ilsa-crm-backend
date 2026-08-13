from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import func, case, select
from app.database import get_db
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.auth import get_current_user, company_agente_filter
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


@router.post("/auto_assign_agenti")
def auto_assign_agenti(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.ruolo != 'admin':
        raise HTTPException(status_code=403, detail="Solo gli admin possono eseguire questa operazione")
    from sqlalchemy import func

    # Precalcola top agente per (paese, provincia) in una sola query per linea
    def build_top_map(col):
        # rank() per trovare il primo per ogni gruppo paese+provincia
        ranked = (
            db.query(
                Company.paese,
                Company.provincia,
                col,
                func.rank().over(
                    partition_by=[Company.paese, Company.provincia],
                    order_by=func.count().desc()
                ).label('rnk')
            )
            .filter(col.isnot(None), col != '', Company.paese.isnot(None))
            .group_by(Company.paese, Company.provincia, col)
            .subquery()
        )
        rows = db.query(ranked).filter(ranked.c.rnk == 1).all()
        # (paese, provincia) -> agente, con fallback su (paese, None)
        by_prov = {}
        by_paese = {}
        for r in rows:
            if r.provincia:
                by_prov[(r.paese, r.provincia)] = r[2]
            else:
                by_paese[r.paese] = r[2]
        return by_prov, by_paese

    ilsa_prov, ilsa_paese = build_top_map(Company.agente_ilsa)
    desco_prov, desco_paese = build_top_map(Company.agente_desco)

    def lookup(by_prov, by_paese, paese, provincia):
        return by_prov.get((paese, provincia)) or by_paese.get(paese)

    unassigned = db.query(Company).filter(
        Company.is_visible == True,
        Company.agente_ilsa.is_(None),
        Company.agente_desco.is_(None),
        Company.paese.isnot(None),
    ).all()

    updated = 0
    for c in unassigned:
        ilsa = lookup(ilsa_prov, ilsa_paese, c.paese, c.provincia)
        desco = lookup(desco_prov, desco_paese, c.paese, c.provincia)
        if ilsa or desco:
            c.agente_ilsa = ilsa
            c.agente_desco = desco
            updated += 1

    db.commit()
    return {"totale_senza_agente": len(unassigned), "aggiornate": updated}


@router.get("/agenti_codes")
def agenti_codes(db: Session = Depends(get_db)):
    ilsa = [r[0] for r in db.query(Company.agente_ilsa)
            .filter(Company.agente_ilsa.isnot(None), Company.agente_ilsa != '')
            .distinct().order_by(Company.agente_ilsa).all()]
    desco = [r[0] for r in db.query(Company.agente_desco)
             .filter(Company.agente_desco.isnot(None), Company.agente_desco != '')
             .distinct().order_by(Company.agente_desco).all()]
    return {"ilsa": ilsa, "desco": desco}


@router.get("/suggest_agente")
def suggest_agente(paese: str = Query(None), provincia: str = Query(None), db: Session = Depends(get_db)):
    from sqlalchemy import func

    def top(col):
        q = db.query(col, func.count().label('n')).filter(col.isnot(None), col != '')
        if paese:
            q = q.filter(Company.paese == paese)
            if paese == 'IT' and provincia:
                q = q.filter(Company.provincia == provincia)
        r = q.group_by(col).order_by(func.count().desc()).first()
        return r[0] if r else None

    return {"agente_ilsa": top(Company.agente_ilsa), "agente_desco": top(Company.agente_desco)}


@router.get("/")
def lista_aziende(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
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
        func.max(Opportunity.data_creazione_sap).label("last_opp_date"),
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
            func.max(Order.data_creazione_sap).label("last_order_date"),
        )
        .join(OrderLineItem, OrderLineItem.order_id == Order.id)
    )
    if date_from:
        order_q = order_q.filter(Order.data_ordine >= date_from)
    if date_to:
        order_q = order_q.filter(Order.data_ordine <= date_to)
    order_stats = order_q.group_by(Order.company_id).subquery()

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
            func.greatest(opp_stats.c.last_opp_date, order_stats.c.last_order_date).label("ultima_interazione_sap"),
        )
        .outerjoin(opp_stats, Company.id == opp_stats.c.company_id)
        .outerjoin(order_stats, Company.id == order_stats.c.company_id)
    )

    q = company_agente_filter(current_user, q, Company)
    q = q.filter(Company.is_visible == True)

    if search:
        from sqlalchemy import or_
        q = q.filter(or_(
            Company.ragione_sociale.ilike(f"%{search}%"),
            Company.sap_customer_id.ilike(f"%{search}%"),
        ))
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
        "ultima_interazione_sap": func.greatest(opp_stats.c.last_opp_date, order_stats.c.last_order_date),
        "agente_ilsa":            Company.agente_ilsa,
    }
    col = sort_map.get(sort_by, Company.ragione_sociale)
    order_col = col.desc() if sort_dir == "desc" else col.asc()

    rows = q.add_columns(func.count().over().label('_total')).order_by(order_col).offset(offset).limit(limit).all()
    total = rows[0]._total if rows else 0

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


@router.get("/zone")
def lista_zone(db: Session = Depends(get_db)):
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT agente FROM (
            SELECT agente_ilsa AS agente FROM companies WHERE agente_ilsa IS NOT NULL AND agente_ilsa != ''
            UNION ALL
            SELECT agente_desco FROM companies WHERE agente_desco IS NOT NULL AND agente_desco != ''
        ) t GROUP BY agente ORDER BY agente
    """)).fetchall()
    return [r[0] for r in rows]


@router.get("/stats/counts")
def stats_counts(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    base = company_agente_filter(current_user, db.query(Company), Company).filter(Company.is_visible == True)
    row = base.with_entities(
        func.count(case((Company.status == "cliente", 1))).label("clienti"),
        func.count(case(((Company.status != "cliente") & (Company.sap_customer_id != None), 1))).label("potenziali"),
        func.count(case(((Company.status != "cliente") & (Company.sap_customer_id == None), 1))).label("lead"),
    ).one()
    return {"clienti": row.clienti, "potenziali": row.potenziali, "lead": row.lead}


@router.get("/{company_id}/demerge_preview")
def demerge_preview(company_id: str, db: Session = Depends(get_db)):
    from app.models.contact import Contact
    from app.models.note import Note
    losers = db.query(Company).filter(Company.merged_into == company_id).all()
    if not losers:
        raise HTTPException(status_code=404, detail="Nessuna azienda inglobata trovata")
    result = []
    for loser in losers:
        post_contacts = db.query(Contact).filter(
            Contact.company_id == company_id,
            Contact.created_at >= loser.merged_at,
        ).all() if loser.merged_at else []
        post_notes = db.query(Note).filter(
            Note.company_id == company_id,
            Note.created_at >= loser.merged_at,
        ).all() if loser.merged_at else []
        result.append({
            "loser_id": str(loser.id),
            "loser_ragione_sociale": loser.ragione_sociale,
            "loser_sap_customer_id": loser.sap_customer_id,
            "merged_at": loser.merged_at.isoformat() if loser.merged_at else None,
            "contacts_post_merge": [{"id": str(c.id), "nome": c.nome, "ruolo": c.ruolo} for c in post_contacts],
            "notes_post_merge": [{"id": str(n.id), "testo": n.testo[:100] if hasattr(n, 'testo') else "", "created_at": n.created_at.isoformat()} for n in post_notes],
            "n_contacts_post_merge": len(post_contacts),
            "n_notes_post_merge": len(post_notes),
        })
    return result


@router.post("/{company_id}/demerge")
def demerge(company_id: str, data: dict, db: Session = Depends(get_db)):
    import uuid as _uuid
    from app.models.contact import Contact
    from app.models.note import Note
    loser_id = data.get("loser_id")
    strategy = data.get("strategy")  # "all_on_winner" | "all_on_loser" | "copy_to_both" | "manual"
    manual_assignments = data.get("assignments", {})  # {"id": "winner"|"loser"|"both", ...}

    loser = db.query(Company).filter(Company.id == loser_id, Company.merged_into == company_id).first()
    if not loser:
        raise HTTPException(status_code=404, detail="Azienda perdente non trovata o non inglobata in questa")

    merged_at = loser.merged_at

    # Sempre: riporta i contatti/note pre-merge del loser al loro posto
    db.query(Contact).filter(Contact.original_company_id == loser_id).update(
        {"company_id": loser_id, "original_company_id": None}, synchronize_session=False)
    db.query(Note).filter(Note.original_company_id == loser_id).update(
        {"company_id": loser_id, "original_company_id": None}, synchronize_session=False)

    def _copy_contact(c: Contact, target_company_id: str):
        db.add(Contact(
            id=_uuid.uuid4(), company_id=target_company_id,
            nome=c.nome, ruolo=c.ruolo, telefono=c.telefono, email=c.email,
            is_primary=False, storico_contatti=c.storico_contatti,
            note=c.note, zona=c.zona, created_by=c.created_by,
        ))

    def _copy_note(n: Note, target_company_id: str):
        db.add(Note(
            id=_uuid.uuid4(), company_id=target_company_id,
            testo=n.testo, pinned=n.pinned, created_by=n.created_by,
        ))

    def _move_note_to_loser(note_filter):
        # Quando si sposta una nota al loser, azzera contact_id/opportunity_id
        # perché quei record appartengono al winner e non sarebbero raggiungibili
        db.query(Note).filter(note_filter).update(
            {"company_id": loser_id, "contact_id": None, "opportunity_id": None},
            synchronize_session=False)

    # Poi gestisci gli ambigui (post-merge) secondo la strategia scelta
    if strategy == "all_on_loser" and merged_at:
        db.query(Contact).filter(Contact.company_id == company_id, Contact.created_at >= merged_at).update(
            {"company_id": loser_id}, synchronize_session=False)
        _move_note_to_loser(
            (Note.company_id == company_id) & (Note.created_at >= merged_at))
    elif strategy == "copy_to_both" and merged_at:
        for c in db.query(Contact).filter(Contact.company_id == company_id, Contact.created_at >= merged_at).all():
            _copy_contact(c, loser_id)
        for n in db.query(Note).filter(Note.company_id == company_id, Note.created_at >= merged_at).all():
            _copy_note(n, loser_id)
    elif strategy == "manual":
        for record_id, target in manual_assignments.items():
            if target == "both":
                c = db.query(Contact).filter(Contact.id == record_id).first()
                if c:
                    _copy_contact(c, loser_id)
                else:
                    n = db.query(Note).filter(Note.id == record_id).first()
                    if n:
                        _copy_note(n, loser_id)
            elif target == "loser":
                if not db.query(Contact).filter(Contact.id == record_id).update({"company_id": loser_id}, synchronize_session=False):
                    _move_note_to_loser(Note.id == record_id)
            else:  # winner — rimane sul winner, nulla da fare
                pass
    # "all_on_winner": gli ambigui rimangono sul winner, nulla da fare

    # Ripristina il perdente come visibile e scollega
    loser.merged_into = None
    loser.merged_at = None
    loser.is_visible = True
    db.commit()
    return {"ok": True, "loser_id": loser_id}


@router.get("/{company_id}")
def get_azienda(company_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    q = company_agente_filter(current_user, db.query(Company), Company)
    company = q.filter(Company.id == company_id).first()
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
        "agente_sap_locked": company.agente_sap_locked,
        "sap_customer_id": company.sap_customer_id,
        "sap_created_at": company.sap_created_at.isoformat() if company.sap_created_at else None,
        "origin": company.origin,
        "storico_contatti": company.storico_contatti,
        "created_by": company.created_by,
        "created_at": company.created_at.date().isoformat() if company.created_at else None,
        "updated_at": company.updated_at.isoformat() if company.updated_at else None,
        "status_dinamico": status_dinamico,
        "n_inglobate": db.query(Company).filter(Company.merged_into == company_id).count(),
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
    if company.agente_sap_locked and ('agente_ilsa' in data or 'agente_desco' in data):
        raise HTTPException(status_code=403, detail="Agente assegnato da SAP: non modificabile manualmente")
    for key, value in data.items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company
