import csv
import io
import json
import uuid
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user, require_admin
from app.models.contact import Contact
from app.models.company import Company, CompanyStatus, CompanyOrigin
from app.models.note import Note
from app.models.import_log import ImportLog

router = APIRouter(prefix="/import", tags=["import"], dependencies=[Depends(get_current_user)])

CONTACT_FIELDS = [
    {"key": "nome",        "label": "Nome"},
    {"key": "company",     "label": "Azienda (ragione sociale)"},
    {"key": "ruolo",       "label": "Ruolo"},
    {"key": "email",       "label": "Email"},
    {"key": "telefono",    "label": "Telefono"},
    {"key": "note",              "label": "Note contatto"},
    {"key": "storico_contatti",  "label": "Storico contatti"},
]

COMPANY_FIELDS = [
    {"key": "ragione_sociale", "label": "Ragione sociale"},
    {"key": "partita_iva",     "label": "Partita IVA"},
    {"key": "indirizzo",       "label": "Indirizzo"},
    {"key": "citta",           "label": "Città"},
    {"key": "cap",             "label": "CAP"},
    {"key": "provincia",       "label": "Provincia"},
    {"key": "paese",           "label": "Paese"},
    {"key": "telefono",        "label": "Telefono"},
    {"key": "email",           "label": "Email"},
    {"key": "tipo_attivita",   "label": "Tipo attività"},
    {"key": "storico_contatti", "label": "Storico contatti"},
    {"key": "nota",             "label": "Nota"},
]

_COMPANY_SNAP_FIELDS = [
    "ragione_sociale", "partita_iva", "indirizzo", "citta", "cap",
    "provincia", "paese", "telefono", "email", "tipo_attivita", "storico_contatti",
]
_CONTACT_SNAP_FIELDS = [
    "nome", "ruolo", "email", "telefono", "storico_contatti",
]


_PAESE_MAP = {
    "italia": "IT", "italy": "IT", "italie": "IT",
    "germania": "DE", "germany": "DE", "deutschland": "DE",
    "francia": "FR", "france": "FR",
    "spagna": "ES", "spain": "ES", "españa": "ES",
    "svizzera": "CH", "switzerland": "CH", "schweiz": "CH",
    "austria": "AT", "oesterreich": "AT", "österreich": "AT",
    "belgio": "BE", "belgium": "BE", "belgique": "BE",
    "paesi bassi": "NL", "olanda": "NL", "netherlands": "NL",
    "portogallo": "PT", "portugal": "PT",
    "regno unito": "GB", "uk": "GB", "great britain": "GB",
    "stati uniti": "US", "usa": "US", "united states": "US",
    "cina": "CN", "china": "CN",
    "giappone": "JP", "japan": "JP",
    "polonia": "PL", "poland": "PL",
    "repubblica ceca": "CZ", "czech republic": "CZ",
    "slovacchia": "SK", "slovakia": "SK",
    "ungheria": "HU", "hungary": "HU",
    "romania": "RO",
    "croazia": "HR", "croatia": "HR",
    "slovenia": "SI",
    "grecia": "GR", "greece": "GR",
    "turchia": "TR", "turkey": "TR",
    "russia": "RU",
    "brasile": "BR", "brazil": "BR",
    "messico": "MX", "mexico": "MX",
    "canada": "CA",
    "australia": "AU",
    "india": "IN",
}

_PROVINCIA_MAP = {
    "agrigento": "AG", "alessandria": "AL", "ancona": "AN", "aosta": "AO",
    "arezzo": "AR", "ascoli piceno": "AP", "asti": "AT", "avellino": "AV",
    "bari": "BA", "barletta": "BT", "belluno": "BL", "benevento": "BN",
    "bergamo": "BG", "biella": "BI", "bologna": "BO", "bolzano": "BZ",
    "brescia": "BS", "brindisi": "BR", "cagliari": "CA", "caltanissetta": "CL",
    "campobasso": "CB", "caserta": "CE", "catania": "CT", "catanzaro": "CZ",
    "chieti": "CH", "como": "CO", "cosenza": "CS", "cremona": "CR",
    "crotone": "KR", "cuneo": "CN", "enna": "EN", "fermo": "FM",
    "ferrara": "FE", "firenze": "FI", "foggia": "FG", "forlì": "FC",
    "forli": "FC", "frosinone": "FR", "genova": "GE", "gorizia": "GO",
    "grosseto": "GR", "imperia": "IM", "isernia": "IS", "la spezia": "SP",
    "l'aquila": "AQ", "aquila": "AQ", "latina": "LT", "lecce": "LE",
    "lecco": "LC", "livorno": "LI", "lodi": "LO", "lucca": "LU",
    "macerata": "MC", "mantova": "MN", "massa": "MS", "matera": "MT",
    "messina": "ME", "milano": "MI", "modena": "MO", "monza": "MB",
    "napoli": "NA", "novara": "NO", "nuoro": "NU", "oristano": "OR",
    "padova": "PD", "palermo": "PA", "parma": "PR", "pavia": "PV",
    "perugia": "PG", "pesaro": "PU", "pescara": "PE", "piacenza": "PC",
    "pisa": "PI", "pistoia": "PT", "pordenone": "PN", "potenza": "PZ",
    "prato": "PO", "ragusa": "RG", "ravenna": "RA", "reggio calabria": "RC",
    "reggio emilia": "RE", "rieti": "RI", "rimini": "RN", "roma": "RM",
    "rovigo": "RO", "salerno": "SA", "sassari": "SS", "savona": "SV",
    "siena": "SI", "siracusa": "SR", "sondrio": "SO", "sud sardegna": "SU",
    "taranto": "TA", "teramo": "TE", "terni": "TR", "torino": "TO",
    "trapani": "TP", "trento": "TN", "treviso": "TV", "trieste": "TS",
    "udine": "UD", "varese": "VA", "venezia": "VE", "verbania": "VB",
    "vercelli": "VC", "verona": "VR", "vibo valentia": "VV", "vicenza": "VI",
    "viterbo": "VT",
}


def _normalize_2l(val: str | None, mapping: dict) -> tuple[str | None, bool]:
    if not val:
        return None, True
    v = val.strip()
    if len(v) <= 2:
        return v.upper(), True
    mapped = mapping.get(v.lower())
    if mapped:
        return mapped, True
    return v, False


def _get_val(row: dict, cfg: dict) -> str | None:
    parts = []
    for entry in cfg.get('entries', []):
        val = row.get(entry.get('col', ''), '').strip()
        if val:
            parts.append((entry.get('incipit') or '') + val)
    result = ''.join(parts)
    return result.upper() if result else None


def _load_xlsx_raw(content: bytes) -> list[list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    raw = []
    for row in ws.iter_rows(values_only=True):
        raw.append([str(v).strip() if v is not None else "" for v in row])
    wb.close()
    return raw


def _parse_xlsx_with_header(content: bytes, header_row: int) -> tuple[list[str], list[dict]]:
    raw = _load_xlsx_raw(content)
    if not raw or header_row >= len(raw):
        raise HTTPException(status_code=400, detail="Riga header non valida")
    headers = raw[header_row]
    while headers and not headers[-1]:
        headers.pop()
    rows = []
    for row in raw[header_row + 1:]:
        if not any(v for v in row):
            continue
        rows.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))})
    return headers, rows


def _parse_csv(content: bytes) -> tuple[list[str], list[dict]]:
    text = None
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except Exception:
            continue
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows


def _snap(obj, fields: list[str]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def _snap_serializable(snap: dict) -> dict:
    """Convert UUID values to strings for JSON serialization."""
    result = {}
    for k, v in snap.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        else:
            result[k] = v
    return result


@router.post("/preview")
async def preview(file: UploadFile = File(...), entity: str = "contatti"):
    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    fields = COMPANY_FIELDS if entity == "aziende" else CONTACT_FIELDS

    if ext == "xlsx":
        raw = _load_xlsx_raw(content)
        if not raw:
            raise HTTPException(status_code=400, detail="File Excel vuoto")
        return {
            "type": "xlsx",
            "raw_rows": raw,
            "total_rows": len(raw),
            "available_fields": fields,
        }
    elif ext in ("csv", "txt"):
        headers, rows = _parse_csv(content)
        return {
            "type": "csv",
            "columns": headers,
            "preview_rows": rows[:5],
            "total_rows": len(rows),
            "available_fields": fields,
        }
    else:
        raise HTTPException(status_code=400, detail="Formato non supportato. Usa CSV o XLSX.")


@router.post("/preview-xlsx")
async def preview_xlsx(file: UploadFile = File(...), header_row: int = 0):
    content = await file.read()
    headers, rows = _parse_xlsx_with_header(content, header_row)
    return {
        "columns": headers,
        "preview_rows": rows[:5],
        "total_rows": len(rows),
    }


@router.post("/contacts/run")
async def run_contacts(
    file: UploadFile = File(...),
    mapping: str = Form(""),
    dry_run: bool = Form(True),
    header_row: int = Form(0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    try:
        col_map: dict = json.loads(mapping) if mapping else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Mapping non valido")

    nome_cfg = col_map.get('nome', {})
    if not [e for e in nome_cfg.get('entries', []) if e.get('col')]:
        raise HTTPException(status_code=400, detail="Devi mappare almeno il campo 'nome'")
    company_cfg = col_map.get('company', {})
    if not [e for e in company_cfg.get('entries', []) if e.get('col')]:
        raise HTTPException(status_code=400, detail="Devi mappare il campo 'Azienda'")

    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext == "xlsx":
        _, rows = _parse_xlsx_with_header(content, header_row)
    else:
        _, rows = _parse_csv(content)

    note_entries_cfg = col_map.get('note_records', [])
    created, updated, skipped = [], [], []
    created_objects: list[Contact] = []
    updated_snapshots: list[dict] = []
    note_objects: list[Note] = []

    for i, row in enumerate(rows):
        line = i + 2

        nome = _get_val(row, col_map.get('nome', {}))
        if not nome:
            skipped.append({"riga": line, "motivo": "Nome vuoto"})
            continue

        company_name = _get_val(row, col_map.get('company', {}))
        company = None
        if company_name:
            company = db.query(Company).filter(Company.ragione_sociale.ilike(company_name)).first()
            if not company:
                skipped.append({"riga": line, "nome": nome, "motivo": "Azienda non trovata"})
                continue

        email = _get_val(row, col_map.get('email', {}))
        ruolo = _get_val(row, col_map.get('ruolo', {}))
        telefono = _get_val(row, col_map.get('telefono', {}))
        note = _get_val(row, col_map.get('note', {}))
        storico_contatti = _get_val(row, col_map.get('storico_contatti', {}))

        existing = None
        if email:
            existing = db.query(Contact).filter(Contact.email == email).first()
        if not existing and company:
            existing = db.query(Contact).filter(
                Contact.company_id == company.id,
                Contact.nome.ilike(nome),
            ).first()

        if existing:
            before = _snap_serializable(_snap(existing, _CONTACT_SNAP_FIELDS))
            if not dry_run:
                existing.nome = nome
                if ruolo: existing.ruolo = ruolo
                if telefono: existing.telefono = telefono
                if storico_contatti: existing.storico_contatti = _append_storico(existing.storico_contatti, storico_contatti)
                if company: existing.company_id = company.id
                existing.created_by = current_user.nome
                after = _snap_serializable(_snap(existing, _CONTACT_SNAP_FIELDS))
                updated_snapshots.append({
                    "id": str(existing.id),
                    "nome": nome,
                    "before": before,
                    "after": after,
                })
                if note and company:
                    n = Note(company_id=company.id, contact_id=existing.id, testo=note, pinned=False, created_by=current_user.nome)
                    db.add(n)
                    note_objects.append(n)
                _collect_notes(db, note_entries_cfg, row, existing.id, company, current_user.nome, note_objects)
            updated.append({"riga": line, "nome": nome, "email": email})
        else:
            if not dry_run:
                contact = Contact(
                    nome=nome, email=email, ruolo=ruolo, telefono=telefono,
                    storico_contatti=storico_contatti,
                    company_id=company.id if company else None,
                    created_by=current_user.nome,
                )
                db.add(contact)
                created_objects.append(contact)
                if note and company:
                    n = Note(company_id=company.id, contact_id=contact.id, testo=note, pinned=False, created_by=current_user.nome)
                    db.add(n)
                    note_objects.append(n)
                _collect_notes(db, note_entries_cfg, row, contact.id, company, current_user.nome, note_objects)
            created.append({"riga": line, "nome": nome, "email": email})

    if not dry_run:
        db.flush()
        log = ImportLog(
            tipo="contatti",
            created_by=current_user.nome,
            creati=len(created),
            aggiornati=len(updated),
            saltati=len(skipped),
            dettaglio_saltati=skipped,
            created_ids=[str(c.id) for c in created_objects],
            updated_snapshots=updated_snapshots,
            note_ids=[str(n.id) for n in note_objects],
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        import_log_id = str(log.id)
    else:
        import_log_id = None

    return {
        "dry_run": dry_run,
        "import_log_id": import_log_id,
        "totale_righe": len(rows),
        "creati": len(created),
        "aggiornati": len(updated),
        "saltati": len(skipped),
        "dettaglio_creati": created,
        "dettaglio_aggiornati": updated,
        "dettaglio_saltati": skipped,
    }


@router.post("/companies/run")
async def run_companies(
    file: UploadFile = File(...),
    mapping: str = Form(""),
    dry_run: bool = Form(True),
    header_row: int = Form(0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    try:
        col_map: dict = json.loads(mapping) if mapping else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Mapping non valido")

    rs_cfg = col_map.get('ragione_sociale', {})
    if not [e for e in rs_cfg.get('entries', []) if e.get('col')]:
        raise HTTPException(status_code=400, detail="Devi mappare il campo 'Ragione sociale'")

    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext == "xlsx":
        _, rows = _parse_xlsx_with_header(content, header_row)
    else:
        _, rows = _parse_csv(content)

    created, updated, skipped = [], [], []
    created_objects: list[Company] = []
    updated_snapshots: list[dict] = []
    note_objects: list[Note] = []

    for i, row in enumerate(rows):
        line = i + 2

        ragione_sociale = _get_val(row, col_map.get('ragione_sociale', {}))
        if not ragione_sociale:
            skipped.append({"riga": line, "motivo": "Ragione sociale vuota"})
            continue

        partita_iva = _get_val(row, col_map.get('partita_iva', {}))
        indirizzo = _get_val(row, col_map.get('indirizzo', {}))
        citta = _get_val(row, col_map.get('citta', {}))
        cap = _get_val(row, col_map.get('cap', {}))
        provincia, prov_ok = _normalize_2l(_get_val(row, col_map.get('provincia', {})), _PROVINCIA_MAP)
        paese, paese_ok = _normalize_2l(_get_val(row, col_map.get('paese', {})), _PAESE_MAP)

        if not prov_ok:
            skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": f"Provincia non riconosciuta: '{provincia}'"})
            continue
        if not paese_ok:
            skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": f"Paese non riconosciuto: '{paese}'"})
            continue

        telefono = _get_val(row, col_map.get('telefono', {}))
        email = _get_val(row, col_map.get('email', {}))
        tipo_attivita = _get_val(row, col_map.get('tipo_attivita', {}))
        storico_contatti = _get_val(row, col_map.get('storico_contatti', {}))
        nota = _get_val(row, col_map.get('nota', {}))
        nota_pinned = col_map.get('nota_pinned', False)

        fields_nuovo = {
            "ragione_sociale": ragione_sociale,
            "partita_iva": partita_iva,
            "indirizzo": indirizzo,
            "citta": citta,
            "cap": cap,
            "provincia": provincia,
            "paese": paese,
            "telefono": telefono,
            "email": email,
            "tipo_attivita": tipo_attivita,
            "storico_contatti": storico_contatti,
        }

        existing = None
        if partita_iva:
            existing = db.query(Company).filter(Company.partita_iva == partita_iva).first()
        if not existing:
            existing = db.query(Company).filter(Company.ragione_sociale.ilike(ragione_sociale)).first()

        if existing:
            storico_merged = _append_storico(existing.storico_contatti, storico_contatti) if storico_contatti else existing.storico_contatti
            fields_attuale = {
                "ragione_sociale": existing.ragione_sociale,
                "partita_iva": existing.partita_iva,
                "indirizzo": existing.indirizzo,
                "citta": existing.citta,
                "cap": existing.cap,
                "provincia": existing.provincia,
                "paese": existing.paese,
                "telefono": existing.telefono,
                "email": existing.email,
                "tipo_attivita": existing.tipo_attivita,
                "storico_contatti": existing.storico_contatti,
            }
            fields_nuovo["storico_contatti"] = storico_merged
            has_changes = fields_attuale != fields_nuovo or bool(nota)
            if not has_changes:
                skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": "Nessuna modifica rispetto al record attuale"})
                continue
            if not dry_run:
                before = _snap(existing, _COMPANY_SNAP_FIELDS)
                existing.ragione_sociale = ragione_sociale
                if partita_iva: existing.partita_iva = partita_iva
                if indirizzo: existing.indirizzo = indirizzo
                if citta: existing.citta = citta
                if cap: existing.cap = cap
                if provincia: existing.provincia = provincia
                if paese: existing.paese = paese
                if telefono: existing.telefono = telefono
                if email: existing.email = email
                if tipo_attivita: existing.tipo_attivita = tipo_attivita
                if storico_contatti: existing.storico_contatti = storico_merged
                existing.created_by = current_user.nome
                after = _snap(existing, _COMPANY_SNAP_FIELDS)
                updated_snapshots.append({
                    "id": str(existing.id),
                    "ragione_sociale": ragione_sociale,
                    "before": before,
                    "after": after,
                })
                if nota:
                    n = Note(company_id=existing.id, testo=nota, pinned=nota_pinned, created_by=current_user.nome)
                    db.add(n)
                    note_objects.append(n)
            updated.append({"riga": line, "attuale": fields_attuale, "nuovo": fields_nuovo})
        else:
            if not dry_run:
                company = Company(
                    ragione_sociale=ragione_sociale,
                    partita_iva=partita_iva,
                    indirizzo=indirizzo,
                    citta=citta,
                    cap=cap,
                    provincia=provincia,
                    paese=paese,
                    telefono=telefono,
                    email=email,
                    tipo_attivita=tipo_attivita,
                    storico_contatti=storico_contatti,
                    status=CompanyStatus.prospect,
                    origin=CompanyOrigin.crm_manual,
                    created_by=current_user.nome,
                )
                db.add(company)
                created_objects.append(company)
                if nota:
                    n = Note(company_id=company.id, testo=nota, pinned=nota_pinned, created_by=current_user.nome)
                    db.add(n)
                    note_objects.append(n)
            created.append({"riga": line, **fields_nuovo})

    if not dry_run:
        db.flush()
        log = ImportLog(
            tipo="aziende",
            created_by=current_user.nome,
            creati=len(created),
            aggiornati=len(updated),
            saltati=len(skipped),
            dettaglio_saltati=skipped,
            created_ids=[str(c.id) for c in created_objects],
            updated_snapshots=updated_snapshots,
            note_ids=[str(n.id) for n in note_objects],
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        import_log_id = str(log.id)
    else:
        import_log_id = None

    return {
        "dry_run": dry_run,
        "import_log_id": import_log_id,
        "totale_righe": len(rows),
        "creati": len(created),
        "aggiornati": len(updated),
        "saltati": len(skipped),
        "dettaglio_creati": created,
        "dettaglio_aggiornati": updated,
        "dettaglio_saltati": skipped,
    }


@router.post("/companies/stream")
async def stream_companies(
    file: UploadFile = File(...),
    mapping: str = Form(""),
    header_row: int = Form(0),
    current_user=Depends(get_current_user),
):
    import json as _json
    try:
        col_map: dict = _json.loads(mapping) if mapping else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Mapping non valido")

    rs_cfg = col_map.get('ragione_sociale', {})
    if not [e for e in rs_cfg.get('entries', []) if e.get('col')]:
        raise HTTPException(status_code=400, detail="Devi mappare il campo 'Ragione sociale'")

    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext == "xlsx":
        _, rows = _parse_xlsx_with_header(content, header_row)
    else:
        _, rows = _parse_csv(content)

    username = current_user.nome

    def generate():
        from app.database import SessionLocal
        db = SessionLocal()
        created, updated, skipped = [], [], []
        created_objects, updated_snapshots, note_objects = [], [], []
        nota_pinned = col_map.get('nota_pinned', False)
        total = len(rows)

        try:
            for i, row in enumerate(rows):
                line = i + 2
                ragione_sociale = _get_val(row, col_map.get('ragione_sociale', {}))
                if not ragione_sociale:
                    skipped.append({"riga": line, "motivo": "Ragione sociale vuota"})
                else:
                    partita_iva = _get_val(row, col_map.get('partita_iva', {}))
                    indirizzo = _get_val(row, col_map.get('indirizzo', {}))
                    citta = _get_val(row, col_map.get('citta', {}))
                    cap = _get_val(row, col_map.get('cap', {}))
                    provincia, prov_ok = _normalize_2l(_get_val(row, col_map.get('provincia', {})), _PROVINCIA_MAP)
                    paese, paese_ok = _normalize_2l(_get_val(row, col_map.get('paese', {})), _PAESE_MAP)

                    if not prov_ok:
                        skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": f"Provincia non riconosciuta: '{provincia}'"})
                    elif not paese_ok:
                        skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": f"Paese non riconosciuto: '{paese}'"})
                    else:
                        telefono = _get_val(row, col_map.get('telefono', {}))
                        email = _get_val(row, col_map.get('email', {}))
                        tipo_attivita = _get_val(row, col_map.get('tipo_attivita', {}))
                        storico_contatti = _get_val(row, col_map.get('storico_contatti', {}))
                        nota = _get_val(row, col_map.get('nota', {}))
                        fields_nuovo = {
                            "ragione_sociale": ragione_sociale, "partita_iva": partita_iva,
                            "indirizzo": indirizzo, "citta": citta, "cap": cap,
                            "provincia": provincia, "paese": paese, "telefono": telefono,
                            "email": email, "tipo_attivita": tipo_attivita,
                            "storico_contatti": storico_contatti,
                        }
                        existing = None
                        if partita_iva:
                            existing = db.query(Company).filter(Company.partita_iva == partita_iva).first()
                        if not existing:
                            existing = db.query(Company).filter(Company.ragione_sociale.ilike(ragione_sociale)).first()

                        if existing:
                            storico_merged = _append_storico(existing.storico_contatti, storico_contatti) if storico_contatti else existing.storico_contatti
                            fields_attuale = {
                                "ragione_sociale": existing.ragione_sociale, "partita_iva": existing.partita_iva,
                                "indirizzo": existing.indirizzo, "citta": existing.citta, "cap": existing.cap,
                                "provincia": existing.provincia, "paese": existing.paese, "telefono": existing.telefono,
                                "email": existing.email, "tipo_attivita": existing.tipo_attivita,
                                "storico_contatti": existing.storico_contatti,
                            }
                            fields_nuovo["storico_contatti"] = storico_merged
                            has_changes = fields_attuale != fields_nuovo or bool(nota)
                            if not has_changes:
                                skipped.append({"riga": line, "ragione_sociale": ragione_sociale, "motivo": "Nessuna modifica"})
                            else:
                                before = _snap(existing, _COMPANY_SNAP_FIELDS)
                                existing.ragione_sociale = ragione_sociale
                                if partita_iva: existing.partita_iva = partita_iva
                                if indirizzo: existing.indirizzo = indirizzo
                                if citta: existing.citta = citta
                                if cap: existing.cap = cap
                                if provincia: existing.provincia = provincia
                                if paese: existing.paese = paese
                                if telefono: existing.telefono = telefono
                                if email: existing.email = email
                                if tipo_attivita: existing.tipo_attivita = tipo_attivita
                                if storico_contatti: existing.storico_contatti = storico_merged
                                existing.created_by = username
                                after = _snap(existing, _COMPANY_SNAP_FIELDS)
                                updated_snapshots.append({"id": str(existing.id), "ragione_sociale": ragione_sociale, "before": before, "after": after})
                                if nota:
                                    n = Note(company_id=existing.id, testo=nota, pinned=nota_pinned, created_by=username)
                                    db.add(n); note_objects.append(n)
                                updated.append({"riga": line, "attuale": fields_attuale, "nuovo": fields_nuovo})
                        else:
                            company = Company(
                                ragione_sociale=ragione_sociale, partita_iva=partita_iva,
                                indirizzo=indirizzo, citta=citta, cap=cap, provincia=provincia,
                                paese=paese, telefono=telefono, email=email,
                                tipo_attivita=tipo_attivita, storico_contatti=storico_contatti,
                                status=CompanyStatus.prospect, origin=CompanyOrigin.crm_manual,
                                created_by=username,
                            )
                            db.add(company); created_objects.append(company)
                            if nota:
                                n = Note(company_id=company.id, testo=nota, pinned=nota_pinned, created_by=username)
                                db.add(n); note_objects.append(n)
                            created.append({"riga": line, **fields_nuovo})

                if (i + 1) % 100 == 0 or i == total - 1:
                    pct = int((i + 1) / max(total, 1) * 90)
                    yield _json.dumps({"type": "progress", "pct": pct, "creati": len(created), "aggiornati": len(updated), "saltati": len(skipped)}) + "\n"

            db.flush()
            log = ImportLog(
                tipo="aziende", created_by=username,
                creati=len(created), aggiornati=len(updated), saltati=len(skipped),
                dettaglio_saltati=skipped,
                created_ids=[str(c.id) for c in created_objects],
                updated_snapshots=updated_snapshots,
                note_ids=[str(n.id) for n in note_objects],
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            yield _json.dumps({
                "type": "done",
                "import_log_id": str(log.id),
                "totale_righe": total,
                "creati": len(created), "aggiornati": len(updated), "saltati": len(skipped),
                "dettaglio_saltati": skipped,
            }) + "\n"
        except Exception as e:
            db.rollback()
            yield _json.dumps({"type": "error", "message": str(e)}) + "\n"
        finally:
            db.close()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


def _append_storico(existing: str | None, nuovo: str) -> str:
    if not existing:
        return nuovo
    parts = [p.strip() for p in existing.split('·')]
    if nuovo.strip() not in parts:
        parts.append(nuovo.strip())
    return ' · '.join(parts)


def _collect_notes(db, note_entries_cfg, row, contact_id, company, created_by, note_objects: list):
    if not note_entries_cfg or not company:
        return
    for entry in note_entries_cfg:
        text = _get_val(row, entry)
        if text:
            n = Note(
                company_id=company.id,
                contact_id=contact_id,
                testo=text,
                pinned=entry.get('pinned', False),
                created_by=created_by,
            )
            db.add(n)
            note_objects.append(n)


# ---------------------------------------------------------------------------
# SAP import — solo admin
# ---------------------------------------------------------------------------

@router.post("/sap", dependencies=[Depends(require_admin)])
async def import_sap(
    kna1: UploadFile = File(...),
    vbak: UploadFile = File(...),
    vbap: UploadFile = File(...),
    vbfa: UploadFile = File(...),
    mara: UploadFile = File(None),
    knvv: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    try:
        from app.services.sap_import_service import load_csv_bytes, load_mara_lookup, run_import_core
    except ImportError:
        raise HTTPException(status_code=500, detail="pandas non installato sul server")

    try:
        clienti   = load_csv_bytes(await kna1.read())
        docvend   = load_csv_bytes(await vbak.read())
        posizioni = load_csv_bytes(await vbap.read())
        flusso    = load_csv_bytes(await vbfa.read())
        mara_lookup = load_mara_lookup(await mara.read()) if mara else {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore lettura file: {e}")

    try:
        stats = run_import_core(clienti, docvend, posizioni, flusso, db, mara_lookup)
        if knvv:
            from app.services.sap_import_service import import_knvv
            knvv_stats = import_knvv(await knvv.read(), db)
            stats["knvv"] = knvv_stats
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore import: {e}")

    return {"ok": True, "stats": stats}


@router.post("/sap/stream", dependencies=[Depends(require_admin)])
async def import_sap_stream(
    kna1: UploadFile = File(...),
    vbak: UploadFile = File(...),
    vbap: UploadFile = File(...),
    vbfa: UploadFile = File(...),
    mara: UploadFile = File(None),
    knvv: UploadFile = File(None),
):
    try:
        import pandas as _pd; del _pd  # check pandas is available
    except ImportError:
        raise HTTPException(status_code=500, detail="pandas non installato sul server")

    try:
        # mara incluso nel dict così il generatore lo libera via .pop() subito dopo il lookup
        file_bytes = {
            "mara": await mara.read() if mara else b"",
            "knvv": await knvv.read() if knvv else b"",
            "kna1": await kna1.read(),
            "vbak": await vbak.read(),
            "vbfa": await vbfa.read(),
            "vbap": await vbap.read(),  # il più pesante, caricato per ultimo
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore lettura file: {e}")

    def generate():
        import gc
        from app.database import SessionLocal
        from app.services.sap_import_service import (
            load_csv_bytes, load_mara_lookup, _flusso_series,
            import_companies_stream, import_prodotti_stream,
            import_offerte_stream, import_ordini_stream, _build_posizioni_index,
        )
        db = SessionLocal()
        db.expire_on_commit = False
        try:
            yield json.dumps({"type": "progress", "pct": 5, "fase": "Lettura file CSV..."}) + "\n"

            # MARA: carica solo 2 colonne, poi libera i bytes subito
            mara_b = file_bytes.pop("mara")
            mara_lookup = load_mara_lookup(mara_b) if mara_b else {}
            del mara_b; gc.collect()

            _zero = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0, "total": 0, "processed": 0}

            # --- Companies 15% → 45% (KNA1: ~10 colonne su ~50) ---
            clienti = load_csv_bytes(file_bytes.pop("kna1"), file_type="kna1"); gc.collect()
            companies_stats = dict(_zero)
            for partial in import_companies_stream(clienti, db):
                pct = 15 + int((partial["processed"] / max(partial["total"], 1)) * 30)
                yield json.dumps({"type": "progress", "pct": pct, "fase": "Importo aziende...", "stats": {"companies": partial}}) + "\n"
                companies_stats = partial
            del clienti; gc.collect()

            # --- Split VBAK in offerte/ordini (6 colonne su ~40) ---
            docvend = load_csv_bytes(file_bytes.pop("vbak"), file_type="vbak"); gc.collect()
            offerte_df = docvend[docvend["Doc. vend."].str.startswith("5")].copy()
            ordini_df  = docvend[docvend["Doc. vend."].str.startswith("1")].copy()
            del docvend; gc.collect()

            # --- VBFA: solo 2 colonne, estrai dicts e libera ---
            flusso = load_csv_bytes(file_bytes.pop("vbfa"), file_type="vbfa"); gc.collect()
            prec = _flusso_series(flusso, "Doc.prec.", "Doc. prec.")
            succ = _flusso_series(flusso, "Doc. succ.", "Doc.succ.")
            offerte_vinte      = set(prec.unique())
            offerta_per_ordine = dict(zip(succ, prec))
            del flusso, prec, succ; gc.collect()

            yield json.dumps({
                "type": "progress", "pct": 44,
                "fase": f"Aziende ok — VBAK: {len(offerte_df)} offerte + {len(ordini_df)} ordini",
            }) + "\n"

            # --- VBAP: 9 colonne su ~40, caricato per ultimo quando tutto il resto è libero ---
            posizioni = load_csv_bytes(file_bytes.pop("vbap"), file_type="vbap"); gc.collect()

            # Prodotti 45% → 60%
            prodotti_stats = dict(_zero)
            for partial in import_prodotti_stream(posizioni, db):
                pct = 45 + int((partial["processed"] / max(partial["total"], 1)) * 15)
                yield json.dumps({"type": "progress", "pct": pct, "fase": "Importo prodotti...", "stats": {"companies": companies_stats, "prodotti": partial}}) + "\n"
                prodotti_stats = partial

            # Indice posizioni costruito una sola volta — poi il DF viene liberato
            posizioni_by_doc = _build_posizioni_index(posizioni)
            del posizioni; gc.collect()

            # Offerte 60% → 80%
            offerte_stats = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0, "total": len(offerte_df), "processed": len(offerte_df)}
            if len(offerte_df) > 0:
                for partial in import_offerte_stream(offerte_df, posizioni_by_doc, offerte_vinte, db, mara_lookup):
                    pct = 60 + int((partial["processed"] / max(partial["total"], 1)) * 20)
                    yield json.dumps({"type": "progress", "pct": pct, "fase": "Importo offerte...", "stats": {"companies": companies_stats, "prodotti": prodotti_stats, "offerte": partial}}) + "\n"
                    offerte_stats = partial
            else:
                yield json.dumps({"type": "progress", "pct": 80, "fase": "Offerte: 0 righe nel VBAK con prefisso 5xxxxx", "stats": {"companies": companies_stats, "prodotti": prodotti_stats, "offerte": offerte_stats}}) + "\n"
            del offerte_df; gc.collect()

            # Ordini 80% → 99%
            ordini_stats = dict(_zero)
            for partial in import_ordini_stream(ordini_df, posizioni_by_doc, offerta_per_ordine, db, mara_lookup):
                pct = 80 + int((partial["processed"] / max(partial["total"], 1)) * 19)
                yield json.dumps({"type": "progress", "pct": pct, "fase": "Importo ordini...", "stats": {"companies": companies_stats, "prodotti": prodotti_stats, "offerte": offerte_stats, "ordini": partial}}) + "\n"
                ordini_stats = partial
            del ordini_df, posizioni_by_doc; gc.collect()

            knvv_stats = {}
            knvv_b = file_bytes.pop("knvv", b"")
            if knvv_b:
                from app.services.sap_import_service import import_knvv
                yield json.dumps({"type": "progress", "pct": 99, "fase": "Importo agenti KNVV..."}) + "\n"
                knvv_stats = import_knvv(knvv_b, db)

            yield json.dumps({"type": "done", "pct": 100, "stats": {
                "companies": companies_stats,
                "prodotti":  prodotti_stats,
                "offerte":   offerte_stats,
                "ordini":    ordini_stats,
                "knvv":      knvv_stats,
            }}) + "\n"
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).exception(f"[SAP STREAM ERROR] {e}")
            db.rollback()
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
        finally:
            db.close()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
