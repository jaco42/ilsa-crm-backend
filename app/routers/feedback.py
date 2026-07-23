from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.feedback import Feedback
from app.routers.auth import get_current_user
import logging

log = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

URGENZA_LABEL = {"bassa": "Bassa", "media": "Media", "alta": "Alta"}
TIPO_LABEL = {"problema": "Problema", "feature": "Nuova feature"}


@router.post("/")
def crea_feedback(data: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    fb = Feedback(
        tipo=data.get("tipo"),
        urgenza=data.get("urgenza"),
        titolo=data.get("titolo"),
        messaggio=data.get("messaggio"),
        created_by=current_user.nome,
    )
    db.add(fb)
    db.commit()

    try:
        from app.services.email_service import send_email
        from app.config import settings
        corpo = (
            f"Da: {current_user.nome}\n"
            f"Tipo: {TIPO_LABEL.get(fb.tipo, fb.tipo)}\n"
            f"Urgenza: {URGENZA_LABEL.get(fb.urgenza, fb.urgenza)}\n\n"
            f"Titolo: {fb.titolo}\n\n"
            f"{fb.messaggio or ''}"
        )
        send_email(
            to=settings.smtp_from or settings.smtp_user,
            subject=f"[CRM Feedback] {TIPO_LABEL.get(fb.tipo, fb.tipo)} — {fb.titolo}",
            body=corpo,
            sender_name="CRM Feedback",
        )
    except Exception as e:
        log.warning(f"Email feedback non inviata: {e}")

    return {"ok": True, "id": str(fb.id)}
