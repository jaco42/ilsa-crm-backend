"""
COSA SONO I SERVICES
--------------------
I services contengono le regole di business dell'applicazione.

I router gestiscono solo la comunicazione HTTP (ricevono la richiesta, restituiscono
la risposta). I modelli descrivono solo la struttura dei dati. Le regole di business
— cosa è permesso, cosa è obbligatorio, cosa succede automaticamente — vivono qui.

Vantaggio: se la stessa regola serve in più posti (es. nel router E nel job SAP),
la scrivi una volta sola qui e la chiami da dove vuoi. Se cambia, la aggiorni
in un posto solo.


COSA FA QUESTO FILE
-------------------
Gestisce la creazione e i cambi di stage delle opportunity.

Regole attive:
- Lo stage è obbligatorio alla creazione
- Lo stage deve essere uno dei valori in STAGE_VALIDI
- "Chiuso Perso" richiede loss_reason obbligatorio

TODO Blocco 4: attualmente non è possibile creare un'opportunity per un'azienda
che non esiste ancora nel CRM. Il rep deve prima creare la company e poi
l'opportunity. La gestione del caso "azienda nuova in un colpo solo" viene
affrontata nel Blocco 4 con la logica di inbox e fuzzy matching.
"""

from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.opportunity import Opportunity, STAGE_VALIDI


def crea_opportunity(db: Session, data: dict) -> Opportunity:
    stage = data.get("stage")

    if not stage:
        raise HTTPException(status_code=400, detail="stage è obbligatorio")

    if stage not in STAGE_VALIDI:
        raise HTTPException(status_code=400, detail=f"Stage non valido. Valori ammessi: {STAGE_VALIDI}")

    if stage == "Chiuso Perso" and not data.get("loss_reason"):
        raise HTTPException(status_code=400, detail="loss_reason obbligatorio per Chiuso Perso")

    opportunity = Opportunity(
        **data,
        stage_changed_at=datetime.now(timezone.utc),
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


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
