from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, contains_eager
from app.database import get_db
from app.models.note import Note
from app.auth import get_current_user
from app.activity import log_activity

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_note(company_id: str = Query(...), db: Session = Depends(get_db)):
    notes = (
        db.query(Note)
        .options(joinedload(Note.opportunity), joinedload(Note.contact))
        .filter(Note.company_id == company_id)
        .order_by(Note.pinned.desc(), Note.created_at.desc())
        .all()
    )
    return [_serialize(n) for n in notes]


@router.post("/")
def crea_nota(data: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    note = Note(**data)
    db.add(note)
    db.flush()
    from app.models.company import Company
    company = db.query(Company).filter(Company.id == note.company_id).first()
    log_activity(db, current_user.nome, "nota_creata", "nota",
                 entity_id=note.id, company_id=note.company_id,
                 company_nome=company.ragione_sociale if company else None,
                 detail={"testo": (note.testo or "")[:80]})
    db.commit()
    db.refresh(note)
    db.refresh(note, ["opportunity"])
    return _serialize(note)


@router.patch("/{note_id}")
def aggiorna_nota(note_id: str, data: dict, db: Session = Depends(get_db)):
    note = db.query(Note).options(joinedload(Note.opportunity), joinedload(Note.contact)).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Nota non trovata")
    for k, v in data.items():
        setattr(note, k, v)
    db.commit()
    db.expire(note)
    note = db.query(Note).options(joinedload(Note.opportunity), joinedload(Note.contact)).filter(Note.id == note_id).first()
    return _serialize(note)


@router.delete("/{note_id}", status_code=204)
def elimina_nota(note_id: str, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Nota non trovata")
    db.delete(note)
    db.commit()


def _serialize(n: Note):
    return {
        "id": str(n.id),
        "company_id": str(n.company_id),
        "opportunity_id": str(n.opportunity_id) if n.opportunity_id else None,
        "opportunity_label": n.opportunity.sap_document_id if n.opportunity else None,
        "contact_id": str(n.contact_id) if n.contact_id else None,
        "contact_label": n.contact.nome if n.contact else None,
        "testo": n.testo,
        "pinned": n.pinned,
        "created_by": n.created_by,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat() if n.updated_at else n.created_at.isoformat(),
    }
