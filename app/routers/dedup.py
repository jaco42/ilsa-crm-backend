from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dedup import DeduplicaAlert
from app.models.company import Company
from app.auth import get_current_user
from app.services.dedup import merge_companies

router = APIRouter(prefix="/dedup", tags=["dedup"], dependencies=[Depends(get_current_user)])

REASON_LABELS = {
    "piva_identica": "P.IVA identica",
    "nome_e_via_identici": "Nome e via identici",
    "alert_simile": "Nome e indirizzo simili",
}


def _serialize_company(c: Company) -> dict:
    from app.routers.companies import _status_dinamico
    return {
        "id": str(c.id),
        "ragione_sociale": c.ragione_sociale,
        "partita_iva": c.partita_iva,
        "indirizzo": c.indirizzo,
        "citta": c.citta,
        "provincia": c.provincia,
        "paese": c.paese,
        "sap_customer_id": c.sap_customer_id,
        "sap_created_at": c.sap_created_at.isoformat() if c.sap_created_at else None,
        "origin": c.origin,
        "status": c.status,
        "status_dinamico": _status_dinamico(c),
    }


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db)):
    alerts = (
        db.query(DeduplicaAlert)
        .filter(DeduplicaAlert.resolved == False)
        .order_by(DeduplicaAlert.created_at.desc())
        .all()
    )
    result = []
    for a in alerts:
        if not a.company_a or not a.company_b:
            continue
        result.append({
            "id": str(a.id),
            "reason": a.reason,
            "reason_label": REASON_LABELS.get(a.reason, a.reason),
            "score_nome": a.score_nome,
            "score_via": a.score_via,
            "company_a": _serialize_company(a.company_a),
            "company_b": _serialize_company(a.company_b),
            "created_at": a.created_at.isoformat(),
        })
    return {"total": len(result), "items": result}


@router.post("/alerts/{alert_id}/merge")
def merge_alert(alert_id: str, data: dict, db: Session = Depends(get_db)):
    """data: { survivor_id: uuid }"""
    alert = db.query(DeduplicaAlert).filter(DeduplicaAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    if alert.resolved:
        raise HTTPException(status_code=400, detail="Alert già risolto")

    survivor_id = data.get("survivor_id")
    if str(alert.company_a_id) == survivor_id:
        survivor = alert.company_a
        duplicate = alert.company_b
    elif str(alert.company_b_id) == survivor_id:
        survivor = alert.company_b
        duplicate = alert.company_a
    else:
        raise HTTPException(status_code=400, detail="survivor_id non valido")

    merge_companies(survivor, duplicate, db)

    alert.resolved = True
    alert.resolved_action = "merged"
    db.commit()
    return {"ok": True, "survivor_id": str(survivor.id)}


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(DeduplicaAlert).filter(DeduplicaAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    alert.resolved = True
    alert.resolved_action = "dismissed"
    db.commit()
    return {"ok": True}
