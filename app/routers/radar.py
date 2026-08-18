from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.radar import RadarProdotto, RadarSegnalazione
from app.models.company import Company
from app.auth import get_current_user, is_admin, _user_zone
from app.activity import log_activity

router = APIRouter(prefix="/radar", tags=["radar"], dependencies=[Depends(get_current_user)])


@router.get("/categorie")
def lista_categorie(db: Session = Depends(get_db)):
    rows = db.query(RadarProdotto.categoria_l1, RadarProdotto.categoria_l2)\
        .filter(RadarProdotto.merged_into_id == None)\
        .distinct().all()
    l1_set = sorted({r[0] for r in rows if r[0]})
    l2_by_l1 = defaultdict(set)
    for l1, l2 in rows:
        if l1 and l2:
            l2_by_l1[l1].add(l2)
    return {"l1": l1_set, "l2_by_l1": {k: sorted(v) for k, v in l2_by_l1.items()}}


@router.get("/")
def lista_radar(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    zone = _user_zone(current_user)
    admin = is_admin(current_user)

    prodotti = (
        db.query(RadarProdotto)
        .filter(RadarProdotto.merged_into_id == None)
        .options(joinedload(RadarProdotto.segnalazioni).joinedload(RadarSegnalazione.company))
        .order_by(RadarProdotto.nome)
        .all()
    )

    result = []
    for p in prodotti:
        visible = list(p.segnalazioni) if admin else [s for s in p.segnalazioni if s.zona in zone]
        if not visible:
            continue
        result.append(_serialize_prodotto(p, visible))
    return result


@router.get("/prodotti/search")
def search_prodotti(q: str = "", l1: str = "", l2: str = "", db: Session = Depends(get_db)):
    query = db.query(RadarProdotto).filter(RadarProdotto.merged_into_id == None)
    if q:
        query = query.filter(RadarProdotto.nome.ilike(f"%{q}%"))
    if l1:
        query = query.filter(RadarProdotto.categoria_l1 == l1)
    if l2:
        query = query.filter(RadarProdotto.categoria_l2 == l2)
    prodotti = query.order_by(RadarProdotto.nome).limit(10).all()
    return [{"id": str(p.id), "nome": p.nome, "categoria_l1": p.categoria_l1, "categoria_l2": p.categoria_l2} for p in prodotti]


@router.get("/{prodotto_id}")
def get_prodotto(prodotto_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    prodotto = db.query(RadarProdotto).filter(RadarProdotto.id == prodotto_id).first()
    if not prodotto:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")

    zone = _user_zone(current_user)
    admin = is_admin(current_user)

    q = db.query(RadarSegnalazione)\
        .filter(RadarSegnalazione.prodotto_id == prodotto_id)\
        .options(joinedload(RadarSegnalazione.company), joinedload(RadarSegnalazione.agente))
    if not admin:
        q = q.filter(RadarSegnalazione.zona.in_(zone))
    segnalazioni = q.order_by(RadarSegnalazione.created_at.desc()).all()

    return {
        "id": str(prodotto.id),
        "nome": prodotto.nome,
        "categoria_l1": prodotto.categoria_l1,
        "categoria_l2": prodotto.categoria_l2,
        "created_at": prodotto.created_at.isoformat(),
        "segnalazioni": [_serialize_segnalazione(s) for s in segnalazioni],
    }


@router.post("/prodotti")
def crea_prodotto(data: dict, db: Session = Depends(get_db)):
    prodotto = RadarProdotto(
        nome=data["nome"],
        categoria_l1=data.get("categoria_l1"),
        categoria_l2=data.get("categoria_l2"),
    )
    db.add(prodotto)
    db.commit()
    db.refresh(prodotto)
    return {"id": str(prodotto.id), "nome": prodotto.nome, "categoria_l1": prodotto.categoria_l1, "categoria_l2": prodotto.categoria_l2, "created_at": prodotto.created_at.isoformat()}


@router.post("/segnalazioni")
def crea_segnalazione(data: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    zona = data.get("zona")
    if not zona:
        company_id = data.get("company_id")
        if company_id:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company:
                user_zones = _user_zone(current_user)
                if company.agente_ilsa in user_zones:
                    zona = company.agente_ilsa
                elif company.agente_desco in user_zones:
                    zona = company.agente_desco

    s = RadarSegnalazione(
        prodotto_id=data["prodotto_id"],
        company_id=data["company_id"],
        quantita=data.get("quantita"),
        unita=data.get("unita"),
        urgenza=data.get("urgenza"),
        note=data.get("note"),
        zona=zona,
        created_by=data.get("created_by"),
        updated_by=data.get("updated_by"),
    )
    db.add(s)
    db.flush()
    company = db.query(Company).filter(Company.id == s.company_id).first() if s.company_id else None
    prodotto = db.query(RadarProdotto).filter(RadarProdotto.id == s.prodotto_id).first()
    log_activity(db, current_user.nome, "radar_creato", "radar",
                 entity_id=s.id, company_id=str(s.company_id) if s.company_id else None,
                 company_nome=company.ragione_sociale if company else None,
                 detail={
                     "prodotto": prodotto.nome if prodotto else None,
                     "prodotto_id": str(s.prodotto_id),
                     "l1": prodotto.categoria_l1 if prodotto else None,
                     "l2": prodotto.categoria_l2 if prodotto else None,
                     "quantita": s.quantita,
                     "unita": s.unita,
                     "note": (s.note or "")[:80] if s.note else None,
                 })
    db.commit()
    db.refresh(s)
    db.refresh(s, ["company", "agente"])
    return _serialize_segnalazione(s)


@router.patch("/segnalazioni/{segnalazione_id}")
def aggiorna_segnalazione(segnalazione_id: str, data: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    s = db.query(RadarSegnalazione).options(
        joinedload(RadarSegnalazione.company), joinedload(RadarSegnalazione.agente),
        joinedload(RadarSegnalazione.prodotto)
    ).filter(RadarSegnalazione.id == segnalazione_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    for key in ("quantita", "unita", "urgenza", "note", "updated_by"):
        if key in data:
            setattr(s, key, data[key])
    log_activity(db, current_user.nome, "radar_modificato", "radar",
                 entity_id=s.id, company_id=str(s.company_id) if s.company_id else None,
                 company_nome=s.company.ragione_sociale if s.company else None,
                 detail={
                     "prodotto": s.prodotto.nome if s.prodotto else None,
                     "prodotto_id": str(s.prodotto_id),
                     "l1": s.prodotto.categoria_l1 if s.prodotto else None,
                     "l2": s.prodotto.categoria_l2 if s.prodotto else None,
                     "quantita": s.quantita,
                     "unita": s.unita,
                     "note": (s.note or "")[:80] if s.note else None,
                 })
    db.commit()
    db.refresh(s)
    return _serialize_segnalazione(s)


@router.delete("/segnalazioni/{segnalazione_id}", status_code=204)
def elimina_segnalazione(segnalazione_id: str, db: Session = Depends(get_db)):
    s = db.query(RadarSegnalazione).filter(RadarSegnalazione.id == segnalazione_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    prodotto_id = s.prodotto_id
    db.delete(s)
    db.flush()
    remaining = db.query(RadarSegnalazione).filter(RadarSegnalazione.prodotto_id == prodotto_id).count()
    if remaining == 0:
        prodotto = db.query(RadarProdotto).filter(RadarProdotto.id == prodotto_id).first()
        if prodotto:
            db.delete(prodotto)
    db.commit()


def _serialize_prodotto(p: RadarProdotto, visible_segnalazioni=None):
    segnalazioni = visible_segnalazioni if visible_segnalazioni is not None else list(p.segnalazioni)
    urgenze = [s.urgenza for s in segnalazioni if s.urgenza]
    ultima = max((s.created_at for s in segnalazioni), default=None)
    return {
        "id": str(p.id),
        "nome": p.nome,
        "categoria_l1": p.categoria_l1,
        "categoria_l2": p.categoria_l2,
        "n_aziende": len(segnalazioni),
        "quantita_totale": _aggrega_quantita(segnalazioni),
        "urgenza_max": _urgenza_max(urgenze),
        "ultima_segnalazione": ultima.isoformat() if ultima else None,
        "created_at": p.created_at.isoformat(),
    }


def _serialize_segnalazione(s: RadarSegnalazione):
    return {
        "id": str(s.id),
        "prodotto_id": str(s.prodotto_id),
        "company_id": str(s.company_id),
        "company_name": s.company.ragione_sociale if s.company else None,
        "paese": s.company.paese if s.company else None,
        "quantita": s.quantita,
        "unita": s.unita,
        "urgenza": s.urgenza,
        "note": s.note,
        "zona": s.zona,
        "created_by": str(s.created_by) if s.created_by else None,
        "updated_by": s.updated_by,
        "created_at": s.created_at.isoformat(),
    }


def _urgenza_max(urgenze: list[str]) -> str | None:
    ordine = {"alta": 3, "media": 2, "bassa": 1}
    if not urgenze:
        return None
    return max(urgenze, key=lambda u: ordine.get(u, 0))


def _aggrega_quantita(segnalazioni) -> str | None:
    totali: dict[str, float] = defaultdict(float)
    for s in segnalazioni:
        if s.quantita is not None and s.unita:
            totali[s.unita] += s.quantita
    if not totali:
        return None
    return " · ".join(
        f"{int(v) if v == int(v) else v} {k}" for k, v in totali.items()
    )
