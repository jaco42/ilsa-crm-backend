from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.contact import Contact
from app.models.company import Company
from app.auth import get_current_user

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_contatti(
    company_id: str | None = None,
    search: str | None = None,
    azienda: str | None = None,
    ruolo: str | None = None,
    paese: str | None = None,
    provenienza: str | None = None,
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    query = db.query(Contact).join(Contact.company).options(joinedload(Contact.company))
    if company_id:
        query = query.filter(Contact.company_id == company_id)
    if search:
        q = f"%{search}%"
        query = query.filter(
            Contact.nome.ilike(q) | Contact.ruolo.ilike(q) | Contact.email.ilike(q)
        )
    if azienda:
        query = query.filter(Company.ragione_sociale == azienda)
    if ruolo:
        query = query.filter(Contact.ruolo == ruolo)
    if paese:
        query = query.filter(Company.paese == paese)
    if provenienza:
        query = query.filter(Contact.provenienza.ilike(f"%{provenienza}%"))
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
def crea_contatto(data: dict, db: Session = Depends(get_db)):
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


@router.delete("/{contact_id}", status_code=204)
def elimina_contatto(contact_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    db.delete(contact)
    db.commit()


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
        "provenienza": c.provenienza,
        "note": c.note,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }
