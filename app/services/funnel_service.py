from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.opportunity import Opportunity, STAGE_VALIDI


def cambia_stage(db: Session, opportunity: Opportunity, nuovo_stage: str, loss_reason: str | None = None) -> Opportunity:
    if nuovo_stage not in STAGE_VALIDI:
        raise HTTPException(status_code=400, detail=f"Stage non valido. Valori ammessi: {STAGE_VALIDI}")

    if nuovo_stage == "Chiuso Perso" and not loss_reason:
        raise HTTPException(status_code=400, detail="loss_reason obbligatorio per Chiuso Perso")

    opportunity.stage = nuovo_stage
    opportunity.stage_changed_at = datetime.now(timezone.utc)

    if loss_reason:
        opportunity.loss_reason = loss_reason

    db.commit()
    db.refresh(opportunity)
    return opportunity
