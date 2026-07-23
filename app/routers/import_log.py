import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models.import_log import ImportLog
from app.models.company import Company
from app.models.contact import Contact
from app.models.note import Note

router = APIRouter(prefix="/import-logs", tags=["import-logs"], dependencies=[Depends(get_current_user)])


@router.get("/")
def list_logs(db: Session = Depends(get_db)):
    logs = db.query(ImportLog).order_by(ImportLog.created_at.desc()).limit(50).all()
    return [_serialize(l) for l in logs]


@router.get("/{log_id}/check")
def check_undo(log_id: str, db: Session = Depends(get_db)):
    log = db.query(ImportLog).filter(ImportLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Import log non trovato")
    if log.undone_at:
        return {"can_undo": False, "undoable": 0, "blocked": 0, "blockers": ["Import già annullato"]}

    undo_c, block_c, undo_u, block_u, blockers = _classify(log, db)
    undoable = len(undo_c) + len(undo_u)
    blocked = len(block_c) + len(block_u)
    return {
        "can_undo": undoable > 0,
        "undoable": undoable,
        "blocked": blocked,
        "blockers": blockers,
    }


@router.post("/{log_id}/undo")
def undo_import(log_id: str, db: Session = Depends(get_db)):
    log = db.query(ImportLog).filter(ImportLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Import log non trovato")
    if log.undone_at:
        raise HTTPException(status_code=400, detail="Import già annullato")

    undo_c, block_c, undo_u, block_u, _ = _classify(log, db)
    if not undo_c and not undo_u:
        raise HTTPException(status_code=409, detail="Nessun record annullabile")

    _execute_partial_undo(log, undo_c, undo_u, db)
    log.undone_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "annullati": len(undo_c) + len(undo_u),
        "saltati": len(block_c) + len(block_u),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _classify(log: ImportLog, db: Session):
    """Classify each record as undoable or blocked. Returns (undo_created_ids, blocked_created_ids, undo_updated_snaps, blocked_updated_snaps, blockers)."""
    undo_c, block_c, undo_u, block_u, blockers = [], [], [], [], []
    note_id_uuids = {uuid.UUID(nid) for nid in (log.note_ids or [])}

    if log.tipo == "aziende":
        for id_str in (log.created_ids or []):
            company = db.query(Company).filter(Company.id == id_str).first()
            if not company:
                block_c.append(id_str)
                blockers.append("Un'azienda creata dall'import non esiste più (mergiata o eliminata)")
                continue
            reasons = []
            if company.updated_at > company.created_at:
                reasons.append(f"'{company.ragione_sociale}' è stata modificata dopo l'import")
            else:
                q = db.query(Note).filter(Note.company_id == company.id)
                if note_id_uuids:
                    q = q.filter(Note.id.notin_(note_id_uuids))
                if q.count() > 0:
                    reasons.append(f"'{company.ragione_sociale}' ha note aggiunte manualmente")
                if db.query(Contact).filter(Contact.company_id == company.id).count() > 0:
                    reasons.append(f"'{company.ragione_sociale}' ha contatti associati")
            if reasons:
                block_c.append(id_str)
                blockers.extend(reasons)
            else:
                undo_c.append(id_str)

        for snap in (log.updated_snapshots or []):
            company = db.query(Company).filter(Company.id == snap['id']).first()
            if not company:
                block_u.append(snap)
                blockers.append("Un'azienda aggiornata dall'import non esiste più")
                continue
            changed = False
            for field, expected in snap.get('after', {}).items():
                current = getattr(company, field)
                if str(current or '') != str(expected or ''):
                    nome = snap.get('ragione_sociale', snap['id'])
                    blockers.append(f"'{nome}' è stata modificata dopo l'import")
                    changed = True
                    break
            (block_u if changed else undo_u).append(snap)

    elif log.tipo == "contatti":
        for id_str in (log.created_ids or []):
            contact = db.query(Contact).filter(Contact.id == id_str).first()
            if not contact:
                block_c.append(id_str)
                blockers.append("Un contatto creato dall'import non esiste più")
                continue
            reasons = []
            if contact.updated_at > contact.created_at:
                reasons.append(f"'{contact.nome}' è stato modificato dopo l'import")
            else:
                q = db.query(Note).filter(Note.contact_id == contact.id)
                if note_id_uuids:
                    q = q.filter(Note.id.notin_(note_id_uuids))
                if q.count() > 0:
                    reasons.append(f"'{contact.nome}' ha note aggiunte manualmente")
            if reasons:
                block_c.append(id_str)
                blockers.extend(reasons)
            else:
                undo_c.append(id_str)

        for snap in (log.updated_snapshots or []):
            contact = db.query(Contact).filter(Contact.id == snap['id']).first()
            if not contact:
                block_u.append(snap)
                blockers.append("Un contatto aggiornato dall'import non esiste più")
                continue
            changed = False
            for field, expected in snap.get('after', {}).items():
                current = getattr(contact, field)
                if str(current or '') != str(expected or ''):
                    nome = snap.get('nome', snap['id'])
                    blockers.append(f"'{nome}' è stato modificato dopo l'import")
                    changed = True
                    break
            (block_u if changed else undo_u).append(snap)

    return undo_c, block_c, undo_u, block_u, blockers


def _execute_partial_undo(log: ImportLog, undo_created_ids: list, undo_updated_snaps: list, db: Session):
    note_id_uuids = [uuid.UUID(nid) for nid in (log.note_ids or [])]
    for note_uuid in note_id_uuids:
        note = db.query(Note).filter(Note.id == note_uuid).first()
        if note:
            db.delete(note)
    db.flush()

    if log.tipo == "aziende":
        for snap in undo_updated_snaps:
            company = db.query(Company).filter(Company.id == snap['id']).first()
            if company:
                for field, value in snap['before'].items():
                    setattr(company, field, value if value != '' else None)
        for id_str in undo_created_ids:
            company = db.query(Company).filter(Company.id == id_str).first()
            if company:
                db.delete(company)

    elif log.tipo == "contatti":
        for snap in undo_updated_snaps:
            contact = db.query(Contact).filter(Contact.id == snap['id']).first()
            if contact:
                for field, value in snap['before'].items():
                    setattr(contact, field, value if value != '' else None)
        for id_str in undo_created_ids:
            contact = db.query(Contact).filter(Contact.id == id_str).first()
            if contact:
                db.delete(contact)

    db.flush()


def _serialize(log: ImportLog) -> dict:
    return {
        "id": str(log.id),
        "tipo": log.tipo,
        "created_by": log.created_by,
        "creati": log.creati,
        "aggiornati": log.aggiornati,
        "saltati": log.saltati,
        "dettaglio_saltati": log.dettaglio_saltati or [],
        "created_at": log.created_at.isoformat(),
        "undone_at": log.undone_at.isoformat() if log.undone_at else None,
        "n_created_ids": len(log.created_ids or []),
        "n_updated_snapshots": len(log.updated_snapshots or []),
    }
