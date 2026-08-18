from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.activity_log import ActivityLog
from app.auth import get_current_user, is_admin
from app.activity import ACTION_LABELS

router = APIRouter(prefix="/activity", tags=["activity"], dependencies=[Depends(get_current_user)])


@router.get("/")
def get_activity(
    date_from: str = Query(None),
    date_to:   str = Query(None),
    user_nome: str = Query(None),
    limit:     int = Query(200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_admin(current_user):
        return {"logs": [], "summary": {}}

    q = db.query(ActivityLog)
    if date_from:
        q = q.filter(ActivityLog.created_at >= date_from)
    if date_to:
        q = q.filter(ActivityLog.created_at < f"{date_to}T23:59:59")
    if user_nome:
        q = q.filter(ActivityLog.user_nome == user_nome)

    logs = q.order_by(ActivityLog.created_at.desc()).limit(limit).all()

    # Summary: count per user in the same period (ignoring user filter)
    sq = db.query(ActivityLog.user_nome, func.count(ActivityLog.id).label("cnt"))
    if date_from:
        sq = sq.filter(ActivityLog.created_at >= date_from)
    if date_to:
        sq = sq.filter(ActivityLog.created_at < f"{date_to}T23:59:59")
    summary = {row.user_nome: row.cnt for row in sq.group_by(ActivityLog.user_nome).all()}

    return {
        "logs": [_serialize(l) for l in logs],
        "summary": summary,
    }


def _serialize(l: ActivityLog):
    return {
        "id":           str(l.id),
        "user_nome":    l.user_nome,
        "action":       l.action,
        "action_label": ACTION_LABELS.get(l.action, l.action),
        "entity_type":  l.entity_type,
        "entity_id":    l.entity_id,
        "company_id":   l.company_id,
        "company_nome": l.company_nome,
        "detail":       l.detail or {},
        "created_at":   l.created_at.isoformat(),
    }
