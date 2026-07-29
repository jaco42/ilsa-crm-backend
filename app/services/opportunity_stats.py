from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.models.opportunity import Opportunity

STAGE_PERSA = ['Drop pre-offerta', 'Drop post-offerta', 'Chiuso Perso']


def build_scaduta_attiva(today: date):
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


def win_rate_from_query(q, today: date) -> dict:
    """Calcola vinte/perse/scadute/tasso_successo su una query già filtrata."""
    scaduta_cond, _ = build_scaduta_attiva(today)
    vinte, perse, scadute = q.with_entities(
        func.count(case((Opportunity.stage == 'Chiuso Vinto', 1))),
        func.count(case((Opportunity.stage.in_(STAGE_PERSA), 1))),
        func.count(case((scaduta_cond, 1))),
    ).one()
    chiuse = vinte + perse + scadute
    return {
        "vinte": vinte,
        "perse": perse,
        "scadute": scadute,
        "chiuse": chiuse,
        "tasso_successo": round(vinte / chiuse * 100) if chiuse else None,
    }
