from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.contact import Contact
from app.models.company import Company
from app.models.note import Note
from app.auth import get_current_user, allowed_company_ids

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_contatti(
    company_id: str | None = None,
    search: str | None = None,
    azienda: str | None = None,
    ruolo: str | None = None,
    paese: str | None = None,
    storico_contatti: str | None = None,
    agente: str | None = None,
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(Contact).join(Contact.company).options(joinedload(Contact.company))
    subq = allowed_company_ids(current_user, db)
    if subq is not None:
        from sqlalchemy import or_
        zone = current_user.zone_assegnate or []
        query = query.filter(
            Contact.company_id.in_(subq),
            or_(Contact.zona.is_(None), Contact.zona.in_(zone)),
        )
    if company_id:
        query = query.filter(Contact.company_id == company_id)
    if search:
        q = f"%{search}%"
        from sqlalchemy import or_
        query = query.filter(or_(
            Contact.nome.ilike(q),
            Contact.ruolo.ilike(q),
            Contact.email.ilike(q),
            Company.ragione_sociale.ilike(q),
            Company.sap_customer_id.ilike(q),
        ))
    if azienda:
        query = query.filter(Company.ragione_sociale == azienda)
    if ruolo:
        query = query.filter(Contact.ruolo == ruolo)
    if paese:
        query = query.filter(Company.paese == paese)
    if storico_contatti:
        query = query.filter(Contact.storico_contatti.ilike(f"%{storico_contatti}%"))
    if agente:
        from sqlalchemy import or_
        query = query.filter(or_(Company.agente_ilsa == agente, Company.agente_desco == agente))
    query = query.order_by(Contact.nome)
    # When filtering by company, return all (used in AccountDetail/QuickCreate dropdowns)
    if company_id:
        contacts = query.all()
        return [_serialize(c) for c in contacts]
    total = query.count()
    contacts = query.offset(offset).limit(limit).all()
    return {"total": total, "items": [_serialize(c) for c in contacts]}


@router.get("/{contact_id}")
def get_contatto(contact_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).options(joinedload(Contact.company)).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    return _serialize(contact)


@router.post("/")
def crea_contatto(data: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    company_id = data.get('company_id')
    if company_id and not data.get('zona'):
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            user_zones = current_user.zone_assegnate or []
            if company.agente_ilsa in user_zones:
                data['zona'] = company.agente_ilsa
            elif company.agente_desco in user_zones:
                data['zona'] = company.agente_desco
    contact = Contact(**data)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    db.refresh(contact, ["company"])
    return _serialize(contact)


@router.patch("/{contact_id}")
def aggiorna_contatto(contact_id: str, data: dict, db: Session = Depends(get_db)):
    contact = db.query(Contact).options(joinedload(Contact.company)).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    for key, value in data.items():
        setattr(contact, key, value)
    db.commit()
    db.refresh(contact)
    return _serialize(contact)


@router.post("/merge")
def merge_contatti(data: dict, db: Session = Depends(get_db)):
    survivor_id = data.get("survivor_id")
    duplicate_ids = data.get("duplicate_ids", [])
    if not survivor_id or not duplicate_ids:
        raise HTTPException(status_code=400, detail="IDs non validi")

    survivor = db.query(Contact).options(joinedload(Contact.company)).filter(Contact.id == survivor_id).first()
    if not survivor:
        raise HTTPException(status_code=404, detail="Contatto survivor non trovato")

    for dup_id in duplicate_ids:
        if dup_id == survivor_id:
            continue
        duplicate = db.query(Contact).filter(Contact.id == dup_id).first()
        if not duplicate:
            continue
        for field in ("ruolo", "telefono", "email", "note"):
            if not getattr(survivor, field):
                val = getattr(duplicate, field)
                if val:
                    setattr(survivor, field, val)
        if duplicate.storico_contatti:
            survivor.storico_contatti = _append_storico(survivor.storico_contatti, duplicate.storico_contatti)
        if duplicate.is_primary:
            survivor.is_primary = True
        db.query(Note).filter(Note.contact_id == duplicate.id).update({"contact_id": survivor.id}, synchronize_session="fetch")
        db.flush()  # invia UPDATE a Postgres prima della DELETE per evitare ON DELETE SET NULL
        db.delete(duplicate)
        db.flush()  # invia DELETE dopo che le note sono già state riassegnate

    db.commit()
    db.refresh(survivor)
    db.refresh(survivor, ["company"])
    return _serialize(survivor)


@router.delete("/{contact_id}", status_code=204)
def elimina_contatto(contact_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    db.delete(contact)
    db.commit()


def _append_storico(existing: str | None, nuovo: str) -> str:
    if not existing:
        return nuovo
    parts = [p.strip() for p in existing.split('·')]
    for p in [p.strip() for p in nuovo.split('·')]:
        if p and p not in parts:
            parts.append(p)
    return ' · '.join(parts)


def _serialize(c: Contact):
    return {
        "id": str(c.id),
        "company_id": str(c.company_id),
        "company_name": c.company.ragione_sociale if c.company else None,
        "paese": c.company.paese if c.company else None,
        "nome": c.nome,
        "ruolo": c.ruolo,
        "email": c.email,
        "telefono": c.telefono,
        "is_primary": c.is_primary,
        "storico_contatti": c.storico_contatti,
        "note": c.note,
        "zona": c.zona,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }
