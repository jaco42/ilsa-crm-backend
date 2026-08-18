from app.models.activity_log import ActivityLog

ACTION_LABELS = {
    "nota_creata":         "Nota creata",
    "contatto_creato":     "Contatto creato",
    "contatto_modificato": "Contatto modificato",
    "azienda_creata":      "Azienda creata",
    "radar_creato":        "Radar creato",
    "radar_modificato":    "Radar modificato",
}


def log_activity(
    db,
    user_nome: str,
    action: str,
    entity_type: str,
    entity_id: str = None,
    company_id: str = None,
    company_nome: str = None,
    detail: dict = None,
):
    if not user_nome:
        return
    entry = ActivityLog(
        user_nome=user_nome,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        company_id=str(company_id) if company_id else None,
        company_nome=company_nome,
        detail=detail or {},
    )
    db.add(entry)
