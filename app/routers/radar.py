from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.radar import RadarProdotto, RadarSegnalazione
from app.auth import get_current_user

router = APIRouter(prefix="/radar", tags=["radar"], dependencies=[Depends(get_current_user)])


@router.get("/")
def lista_radar(db: Session = Depends(get_db)):
    prodotti = (
        db.query(RadarProdotto)
        .filter(RadarProdotto.merged_into_id == None)
        .options(joinedload(RadarProdotto.segnalazioni).joinedload(RadarSegnalazione.company))
        .order_by(RadarProdotto.nome)
        .all()
    )
    return [_serialize_prodotto(p) for p in prodotti if p.segnalazioni]


@router.get("/prodotti/search")
def search_prodotti(q: str = "", db: Session = Depends(get_db)):
    prodotti = (
        db.query(RadarProdotto)
        .filter(RadarProdotto.merged_into_id == None)
        .filter(RadarProdotto.nome.ilike(f"%{q}%"))
        .order_by(RadarProdotto.nome)
        .limit(10)
        .all()
    )
    return [{"id": str(p.id), "nome": p.nome} for p in prodotti]


@router.get("/{prodotto_id}")
def get_prodotto(prodotto_id: str, db: Session = Depends(get_db)):
    prodotto = db.query(RadarProdotto).filter(RadarProdotto.id == prodotto_id).first()
    if not prodotto:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")
    segnalazioni = (
        db.query(RadarSegnalazione)
        .filter(RadarSegnalazione.prodotto_id == prodotto_id)
        .options(joinedload(RadarSegnalazione.company), joinedload(RadarSegnalazione.agente))
        .order_by(RadarSegnalazione.created_at.desc())
        .all()
    )
    return {
        "id": str(prodotto.id),
        "nome": prodotto.nome,
        "created_at": prodotto.created_at.isoformat(),
        "segnalazioni": [_serialize_segnalazione(s) for s in segnalazioni],
    }


@router.post("/prodotti")
def crea_prodotto(data: dict, db: Session = Depends(get_db)):
    prodotto = RadarProdotto(nome=data["nome"])
    db.add(prodotto)
    db.commit()
    db.refresh(prodotto)
    return {"id": str(prodotto.id), "nome": prodotto.nome, "created_at": prodotto.created_at.isoformat()}


@router.post("/segnalazioni")
def crea_segnalazione(data: dict, db: Session = Depends(get_db)):
    s = RadarSegnalazione(
        prodotto_id=data["prodotto_id"],
        company_id=data["company_id"],
        quantita=data.get("quantita"),
        unita=data.get("unita"),
        urgenza=data.get("urgenza"),
        note=data.get("note"),
        created_by=data.get("created_by"),
        updated_by=data.get("updated_by"),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    db.refresh(s, ["company", "agente"])
    return _serialize_segnalazione(s)


@router.patch("/segnalazioni/{segnalazione_id}")
def aggiorna_segnalazione(segnalazione_id: str, data: dict, db: Session = Depends(get_db)):
    s = db.query(RadarSegnalazione).options(
        joinedload(RadarSegnalazione.company), joinedload(RadarSegnalazione.agente)
    ).filter(RadarSegnalazione.id == segnalazione_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    for key in ("quantita", "unita", "urgenza", "note", "updated_by"):
        if key in data:
            setattr(s, key, data[key])
    db.commit()
    db.refresh(s)
    return _serialize_segnalazione(s)


@router.delete("/segnalazioni/{segnalazione_id}", status_code=204)
def elimina_segnalazione(segnalazione_id: str, db: Session = Depends(get_db)):
    s = db.query(RadarSegnalazione).filter(RadarSegnalazione.id == segnalazione_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    db.delete(s)
    db.commit()


def _serialize_prodotto(p: RadarProdotto):
    segnalazioni = list(p.segnalazioni)
    urgenze = [s.urgenza for s in segnalazioni if s.urgenza]
    ultima = max((s.created_at for s in segnalazioni), default=None)
    return {
        "id": str(p.id),
        "nome": p.nome,
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
