from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.database import get_db
from app.models.reminder import EmailReminder
from app.auth import get_current_user
from app.services.email_service import send_email

router = APIRouter(prefix="/reminders", tags=["reminders"], dependencies=[Depends(get_current_user)])
internal_router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


@router.get("/")
def lista_reminders(
    company_id: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(EmailReminder).filter(EmailReminder.created_by == current_user.email)
    if company_id:
        q = q.filter(EmailReminder.company_id == company_id)
    if status:
        q = q.filter(EmailReminder.status == status)
    reminders = q.order_by(EmailReminder.scheduled_at.desc()).all()
    return [_serialize(r) for r in reminders]


@router.post("/")
def crea_reminder(data: dict, db: Session = Depends(get_db)):
    reminder = EmailReminder(**data)
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return _serialize(reminder)


@router.patch("/{reminder_id}")
def modifica_reminder(reminder_id: str, data: dict, db: Session = Depends(get_db)):
    reminder = db.query(EmailReminder).filter(EmailReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder non trovato")
    if reminder.status == "sent":
        raise HTTPException(status_code=400, detail="I reminder inviati non possono essere modificati")
    for field in ("oggetto", "body", "destinatari", "cc", "scheduled_at"):
        if field in data:
            setattr(reminder, field, data[field])
    if data.get("resend"):
        reminder.status = "pending"
        reminder.error_message = None
    db.commit()
    db.refresh(reminder)
    return _serialize(reminder)


@router.delete("/{reminder_id}", status_code=204)
def cancella_reminder(reminder_id: str, db: Session = Depends(get_db)):
    reminder = db.query(EmailReminder).filter(EmailReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder non trovato")
    if reminder.status not in ("pending", "failed"):
        raise HTTPException(status_code=400, detail="Solo i reminder in attesa o falliti possono essere eliminati")
    db.delete(reminder)
    db.commit()


def run_pending_reminders(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    due = (
        db.query(EmailReminder)
        .filter(EmailReminder.status == "pending", EmailReminder.scheduled_at <= now)
        .all()
    )
    sent, failed = 0, 0
    for r in due:
        try:
            send_email(
                to=r.destinatari,
                subject=r.oggetto,
                body=r.body,
                cc=r.cc or [],
                sender_name="ILSA CRM",
                reply_to=r.mittente_email or None,
            )
            r.status = "sent"
            r.sent_at = now
            sent += 1
        except Exception as e:
            r.status = "failed"
            r.error_message = str(e)
            failed += 1
    db.commit()
    return {"processed": len(due), "sent": sent, "failed": failed}


@internal_router.post("/process-reminders")
def processa_reminders(db: Session = Depends(get_db)):
    return run_pending_reminders(db)


def _serialize(r: EmailReminder):
    return {
        "id": str(r.id),
        "company_id": str(r.company_id) if r.company_id else None,
        "opportunity_id": str(r.opportunity_id) if r.opportunity_id else None,
        "oggetto": r.oggetto,
        "body": r.body,
        "destinatari": r.destinatari or [],
        "cc": r.cc or [],
        "scheduled_at": r.scheduled_at.isoformat(),
        "status": r.status,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "error_message": r.error_message,
        "created_by": r.created_by,
        "mittente_email": r.mittente_email,
        "created_at": r.created_at.isoformat(),
    }
