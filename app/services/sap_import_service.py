import io
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models.agent_assignment import AgentAssignment
from app.models.company import Company, CompanyOrigin, CompanyStatus
from app.models.company_sap_ids import CompanySapId
from app.models.line_item import LineItem
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.prodotto import Prodotto
from app.services.merge import find_and_handle_duplicate, score_match

log = logging.getLogger(__name__)

SEP = "|"
ENCODING = "latin-1"
STAGE_VINTO = "Chiuso Vinto"
STAGE_OFFERTA = "Offerta Mandata"

_TIPI_CONTRIBUISCE = {"ZOI0", "ZOC0", "ZOE0", "ZRII", "ZRIC", "ZRIE", "ZRAS"}
_NOTA_DA_TIPO = {
    "ZSOG": "Ord. sost. in garanzia",
    "ZFIN": "Invio conto fiera",
    "ZVIN": "Invio conto visione",
}
_SFRIDI_KW = ("sfridi", "fridi", "rottami", "rottame")
_ROYALTY_KW = ("importo dovuto da contratto",)


_RF_DESC = {
    "01": "Consegna fissata troppo tardi", "02": "Qualità scadente",
    "03": "Prezzo eccessivo", "04": "Fornitore con servizio migliore",
    "05": "Garanzia", "10": "Richieste irragionevoli",
    "11": "Consegna sostitutiva", "50": "Operazione sospesa per chiarimenti",
}


def _nota_riga(rf: str) -> str | None:
    rf = (rf.strip().lstrip("0") if rf else "").zfill(2)
    if not rf or rf == "00":
        return None
    return f"Prodotto annullato: {_RF_DESC.get(rf, f'Codice {rf}')}"


def _is_sfridi(d: str) -> bool:
    return any(kw in d.lower() for kw in _SFRIDI_KW) if d else False


def _is_royalty(d: str) -> bool:
    return any(kw in d.lower() for kw in _ROYALTY_KW) if d else False


# ---------------------------------------------------------------------------
# usecols — carica solo le colonne necessarie (-80÷97% RAM per DF)
# ---------------------------------------------------------------------------

_KNA1_COLS = {"Cliente", "Nome 1", "Nome 2", "Partita IVA 1", "Part.IVA", "Partita IVA",
              "Via", "Località", "Localit?", "CAP", "Rg", "Pse", "Telefono 1", "Data ap."}
_VBAK_COLS = {"Doc. vend.", "Committ.", "Val.netto", "Fine off.", "Data cr.", "Creato", "Data doc.", "OrgCm", "TpDV"}
_VBAP_COLS = {"Doc. vend.", "Materiale", "Definizione",
              "Qtà ordine", "Qt? ordine", "Qt ordine", "UM", "Prz. netto", "Val.netto",
              "Gerarchia prodotti", "Rf"}
_VBFA_COLS = {"Doc.prec.", "Doc. prec.", "Doc. succ.", "Doc.succ."}
_MARA_COLS = {"Materiale", "MATNR", "Gr.merci", "Gruppo merci", "MATKL", "Gr. merci"}

FILE_COLS = {
    "kna1": _KNA1_COLS, "vbak": _VBAK_COLS, "vbap": _VBAP_COLS,
    "vbfa": _VBFA_COLS, "mara": _MARA_COLS,
}


def load_csv_bytes(content: bytes, file_type: str = None) -> pd.DataFrame:
    try:
        sample = content.decode(ENCODING, errors="replace")
    except Exception:
        sample = content.decode("utf-8", errors="replace")
    lines = [l for l in sample.split("\n") if l.strip()]
    probe = lines[3] if len(lines) > 3 else (lines[0] if lines else "")
    sep = "\t" if probe.count("\t") > probe.count("|") else SEP

    needed = FILE_COLS.get(file_type) if file_type else None
    usecols = (lambda c: c.strip().strip("|").strip() in needed) if needed else None

    df = pd.read_csv(
        io.BytesIO(content), sep=sep, dtype=str, encoding=ENCODING,
        skiprows=3, skipinitialspace=True, on_bad_lines="skip", quoting=3,
        usecols=usecols,
    )
    df.columns = df.columns.str.strip().str.strip("|")
    for col in df.columns:
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        if s.dtype == object or str(s.dtype) in ("string", "str"):
            df[col] = s.str.strip().str.strip("|")
    return df.fillna("")


# ---------------------------------------------------------------------------
# Gerarchia prodotti → L1 / L2
# Fonte: listino Excel ILSA 2026 come master per L1.
# ---------------------------------------------------------------------------

_COMPLEMENTI_EXACT = {
    "COPFPFOR01_0001255",  # detergenti / accessori forno
    "COPFPFOR01_0001280",  # forni gas linea secondaria
    "COPFPFOR01_0001290",  # forni elettrici linea secondaria
    "COPFOFOR01_0001255",  # supporti, kit, guide forno
    "COPFZFOR01_0001255",  # teglie, portagriglie
    "COSLCFOR01_0001255",  # sonde al cuore per forni
}

_COTTURA_L2 = {
    "CUC": "Cucine",        "FOR": "Forni",
    "FRY": "Frytop",        "GRI": "Griglie",
    "GRE": "Griglie",       "FRI": "Friggitrici",
    "BRA": "Brasiere",      "TPS": "Tuttapiastra",
    "CUP": "Cuocipasta",    "PAS": "Cuocipasta",
    "BAG": "Bagnomaria",    "PEN": "Pentoloni",
    "COC": "Contenitori caldo", "NEU": "Neutri cottura",
    "SAM": "Salamandre",    "CAP": "Accessori cottura",
}

_REFRG_L2 = {
    "ABOV": "Abbattitori",
    "ARMA": "Armadi frigoriferi",
    "TAVR": "Tavoli refrigerati",
    "VETR": "Vetrine refrigerate",
    "ACFR": "Accessori frigo",
}

_LAVA_L2 = {
    "0000130": "Lavabicchieri / Lavapiatti",
    "0000131": "Lavastoviglie a cappotte",
    "0000132": "Lavaoggetti",
    "0000134": "Cestelli e accessori lavaggio",
}

_PSVEN_L2 = {
    "COTT": "Ricambi Cottura",
    "FRED": "Ricambi Freddo",
    "NEUT": "Ricambi Neutro",
    "COMU": "Ricambi Comuni",
}

_SPEC_L2 = {
    "PROD": "Speciali produzione - Prodotti su Misura",
    "COMM": "Speciali commerciali - Prodotti di Terzi",
}


def _gerarchia_to_famiglia(g: str):
    import re
    if not g:
        return None, None

    if g in _COMPLEMENTI_EXACT:
        return "Complementi", "Accessori forni"

    if g.startswith("COPF") or g.startswith("COTT"):
        m = (re.match(r"COPF[A-Z]([A-Z]{3})\d+", g)
             or re.match(r"COTT_([A-Z]{3})\d+", g)
             or re.match(r"COSLC([A-Z]{3})\d+", g))
        l2 = _COTTURA_L2.get(m.group(1) if m else "", "Accessori cottura")
        return "Cottura", l2
    if g.startswith("VARIE_COTT"):
        return "Cottura", "Accessori cottura"
    if g.startswith("COSLCSAM"):
        return "Cottura", "Salamandre"

    if g.startswith("REFRG"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Refrigerazione", _REFRG_L2.get(key, "Refrigerazione altro")
    if g.startswith("PZ_NE"):
        return "Refrigerazione", "Tavoli pizza"

    if g.startswith("CAPPE"):
        return "Neutro", "Cappe Aspirazione"
    if g.startswith("GN_"):
        return "Neutro", "Tavoli e Armadi"
    if g.startswith("PS_NE"):
        parts = g.split("_")
        sub = parts[2] if len(parts) > 2 else ""
        if sub.startswith("PS03") or sub.startswith("PS04"):
            return "Neutro", "Lavelli e Vasche"
        return "Neutro", "Piani di Lavoro"
    if g.startswith("VARIE_RIPI"):
        return "Neutro", "Ripiani"
    if g.startswith("VARIE_PENS"):
        return "Neutro", "Pensili"
    if g.startswith("VARIE_ARMN"):
        return "Neutro", "Armadi neutri"
    if g.startswith("VARIE_SCAF"):
        return "Neutro", "Scaffali"
    if g.startswith("VARIE_LVMN"):
        return "Neutro", "Lavamani"
    if g.startswith("VARIE_TEGL"):
        return "Neutro", "Teglie"
    if g.startswith("VARIE_ACGE"):
        return "Neutro", "Accessori e Kit"

    if g.startswith("PSVEN_NEUT"):
        return "Ricambi", "Ricambi Neutro"

    if g.startswith("LAVA_"):
        suffix = g.split("_")[-1] if "_" in g else ""
        return "Complementi", _LAVA_L2.get(suffix, "Lavaggio")
    if g.startswith("VARIE_COMM"):
        return "Complementi", "Fabbricatori ghiaccio"

    if g.startswith("PSVEN"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Ricambi", _PSVEN_L2.get(key, "Ricambi Generali")

    if g.startswith("SPEC_"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Speciali", _SPEC_L2.get(key, "Speciali")

    if g.startswith("SELF_"):
        return "Self Service", "Self service"

    return "Trasporti", "Trasporti"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(row, *names: str) -> str:
    for name in names:
        if name not in row:
            continue
        val = row[name]
        if isinstance(val, pd.Series):
            val = val.iloc[0]
        if val and str(val).strip():
            return str(val).strip()
    return ""


def parse_decimal(val: str):
    if not val:
        return None
    val = val.replace(".", "").replace(",", ".")
    try:
        return float(val)
    except ValueError:
        return None


def parse_date(val: str):
    if not val:
        return None
    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            d = datetime.strptime(val, fmt).date()
            return None if d.year > 2100 else d
        except ValueError:
            continue
    return None


def _flusso_series(df: pd.DataFrame, *candidates: str) -> pd.Series:
    for c in candidates:
        if c in df.columns:
            return df[c].str.strip()
    raise KeyError(
        f"Colonna VBFA non trovata (cercato: {candidates}). "
        f"Colonne disponibili: {list(df.columns)}"
    )


def load_mara_lookup(content: bytes) -> dict:
    """Ritorna {codice_sap: gr_merci} da MARA (non più usato per L1/L2, tenuto per compat)."""
    try:
        df = load_csv_bytes(content, file_type="mara")
    except Exception:
        return {}
    lookup = {}
    for _, row in df.iterrows():
        codice = get(row, "Materiale", "MATNR")
        gr = get(row, "Gr.merci", "Gruppo merci", "MATKL", "Gr. merci")
        if codice and gr:
            lookup[codice] = gr
    return lookup


def classify_customer_code(codice: str) -> str:
    if not codice.isnumeric():
        return "special"
    n = int(codice)
    if n < 900_000:
        return "cliente"
    if n < 1_000_000:
        return "skip"
    if n < 2_000_000:
        return "dest_merci"
    if n <= 3_000_000:
        return "prospect"
    return "skip"


def _build_companies_lookup(db) -> dict:
    lookup = {
        c.sap_customer_id: c
        for c in db.query(Company).filter(Company.sap_customer_id.isnot(None)).all()
    }
    for sec in db.query(CompanySapId).all():
        if sec.sap_customer_id not in lookup and sec.company:
            lookup[sec.sap_customer_id] = sec.company
    return lookup


def _changed(obj, field: str, new_val) -> bool:
    if new_val is None:
        return False
    current = getattr(obj, field, None)
    if current is None:
        return True
    return str(current) != str(new_val)


def _build_posizioni_index(posizioni: pd.DataFrame) -> dict:
    """O(N) compact index {doc_id: [tuple di 7 campi]}.
    Usa tuple invece di Series: ~5x meno RAM, DataFrame liberabile subito dopo."""
    index = {}
    for _, riga in posizioni.iterrows():
        doc_id = get(riga, "Doc. vend.")
        if not doc_id:
            continue
        if doc_id not in index:
            index[doc_id] = []
        index[doc_id].append((
            get(riga, "Materiale"),
            get(riga, "Definizione"),
            get(riga, "Qtà ordine", "Qt? ordine", "Qt ordine"),
            get(riga, "UM"),
            get(riga, "Prz. netto"),
            get(riga, "Val.netto"),
            get(riga, "Gerarchia prodotti"),
            get(riga, "Rf"),
        ))
    return index


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def import_companies_stream(clienti: pd.DataFrame, db: Session):
    import uuid as _uuid
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import func as _func, case as _case

    skipped = 0

    # Pre-carica esistenti e secondari in 2 query
    existing_sap_ids = set(
        r[0] for r in db.query(Company.sap_customer_id)
        .filter(Company.sap_customer_id.isnot(None)).all()
    )
    secondaries = {}
    for sec in db.query(CompanySapId).all():
        if sec.company:
            secondaries[sec.sap_customer_id] = sec.company

    yield {"inserted": 0, "already_present": 0, "identical": 0, "skipped": 0, "processed": 0, "total": 0}

    # Fase 1: parsing righe in Python
    all_rows = []
    secondary_rows = []
    _records = clienti.to_dict('records')
    for row in _records:
        codice_cliente = (row.get("Cliente") or "").strip()
        if not codice_cliente:
            skipped += 1
            continue
        tipo = classify_customer_code(codice_cliente)
        if tipo in ("dest_merci", "skip"):
            skipped += 1
            continue

        nome1 = (row.get("Nome 1") or "").strip()
        nome2 = (row.get("Nome 2") or "").strip()
        ragione_sociale = f"{nome1} {nome2}".strip() if nome2 else nome1
        if not ragione_sociale:
            ragione_sociale = f"Cliente SAP {codice_cliente}"

        piva = get(row, "Partita IVA 1", "Part.IVA", "Partita IVA") or None
        entry = {
            "id": _uuid.uuid4(),
            "sap_customer_id": codice_cliente,
            "ragione_sociale": ragione_sociale,
            "indirizzo": get(row, "Via") or None,
            "citta": get(row, "Località", "Localit?") or None,
            "cap": get(row, "CAP") or None,
            "provincia": get(row, "Rg") or None,
            "paese": get(row, "Pse") or None,
            "telefono": get(row, "Telefono 1") or None,
            "partita_iva": piva,
            "sap_created_at": parse_date(get(row, "Data ap.")),
            "status": CompanyStatus.cliente if tipo == "cliente" else CompanyStatus.prospect,
            "origin": CompanyOrigin.sap_sync,
            "created_by": "SAP",
        }

        if codice_cliente not in existing_sap_ids and codice_cliente in secondaries:
            secondary_rows.append((secondaries[codice_cliente], entry))
        else:
            all_rows.append(entry)

    inserted_count = sum(1 for r in all_rows if r["sap_customer_id"] not in existing_sap_ids)
    already_present_count = len(all_rows) - inserted_count
    _valid_total = len(all_rows)
    yield {"inserted": inserted_count, "already_present": already_present_count, "identical": 0,
           "skipped": skipped, "processed": 0, "total": _valid_total}

    # Fase 2: bulk upsert — CASE preserva telefono_override e non degrada status
    _CHUNK = 2000
    for ci in range(0, _valid_total, _CHUNK):
        chunk = all_rows[ci:ci + _CHUNK]
        stmt = pg_insert(Company).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sap_customer_id"],
            set_={
                "ragione_sociale":  stmt.excluded.ragione_sociale,
                "indirizzo":        stmt.excluded.indirizzo,
                "citta":            stmt.excluded.citta,
                "cap":              stmt.excluded.cap,
                "provincia":        stmt.excluded.provincia,
                "paese":            stmt.excluded.paese,
                "partita_iva":      stmt.excluded.partita_iva,
                "sap_created_at":   stmt.excluded.sap_created_at,
                "origin":           stmt.excluded.origin,
                "telefono": _case(
                    (Company.__table__.c.telefono_override == True,
                     Company.__table__.c.telefono),
                    else_=stmt.excluded.telefono,
                ),
                "status": _case(
                    ((Company.__table__.c.status == 'cliente') &
                     (stmt.excluded.status == 'prospect'),
                     Company.__table__.c.status),
                    else_=stmt.excluded.status,
                ),
                "updated_at": _func.now(),
            }
        )
        db.execute(stmt)
        db.commit()
        yield {"inserted": inserted_count, "already_present": already_present_count, "identical": 0,
               "skipped": skipped, "processed": ci + len(chunk), "total": _valid_total}

    # Fase 3: secondary SAP IDs — aggiorna campi vuoti sul survivor
    sec_updated = 0
    for survivor, data in secondary_rows:
        fill_fields = ["partita_iva", "indirizzo", "citta", "cap", "provincia", "paese", "sap_created_at"]
        if not survivor.telefono_override:
            fill_fields.append("telefono")
        changed_fields = [f for f in fill_fields if not getattr(survivor, f) and data.get(f)]
        for f in changed_fields:
            setattr(survivor, f, data[f])
        if changed_fields:
            sec_updated += 1
    if secondary_rows:
        db.commit()

    log.info(f"Companies:  {inserted_count} inserite  |  {already_present_count} già presenti  |  {skipped} saltate  |  {sec_updated} secondary aggiornate")


def import_companies(clienti: pd.DataFrame, db: Session) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for partial in import_companies_stream(clienti, db):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# Prodotti
# ---------------------------------------------------------------------------

def import_prodotti_stream(posizioni: pd.DataFrame, db: Session):
    inserted = updated = identical = 0
    deduped = posizioni.drop_duplicates(subset=["Materiale"])
    total = len(deduped)

    # Pre-carica tutti i prodotti esistenti in 1 query
    existing = {p.codice_sap: p for p in db.query(Prodotto).all()}

    to_insert = []
    for i, (_, row) in enumerate(deduped.iterrows()):
        codice = get(row, "Materiale")
        if not codice:
            continue
        nome = get(row, "Definizione") or codice
        prodotto = existing.get(codice)
        if prodotto:
            if prodotto.nome != nome:
                prodotto.nome = nome
                updated += 1
            else:
                identical += 1
        else:
            to_insert.append(Prodotto(codice_sap=codice, nome=nome, attivo=True))
            inserted += 1

        if (i + 1) % 500 == 0 or i == total - 1:
            yield {"inserted": inserted, "updated": updated, "identical": identical, "skipped": 0,
                   "processed": i + 1, "total": total}

    if to_insert:
        db.add_all(to_insert)
    db.commit()
    log.info(f"Prodotti:   {inserted} inseriti  |  {updated} aggiornati  |  {identical} identici")


def import_prodotti(posizioni: pd.DataFrame, db: Session) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for partial in import_prodotti_stream(posizioni, db):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# Offerte
# ---------------------------------------------------------------------------

def import_offerte_stream(offerte: pd.DataFrame, posizioni_by_doc: dict, offerte_vinte: set, db: Session, mara_lookup: dict = None):
    import time as _time
    import uuid as _uuid
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import func as _func

    skipped = 0
    companies = _build_companies_lookup(db)
    total = len(offerte)

    existing_sap_ids = set(
        r[0] for r in db.query(Opportunity.sap_document_id)
        .filter(Opportunity.sap_document_id.isnot(None)).all()
    )

    # Fase 1: costruisci tutte le righe in Python — 0ms, nessun DB
    t0 = _time.monotonic()
    all_rows = []
    _records = offerte.to_dict('records')
    for row in _records:
        sap_doc_id = row.get("Doc. vend.") or ""
        if not sap_doc_id:
            skipped += 1
            continue
        company = companies.get(row.get("Committ.") or "")
        if not company:
            skipped += 1
            continue
        stage = STAGE_VINTO if sap_doc_id in offerte_vinte else STAGE_OFFERTA
        tipo_doc = row.get("TpDV") or None
        all_rows.append({
            "id": _uuid.uuid4(),
            "company_id": company.id,
            "sap_document_id": sap_doc_id,
            "stage": stage,
            "tipo_doc": tipo_doc,
            "org_cm": row.get("OrgCm") or None,
            "valore_totale": parse_decimal(row.get("Val.netto") or ""),
            "data_scadenza": None if stage == STAGE_VINTO else parse_date(row.get("Fine off.") or ""),
            "data_creazione_sap": parse_date(row.get("Data cr.") or ""),
            "sap_creato_da": row.get("Creato") or None,
        })
    inserted_count = sum(1 for r in all_rows if r["sap_document_id"] not in existing_sap_ids)
    already_present_count = len(all_rows) - inserted_count
    log.info(f"[T] build rows: {_time.monotonic()-t0:.2f}s  ({len(all_rows)} valid, {skipped} skip)")
    yield {"inserted": inserted_count, "already_present": already_present_count, "identical": 0, "skipped": skipped,
           "processed": len(all_rows), "total": total}

    # Fase 2: upsert in chunk — 1 query SQL per chunk, non N query
    _UPSERT_CHUNK = 2000
    upserted = 0
    t_upsert = _time.monotonic()
    for ci in range(0, len(all_rows), _UPSERT_CHUNK):
        chunk = all_rows[ci:ci + _UPSERT_CHUNK]
        t_c = _time.monotonic()
        stmt = pg_insert(Opportunity).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sap_document_id"],
            set_={
                "company_id":        stmt.excluded.company_id,
                "stage":             stmt.excluded.stage,
                "tipo_doc":          _func.coalesce(stmt.excluded.tipo_doc, Opportunity.__table__.c.tipo_doc),
                "org_cm":            stmt.excluded.org_cm,
                "valore_totale":     stmt.excluded.valore_totale,
                "data_scadenza":     stmt.excluded.data_scadenza,
                "data_creazione_sap":stmt.excluded.data_creazione_sap,
                "sap_creato_da":     stmt.excluded.sap_creato_da,
                "updated_at":        _func.now(),
            }
        )
        db.execute(stmt)
        db.commit()
        upserted += len(chunk)
        log.info(f"[T] upsert chunk {ci}-{ci+len(chunk)}: {_time.monotonic()-t_c:.2f}s")
        yield {"inserted": inserted_count, "already_present": already_present_count, "identical": 0, "skipped": skipped,
               "processed": upserted, "total": total}
    log.info(f"[T] upsert totale {len(all_rows)} opp: {_time.monotonic()-t_upsert:.2f}s")

    # Fase 3: ricarica gli id (include nuovi inseriti) per i line items
    t0 = _time.monotonic()
    existing_opps = {
        sap_id: opp_id
        for opp_id, sap_id in db.query(Opportunity.id, Opportunity.sap_document_id)
                                 .filter(Opportunity.sap_document_id.isnot(None)).all()
    }
    log.info(f"[T] reload ids: {_time.monotonic()-t0:.2f}s")

    processed_doc_ids = [r["sap_document_id"] for r in all_rows]
    n_docs = len(processed_doc_ids)

    # Fase 4: line items — bulk INSERT dicts, no ORM tracking
    _CHUNK = 300
    total_li = 0
    for ci in range(0, n_docs, _CHUNK):
        chunk_doc_ids = processed_doc_ids[ci:ci + _CHUNK]
        chunk_opp_ids = [existing_opps[d] for d in chunk_doc_ids if d in existing_opps]
        if chunk_opp_ids:
            db.query(LineItem).filter(
                LineItem.opportunity_id.in_(chunk_opp_ids),
                LineItem.document_type == 'offer',
            ).delete(synchronize_session=False)
        chunk_li = []
        for doc_id in chunk_doc_ids:
            opp_id = existing_opps.get(doc_id)
            if not opp_id:
                continue
            for (codice, definizione, qty, um, prz, val, gerarchia, rf) in posizioni_by_doc.get(doc_id, []):
                l1, l2 = _gerarchia_to_famiglia(gerarchia)
                chunk_li.append({
                    "id": _uuid.uuid4(),
                    "document_type": "offer",
                    "opportunity_id": opp_id,
                    "codice_sap": codice or None,
                    "descrizione_riga": definizione or None,
                    "quantita": parse_decimal(qty),
                    "unita_misura": um or None,
                    "prezzo_unitario": parse_decimal(prz),
                    "totale_riga": parse_decimal(val),
                    "categoria": l1,
                    "prodotto": l2,
                    "nota": _nota_riga(rf),
                })
        if chunk_li:
            db.execute(pg_insert(LineItem).values(chunk_li))
        db.commit()
        total_li += len(chunk_li)
        yield {"inserted": inserted_count, "already_present": already_present_count, "identical": 0, "skipped": skipped,
               "processed": ci + len(chunk_doc_ids), "total": n_docs}

    log.info(f"Offerte:    {upserted} upsertate  |  {skipped} saltate  |  {total_li} righe")


def import_offerte(offerte: pd.DataFrame, posizioni: pd.DataFrame, offerte_vinte: set, db: Session, mara_lookup: dict = None) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    posizioni_by_doc = _build_posizioni_index(posizioni)
    for partial in import_offerte_stream(offerte, posizioni_by_doc, offerte_vinte, db, mara_lookup):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# Ordini
# ---------------------------------------------------------------------------

def import_ordini_stream(ordini: pd.DataFrame, posizioni_by_doc: dict, offerta_per_ordine: dict, db: Session, mara_lookup: dict = None):
    import time as _time
    import uuid as _uuid
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import func as _func, case as _case

    skipped = 0
    companies = _build_companies_lookup(db)
    total = len(ordini)

    existing_order_sap_ids = set(
        r[0] for r in db.query(Order.sap_document_id)
        .filter(Order.sap_document_id.isnot(None)).all()
    )

    opp_id_by_doc = {
        sap_id: (opp_id, stage)
        for opp_id, sap_id, stage in db.query(Opportunity.id, Opportunity.sap_document_id, Opportunity.stage)
                                        .filter(Opportunity.sap_document_id.isnot(None)).all()
    }

    # Fase 1: costruisci tutte le righe in Python
    t0 = _time.monotonic()
    all_rows = []
    opp_ids_to_win = []
    _records = ordini.to_dict('records')
    for row in _records:
        sap_doc_id = row.get("Doc. vend.") or ""
        if not sap_doc_id:
            skipped += 1
            continue
        company = companies.get(row.get("Committ.") or "")
        if not company:
            skipped += 1
            continue
        sap_offerta_id = offerta_per_ordine.get(sap_doc_id)
        opp_entry = opp_id_by_doc.get(sap_offerta_id) if sap_offerta_id else None
        opp_id = opp_entry[0] if opp_entry else None
        opp_stage = opp_entry[1] if opp_entry else None
        tipo_doc = row.get("TpDV") or None
        if tipo_doc is not None:
            if tipo_doc == "ZAMM":
                righe = posizioni_by_doc.get(sap_doc_id, [])
                has_special = any(_is_sfridi(r[1]) or _is_royalty(r[1]) for r in righe)
                if not has_special:
                    skipped += 1
                    continue
                contribuisce = True
            else:
                contribuisce = tipo_doc in _TIPI_CONTRIBUISCE
        else:
            contribuisce = True
        all_rows.append({
            "id": _uuid.uuid4(),
            "company_id": company.id,
            "opportunity_id": opp_id,
            "sap_document_id": sap_doc_id,
            "tipo_doc": tipo_doc,
            "nota": _NOTA_DA_TIPO.get(tipo_doc) if tipo_doc else None,
            "contribuisce_fatturato": contribuisce,
            "org_cm": row.get("OrgCm") or None,
            "valore_totale": parse_decimal(row.get("Val.netto") or ""),
            "data_ordine": parse_date(row.get("Data doc.") or ""),
            "data_creazione_sap": parse_date(row.get("Data cr.") or ""),
            "sap_creato_da": row.get("Creato") or None,
        })
        if opp_id and opp_stage == STAGE_OFFERTA:
            opp_ids_to_win.append(opp_id)
    ord_inserted_count = sum(1 for r in all_rows if r["sap_document_id"] not in existing_order_sap_ids)
    ord_already_present_count = len(all_rows) - ord_inserted_count
    log.info(f"[T] build rows ordini: {_time.monotonic()-t0:.2f}s  ({len(all_rows)} valid, {skipped} skip)")
    yield {"inserted": ord_inserted_count, "already_present": ord_already_present_count, "identical": 0, "skipped": skipped,
           "processed": len(all_rows), "total": total}

    # Fase 2: upsert in chunk
    _UPSERT_CHUNK = 2000
    upserted = 0
    t_upsert = _time.monotonic()
    for ci in range(0, len(all_rows), _UPSERT_CHUNK):
        chunk = all_rows[ci:ci + _UPSERT_CHUNK]
        stmt = pg_insert(Order).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sap_document_id"],
            set_={
                "company_id":            stmt.excluded.company_id,
                "opportunity_id":        stmt.excluded.opportunity_id,
                "tipo_doc":              _func.coalesce(stmt.excluded.tipo_doc, Order.__table__.c.tipo_doc),
                "nota":                  _func.coalesce(stmt.excluded.nota, Order.__table__.c.nota),
                "contribuisce_fatturato": _case(
                    (stmt.excluded.tipo_doc.isnot(None), stmt.excluded.contribuisce_fatturato),
                    else_=Order.__table__.c.contribuisce_fatturato,
                ),
                "org_cm":                stmt.excluded.org_cm,
                "valore_totale":         stmt.excluded.valore_totale,
                "data_ordine":           stmt.excluded.data_ordine,
                "data_creazione_sap":    stmt.excluded.data_creazione_sap,
                "sap_creato_da":         stmt.excluded.sap_creato_da,
                "updated_at":            _func.now(),
            }
        )
        db.execute(stmt)
        upserted += len(chunk)
    if opp_ids_to_win:
        db.query(Opportunity).filter(Opportunity.id.in_(opp_ids_to_win)).update(
            {"stage": STAGE_VINTO}, synchronize_session=False
        )
    db.commit()
    log.info(f"[T] upsert ordini {len(all_rows)}: {_time.monotonic()-t_upsert:.2f}s")
    yield {"inserted": ord_inserted_count, "already_present": ord_already_present_count, "identical": 0, "skipped": skipped,
           "processed": upserted, "total": total}

    # Fase 3: ricarica ids per line items
    existing_orders = {
        sap_id: order_id
        for order_id, sap_id in db.query(Order.id, Order.sap_document_id)
                                   .filter(Order.sap_document_id.isnot(None)).all()
    }
    processed_doc_ids = [r["sap_document_id"] for r in all_rows]
    tipo_doc_by_sap_id = {r["sap_document_id"]: r.get("tipo_doc") for r in all_rows}
    n_docs = len(processed_doc_ids)

    # Fase 4: line items — bulk INSERT dicts, no ORM tracking
    _CHUNK = 300
    total_li = 0
    for ci in range(0, n_docs, _CHUNK):
        chunk_doc_ids = processed_doc_ids[ci:ci + _CHUNK]
        chunk_order_ids = [existing_orders[d] for d in chunk_doc_ids if d in existing_orders]
        if chunk_order_ids:
            db.query(LineItem).filter(
                LineItem.order_id.in_(chunk_order_ids),
                LineItem.document_type == 'order',
            ).delete(synchronize_session=False)
        chunk_li = []
        for doc_id in chunk_doc_ids:
            order_id = existing_orders.get(doc_id)
            if not order_id:
                continue
            tipo_doc = tipo_doc_by_sap_id.get(doc_id)
            for (codice, definizione, qty, um, prz, val, gerarchia, rf) in posizioni_by_doc.get(doc_id, []):
                if tipo_doc == "ZAMM":
                    if _is_royalty(definizione):
                        l1, l2 = "Royalties", "Royalties"
                    elif _is_sfridi(definizione):
                        l1, l2 = "Vendita Sfridi", "Vendita Sfridi"
                    else:
                        continue
                elif tipo_doc == "ZRAS":
                    l1, l2 = "Riparazioni", "Riparazioni"
                else:
                    l1, l2 = _gerarchia_to_famiglia(gerarchia)
                chunk_li.append({
                    "id": _uuid.uuid4(),
                    "document_type": "order",
                    "order_id": order_id,
                    "codice_sap": codice or None,
                    "descrizione_riga": definizione or None,
                    "quantita": parse_decimal(qty),
                    "unita_misura": um or None,
                    "prezzo_unitario": parse_decimal(prz),
                    "totale_riga": parse_decimal(val),
                    "categoria": l1,
                    "prodotto": l2,
                    "nota": _nota_riga(rf) or _NOTA_DA_TIPO.get(tipo_doc),
                })
        if chunk_li:
            db.execute(pg_insert(LineItem).values(chunk_li))
        db.commit()
        total_li += len(chunk_li)
        yield {"inserted": ord_inserted_count, "already_present": ord_already_present_count, "identical": 0, "skipped": skipped,
               "processed": ci + len(chunk_doc_ids), "total": n_docs}

    log.info(f"Ordini:     {upserted} upsertati  |  {skipped} saltati  |  {total_li} righe")


def import_ordini(ordini: pd.DataFrame, posizioni: pd.DataFrame, offerta_per_ordine: dict, db: Session, mara_lookup: dict = None) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    posizioni_by_doc = _build_posizioni_index(posizioni)
    for partial in import_ordini_stream(ordini, posizioni_by_doc, offerta_per_ordine, db, mara_lookup):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# run_import_core — endpoint non-streaming
# ---------------------------------------------------------------------------

def run_import_core(clienti: pd.DataFrame, docvend: pd.DataFrame, posizioni: pd.DataFrame, flusso: pd.DataFrame, db: Session, mara_lookup: dict = None) -> dict:
    offerte = docvend[docvend["Doc. vend."].str.startswith("5")].copy()
    ordini  = docvend[docvend["Doc. vend."].str.startswith("1")].copy()
    prec = _flusso_series(flusso, "Doc.prec.", "Doc. prec.")
    succ = _flusso_series(flusso, "Doc. succ.", "Doc.succ.")
    offerte_vinte      = set(prec.unique())
    offerta_per_ordine = dict(zip(succ, prec))

    log.info(f"Avvio import: {len(clienti)} clienti, {len(offerte)} offerte, {len(ordini)} ordini, {len(posizioni)} posizioni")

    companies_r = import_companies(clienti, db)
    prodotti_r  = import_prodotti(posizioni, db)
    posizioni_by_doc = _build_posizioni_index(posizioni)

    offerte_r = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for p in import_offerte_stream(offerte, posizioni_by_doc, offerte_vinte, db, mara_lookup):
        offerte_r = p
    offerte_r = {k: offerte_r[k] for k in ["inserted", "updated", "identical", "skipped"]}

    ordini_r = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for p in import_ordini_stream(ordini, posizioni_by_doc, offerta_per_ordine, db, mara_lookup):
        ordini_r = p
    ordini_r = {k: ordini_r[k] for k in ["inserted", "updated", "identical", "skipped"]}

    return {"companies": companies_r, "prodotti": prodotti_r, "offerte": offerte_r, "ordini": ordini_r}


def import_knvv(content: bytes, db: Session) -> dict:
    """Importa KNVV (agent assignments). Svuota e ricarica la tabella ad ogni import."""
    text = None
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except Exception:
            continue

    rows = {}
    for line in text.splitlines():
        if not line.startswith("|") or not line.endswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4 or parts[0] == "Cliente":
            continue
        cliente_sap, org_cm, zn = parts[0], parts[1], parts[3]
        if not cliente_sap or not org_cm or not zn:
            continue
        if (cliente_sap, org_cm) not in rows:
            rows[(cliente_sap, org_cm)] = zn

    db.query(AgentAssignment).delete()
    for (cliente_sap, org_cm), zn in rows.items():
        db.add(AgentAssignment(cliente_sap=cliente_sap, org_cm=org_cm, zn=zn))

    from app.models.company import Company
    from collections import defaultdict
    ilsa = {cs: zn for (cs, org), zn in rows.items() if org == "OC00"}
    desco = {cs: zn for (cs, org), zn in rows.items() if org == "OC02"}

    # Raggruppa per agente → un UPDATE per agente invece di uno per cliente
    ilsa_groups: dict[str, list] = defaultdict(list)
    for cs, zn in ilsa.items():
        ilsa_groups[zn].append(cs)
    desco_groups: dict[str, list] = defaultdict(list)
    for cs, zn in desco.items():
        desco_groups[zn].append(cs)

    updated = 0
    for agente, sap_ids in ilsa_groups.items():
        updated += db.query(Company).filter(Company.sap_customer_id.in_(sap_ids)).update(
            {"agente_ilsa": agente, "agente_ilsa_locked": True}, synchronize_session=False
        )
    for agente, sap_ids in desco_groups.items():
        updated += db.query(Company).filter(Company.sap_customer_id.in_(sap_ids)).update(
            {"agente_desco": agente, "agente_desco_locked": True}, synchronize_session=False
        )

    db.commit()
    return {"inserted": len(rows), "aziende_aggiornate": updated}
