import io
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models.agent_assignment import AgentAssignment
from app.models.company import Company, CompanyOrigin, CompanyStatus
from app.models.company_sap_ids import CompanySapId
from app.models.dedup import DeduplicaAlert
from app.models.offer_line_item import OfferLineItem
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.prodotto import Prodotto
from app.services.dedup import find_and_handle_duplicate, score_match

log = logging.getLogger(__name__)

SEP = "|"
ENCODING = "latin-1"
STAGE_VINTO = "Chiuso Vinto"
STAGE_OFFERTA = "Offerta Mandata"


# ---------------------------------------------------------------------------
# usecols — carica solo le colonne necessarie (-80÷97% RAM per DF)
# ---------------------------------------------------------------------------

_KNA1_COLS = {"Cliente", "Nome 1", "Nome 2", "Partita IVA 1", "Part.IVA", "Partita IVA",
              "Via", "Località", "Localit?", "CAP", "Rg", "Pse", "Telefono 1", "Data ap."}
_VBAK_COLS = {"Doc. vend.", "Committ.", "Val.netto", "Fine off.", "Data cr.", "Creato", "Data doc.", "OrgCm"}
_VBAP_COLS = {"Doc. vend.", "Materiale", "Definizione",
              "Qtà ordine", "Qt? ordine", "Qt ordine", "UM", "Prz. netto", "Val.netto",
              "Gerarchia prodotti"}
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

    return "Varie e Trasporti", "Varie e Trasporti"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(row, *names: str) -> str:
    for name in names:
        if name not in row.index:
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
        ))
    return index


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def import_companies_stream(clienti: pd.DataFrame, db: Session):
    inserted = updated = identical = skipped = 0
    total = len(clienti)

    # Pre-carica tutti i record esistenti in 2 query invece di N
    existing = {
        c.sap_customer_id: c
        for c in db.query(Company).filter(Company.sap_customer_id.isnot(None)).all()
    }
    secondaries = {}
    for sec in db.query(CompanySapId).all():
        if sec.company:
            secondaries[sec.sap_customer_id] = sec.company

    for i, (_, row) in enumerate(clienti.iterrows()):
        codice_cliente = get(row, "Cliente")
        if not codice_cliente:
            skipped += 1
        else:
            tipo = classify_customer_code(codice_cliente)
            if tipo in ("dest_merci", "skip"):
                skipped += 1
            else:
                nome1 = get(row, "Nome 1")
                nome2 = get(row, "Nome 2")
                ragione_sociale = f"{nome1} {nome2}".strip() if nome2 else nome1
                if not ragione_sociale:
                    ragione_sociale = f"Cliente SAP {codice_cliente}"

                piva = get(row, "Partita IVA 1", "Part.IVA", "Partita IVA") or None
                data = {
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

                company = existing.get(codice_cliente)
                row_handled = False

                if not company:
                    survivor = secondaries.get(codice_cliente)
                    if survivor:
                        fill_fields = ["partita_iva", "indirizzo", "citta", "cap", "provincia", "paese", "tipo_attivita", "sap_created_at"]
                        if not survivor.telefono_override:
                            fill_fields.append("telefono")
                        if not survivor.email_override:
                            fill_fields.append("email")
                        changed_fields = [f for f in fill_fields if not getattr(survivor, f) and data.get(f)]
                        for f in changed_fields:
                            setattr(survivor, f, data[f])
                        updated += 1 if changed_fields else 0
                        identical += 0 if changed_fields else 1
                        row_handled = True

                if not row_handled:
                    if company:
                        if company.telefono_override:
                            data.pop("telefono", None)
                        if company.status == CompanyStatus.cliente and data.get("status") == CompanyStatus.prospect:
                            data.pop("status", None)
                        any_changed = any(
                            _changed(company, k, v)
                            for k, v in data.items() if v is not None and hasattr(company, k)
                        )
                        if any_changed:
                            for k, v in data.items():
                                setattr(company, k, v)
                            updated += 1
                        else:
                            identical += 1
                    else:
                        handled, match = find_and_handle_duplicate(data, db)
                        if handled:
                            updated += 1
                        else:
                            new_company = Company(**data)
                            db.add(new_company)
                            db.flush()
                            existing[codice_cliente] = new_company
                            inserted += 1
                            if match is not None:
                                reason, s_nome, s_via = score_match(match, new_company)
                                db.add(DeduplicaAlert(
                                    company_a_id=match.id,
                                    company_b_id=new_company.id,
                                    reason=reason or "alert_simile",
                                    score_nome=s_nome,
                                    score_via=s_via if s_via else None,
                                ))

        if (i + 1) % 200 == 0 or i == total - 1:
            yield {"inserted": inserted, "updated": updated, "identical": identical, "skipped": skipped,
                   "processed": i + 1, "total": total}

    db.commit()
    log.info(f"Companies:  {inserted} inserite  |  {updated} aggiornate  |  {identical} identiche  |  {skipped} saltate")


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
    inserted = updated = skipped = 0
    companies = _build_companies_lookup(db)
    total = len(offerte)

    # Solo id — niente ORM completo, niente confronto campi
    existing_opps = {
        sap_id: opp_id
        for opp_id, sap_id in db.query(Opportunity.id, Opportunity.sap_document_id)
                                 .filter(Opportunity.sap_document_id.isnot(None)).all()
    }

    to_insert = []
    pending_bulk_updates = []
    processed_doc_ids = []
    _CHUNK = 300

    _records = offerte.to_dict('records')
    for i, row in enumerate(_records):
        sap_doc_id = row.get("Doc. vend.") or ""
        if not sap_doc_id:
            skipped += 1
        else:
            sap_customer_id = row.get("Committ.") or ""
            company = companies.get(sap_customer_id)
            if not company:
                skipped += 1
            else:
                stage = STAGE_VINTO if sap_doc_id in offerte_vinte else STAGE_OFFERTA
                data = {
                    "company_id": company.id,
                    "sap_document_id": sap_doc_id,
                    "stage": stage,
                    "org_cm": row.get("OrgCm") or None,
                    "valore_totale": parse_decimal(row.get("Val.netto") or ""),
                    "data_scadenza": None if stage == STAGE_VINTO else parse_date(row.get("Fine off.") or ""),
                    "data_creazione_sap": parse_date(row.get("Data cr.") or ""),
                    "sap_creato_da": row.get("Creato") or None,
                }

                opp_id = existing_opps.get(sap_doc_id)
                if opp_id:
                    pending_bulk_updates.append({"id": opp_id, **data})
                    updated += 1
                else:
                    to_insert.append(data)
                    inserted += 1
                processed_doc_ids.append(sap_doc_id)

        if len(pending_bulk_updates) >= _CHUNK:
            db.bulk_update_mappings(Opportunity, pending_bulk_updates)
            db.commit()
            pending_bulk_updates = []

        if (i + 1) % 200 == 0:
            yield {"inserted": inserted, "updated": updated, "identical": 0, "skipped": skipped,
                   "processed": i + 1, "total": total}

    log.info(f"[DEBUG] offerte loop done: {inserted} insert, {updated} update — avvio commit finale")
    if pending_bulk_updates:
        db.bulk_update_mappings(Opportunity, pending_bulk_updates)
    if to_insert:
        new_opps = [Opportunity(**d) for d in to_insert]
        db.add_all(new_opps)
        db.flush()
        for opp in new_opps:
            existing_opps[opp.sap_document_id] = opp.id
    if pending_bulk_updates or to_insert:
        db.commit()
    log.info(f"[DEBUG] commit opp ok — avvio chunk line items su {len(processed_doc_ids)} doc")

    _CHUNK = 300
    total_li = 0
    for ci in range(0, len(processed_doc_ids), _CHUNK):
        chunk_doc_ids = processed_doc_ids[ci:ci + _CHUNK]
        chunk_opp_ids = [existing_opps[d] for d in chunk_doc_ids if d in existing_opps]
        log.info(f"[DEBUG] chunk offerte {ci}–{ci+len(chunk_doc_ids)}: delete {len(chunk_opp_ids)} opp ids")
        if chunk_opp_ids:
            db.query(OfferLineItem).filter(
                OfferLineItem.opportunity_id.in_(chunk_opp_ids)
            ).delete(synchronize_session=False)
        chunk_li = []
        for doc_id in chunk_doc_ids:
            opp_id = existing_opps.get(doc_id)
            if not opp_id:
                continue
            for (codice, definizione, qty, um, prz, val, gerarchia) in posizioni_by_doc.get(doc_id, []):
                l1, l2 = _gerarchia_to_famiglia(gerarchia)
                chunk_li.append(OfferLineItem(
                    opportunity_id=opp_id,
                    codice_sap=codice or None,
                    descrizione_riga=definizione or None,
                    quantita=parse_decimal(qty),
                    unita_misura=um or None,
                    prezzo_unitario=parse_decimal(prz),
                    totale_riga=parse_decimal(val),
                    categoria=l1,
                    prodotto=l2,
                ))
        if chunk_li:
            db.add_all(chunk_li)
        db.commit()
        total_li += len(chunk_li)
        log.info(f"[DEBUG] chunk offerte {ci} ok: {len(chunk_li)} righe")
        yield {"inserted": inserted, "updated": updated, "identical": 0, "skipped": skipped,
               "processed": total, "total": total}

    log.info(f"Offerte:    {inserted} inserite  |  {updated} aggiornate  |  {skipped} saltate  |  {total_li} righe")


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
    inserted = updated = skipped = 0
    companies = _build_companies_lookup(db)
    total = len(ordini)

    # Solo id — niente ORM completo, niente confronto campi
    opp_id_by_doc = {
        sap_id: (opp_id, stage)
        for opp_id, sap_id, stage in db.query(Opportunity.id, Opportunity.sap_document_id, Opportunity.stage)
                                        .filter(Opportunity.sap_document_id.isnot(None)).all()
    }
    existing_orders = {
        sap_id: order_id
        for order_id, sap_id in db.query(Order.id, Order.sap_document_id)
                                   .filter(Order.sap_document_id.isnot(None)).all()
    }

    to_insert = []
    pending_bulk_updates = []
    processed_doc_ids = []
    opp_ids_to_win = []
    _CHUNK = 300

    _records = ordini.to_dict('records')
    for i, row in enumerate(_records):
        sap_doc_id = row.get("Doc. vend.") or ""
        if not sap_doc_id:
            skipped += 1
        else:
            sap_customer_id = row.get("Committ.") or ""
            company = companies.get(sap_customer_id)
            if not company:
                skipped += 1
            else:
                sap_offerta_id = offerta_per_ordine.get(sap_doc_id)
                opp_entry = opp_id_by_doc.get(sap_offerta_id) if sap_offerta_id else None
                opp_id = opp_entry[0] if opp_entry else None
                opp_stage = opp_entry[1] if opp_entry else None

                data = {
                    "company_id": company.id,
                    "opportunity_id": opp_id,
                    "sap_document_id": sap_doc_id,
                    "org_cm": row.get("OrgCm") or None,
                    "valore_totale": parse_decimal(row.get("Val.netto") or ""),
                    "data_ordine": parse_date(row.get("Data doc.") or ""),
                    "data_creazione_sap": parse_date(row.get("Data cr.") or ""),
                    "sap_creato_da": row.get("Creato") or None,
                }

                order_id = existing_orders.get(sap_doc_id)
                if order_id:
                    pending_bulk_updates.append({"id": order_id, **data})
                    updated += 1
                else:
                    to_insert.append(data)
                    inserted += 1
                processed_doc_ids.append(sap_doc_id)

                if opp_id and opp_stage == STAGE_OFFERTA:
                    opp_ids_to_win.append(opp_id)

        if len(pending_bulk_updates) >= _CHUNK:
            db.bulk_update_mappings(Order, pending_bulk_updates)
            db.commit()
            pending_bulk_updates = []

        if (i + 1) % 200 == 0:
            yield {"inserted": inserted, "updated": updated, "identical": 0, "skipped": skipped,
                   "processed": i + 1, "total": total}

    if pending_bulk_updates:
        db.bulk_update_mappings(Order, pending_bulk_updates)
    if to_insert:
        new_orders = [Order(**d) for d in to_insert]
        db.add_all(new_orders)
        db.flush()
        for order in new_orders:
            existing_orders[order.sap_document_id] = order.id
    if opp_ids_to_win:
        db.query(Opportunity).filter(Opportunity.id.in_(opp_ids_to_win)).update(
            {"stage": STAGE_VINTO}, synchronize_session=False
        )
    if pending_bulk_updates or to_insert or opp_ids_to_win:
        db.commit()

    # Line items in chunk da 300 doc: delete vecchi + insert nuovi + commit + yield
    _CHUNK = 300
    total_li = 0
    for ci in range(0, len(processed_doc_ids), _CHUNK):
        chunk_doc_ids = processed_doc_ids[ci:ci + _CHUNK]
        chunk_order_ids = [existing_orders[d] for d in chunk_doc_ids if d in existing_orders]
        if chunk_order_ids:
            db.query(OrderLineItem).filter(
                OrderLineItem.order_id.in_(chunk_order_ids)
            ).delete(synchronize_session=False)
        chunk_li = []
        for doc_id in chunk_doc_ids:
            order_id = existing_orders.get(doc_id)
            if not order_id:
                continue
            for (codice, definizione, qty, um, prz, val, gerarchia) in posizioni_by_doc.get(doc_id, []):
                l1, l2 = _gerarchia_to_famiglia(gerarchia)
                chunk_li.append(OrderLineItem(
                    order_id=order_id,
                    codice_sap=codice or None,
                    descrizione_riga=definizione or None,
                    quantita=parse_decimal(qty),
                    unita_misura=um or None,
                    prezzo_unitario=parse_decimal(prz),
                    totale_riga=parse_decimal(val),
                    categoria=l1,
                    prodotto=l2,
                ))
        if chunk_li:
            db.add_all(chunk_li)
        db.commit()
        total_li += len(chunk_li)
        yield {"inserted": inserted, "updated": updated, "identical": 0, "skipped": skipped,
               "processed": total, "total": total}

    log.info(f"Ordini:     {inserted} inseriti  |  {updated} aggiornati  |  {skipped} saltati  |  {total_li} righe")


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

    db.commit()
    return {"inserted": len(rows)}
