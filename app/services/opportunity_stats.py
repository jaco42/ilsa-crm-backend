from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.models.opportunity import Opportunity

STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def build_scaduta_attiva(today: date):
    """Restituisce (scaduta_cond, attiva_cond) come SQLAlchemy expressions."""
    un_mese_fa = today - timedelta(days=30)
    scaduta = (Opportunity.stage == 'Offerta Mandata') & (
        (Opportunity.data_scadenza < today) |
        (
            (Opportunity.data_scadenza == None) &
            (Opportunity.data_creazione_sap != None) &
            (Opportunity.data_creazione_sap < un_mese_fa)
        )
    )
    attiva = (Opportunity.stage == 'Offerta Mandata') & (
        (Opportunity.data_scadenza >= today) |
        (
            (Opportunity.data_scadenza == None) &
            ((Opportunity.data_creazione_sap == None) | (Opportunity.data_creazione_sap >= un_mese_fa))
        )
    )
    return scaduta, attiva


def opportunity_stats(db: Session, today: date, creazione_dal: date = None, creazione_al: date = None) -> dict:
    """Calcola vinte/perse/scadute/attive con la logica canonica.
    Opzionalmente filtra per data_creazione_sap."""
    scaduta_cond, attiva_cond = build_scaduta_attiva(today)

    q = db.query(Opportunity)
    if creazione_dal:
        q = q.filter(Opportunity.data_creazione_sap >= creazione_dal)
    if creazione_al:
        q = q.filter(Opportunity.data_creazione_sap <= creazione_al)

    vinte, perse, scadute, attive = q.with_entities(
        func.count(case((Opportunity.stage == 'Chiuso Vinto', 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((scaduta_cond, 1))),
        func.count(case((attiva_cond, 1))),
    ).one()

    chiuse = vinte + perse + scadute
    return {
        "vinte": vinte,
        "perse": perse,
        "scadute": scadute,
        "attive": attive,
        "chiuse": chiuse,
        "tasso_successo": round(vinte / chiuse * 100) if chiuse else None,
    }
