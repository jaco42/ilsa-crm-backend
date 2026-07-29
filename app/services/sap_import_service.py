import io
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

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


def load_csv_bytes(content: bytes) -> pd.DataFrame:
    df = pd.read_csv(
        io.BytesIO(content), sep=SEP, dtype=str, encoding=ENCODING,
        skiprows=3, skipinitialspace=True, on_bad_lines="skip", quoting=3,
    )
    df.columns = df.columns.str.strip().str.strip("|")
    for col in df.columns:
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        if s.dtype == object or str(s.dtype) in ("string", "str"):
            df[col] = s.str.strip().str.strip("|")
    return df.fillna("")


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
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _flusso_series(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Restituisce la prima colonna trovata tra i candidati (gestisce varianti SAP con/senza spazio)."""
    for c in candidates:
        if c in df.columns:
            return df[c].str.strip()
    raise KeyError(
        f"Colonna VBFA non trovata (cercato: {candidates}). "
        f"Colonne disponibili: {list(df.columns)}"
    )


def load_mara_lookup(content: bytes) -> dict:
    """Ritorna {codice_sap: gr_merci} da MARA.CSV."""
    try:
        df = load_csv_bytes(content)
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


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def import_companies_stream(clienti: pd.DataFrame, db: Session):
    """Generator: yields partial stats every ~200 rows."""
    inserted = updated = identical = skipped = 0
    total = len(clienti)

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

                company = db.query(Company).filter(Company.sap_customer_id == codice_cliente).first()
                row_handled = False

                if not company:
                    secondary = db.query(CompanySapId).filter(CompanySapId.sap_customer_id == codice_cliente).first()
                    if secondary:
                        s = secondary.company
                        fill_fields = ["partita_iva", "indirizzo", "citta", "cap", "provincia", "paese", "tipo_attivita", "sap_created_at"]
                        if not s.telefono_override:
                            fill_fields.append("telefono")
                        if not s.email_override:
                            fill_fields.append("email")
                        changed_fields = [f for f in fill_fields if not getattr(s, f) and data.get(f)]
                        for f in changed_fields:
                            setattr(s, f, data[f])
                        if changed_fields:
                            updated += 1
                        else:
                            identical += 1
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

    for i, (_, row) in enumerate(deduped.iterrows()):
        codice = get(row, "Materiale")
        if not codice:
            continue
        nome = get(row, "Definizione") or codice
        prodotto = db.query(Prodotto).filter(Prodotto.codice_sap == codice).first()
        if prodotto:
            if prodotto.nome != nome:
                prodotto.nome = nome
                updated += 1
            else:
                identical += 1
        else:
            db.add(Prodotto(codice_sap=codice, nome=nome, attivo=True))
            inserted += 1

        if (i + 1) % 200 == 0 or i == total - 1:
            yield {"inserted": inserted, "updated": updated, "identical": identical, "skipped": 0,
                   "processed": i + 1, "total": total}

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

def import_offerte_stream(offerte: pd.DataFrame, posizioni: pd.DataFrame, offerte_vinte: set, db: Session, mara_lookup: dict = None):
    inserted = updated = identical = skipped = 0
    companies = _build_companies_lookup(db)
    total = len(offerte)

    for i, (_, row) in enumerate(offerte.iterrows()):
        sap_doc_id = get(row, "Doc. vend.")
        if not sap_doc_id:
            skipped += 1
        else:
            sap_customer_id = get(row, "Committ.")
            company = companies.get(sap_customer_id)
            if not company:
                skipped += 1
            else:
                stage = STAGE_VINTO if sap_doc_id in offerte_vinte else STAGE_OFFERTA
                data = {
                    "company_id": company.id,
                    "sap_document_id": sap_doc_id,
                    "stage": stage,
                    "valore_totale": parse_decimal(get(row, "Val.netto")),
                    "data_scadenza": parse_date(get(row, "Fine off.")),
                    "data_creazione_sap": parse_date(get(row, "Data cr.")),
                    "sap_creato_da": get(row, "Creato") or None,
                }

                opp = db.query(Opportunity).filter(Opportunity.sap_document_id == sap_doc_id).first()
                if opp:
                    any_changed = any(
                        _changed(opp, k, v)
                        for k, v in data.items() if v is not None and hasattr(opp, k)
                    )
                    if any_changed:
                        for k, v in data.items():
                            if v is not None:
                                setattr(opp, k, v)
                        updated += 1
                    else:
                        identical += 1
                else:
                    opp = Opportunity(**data)
                    db.add(opp)
                    db.flush()
                    inserted += 1

                db.query(OfferLineItem).filter(OfferLineItem.opportunity_id == opp.id).delete()
                for _, riga in posizioni[posizioni["Doc. vend."] == sap_doc_id].iterrows():
                    codice = get(riga, "Materiale")
                    db.add(OfferLineItem(
                        opportunity_id=opp.id,
                        codice_sap=codice or None,
                        descrizione_riga=get(riga, "Definizione") or None,
                        quantita=parse_decimal(get(riga, "Qtà ordine", "Qt? ordine", "Qt ordine")),
                        unita_misura=get(riga, "UM") or None,
                        prezzo_unitario=parse_decimal(get(riga, "Prz. netto")),
                        totale_riga=parse_decimal(get(riga, "Val.netto")),
                        gr_merci=(mara_lookup or {}).get(codice) or None,
                    ))

        if (i + 1) % 100 == 0 or i == total - 1:
            yield {"inserted": inserted, "updated": updated, "identical": identical, "skipped": skipped,
                   "processed": i + 1, "total": total}

    db.commit()
    log.info(f"Offerte:    {inserted} inserite  |  {updated} aggiornate  |  {identical} identiche  |  {skipped} saltate")


def import_offerte(offerte: pd.DataFrame, posizioni: pd.DataFrame, offerte_vinte: set, db: Session, mara_lookup: dict = None) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for partial in import_offerte_stream(offerte, posizioni, offerte_vinte, db, mara_lookup):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# Ordini
# ---------------------------------------------------------------------------

def import_ordini_stream(ordini: pd.DataFrame, posizioni: pd.DataFrame, offerta_per_ordine: dict, db: Session, mara_lookup: dict = None):
    inserted = updated = identical = skipped = 0
    companies = _build_companies_lookup(db)
    opportunities = {
        o.sap_document_id: o
        for o in db.query(Opportunity).filter(Opportunity.sap_document_id.isnot(None)).all()
    }
    total = len(ordini)

    for i, (_, row) in enumerate(ordini.iterrows()):
        sap_doc_id = get(row, "Doc. vend.")
        if not sap_doc_id:
            skipped += 1
        else:
            sap_customer_id = get(row, "Committ.")
            company = companies.get(sap_customer_id)
            if not company:
                skipped += 1
            else:
                sap_offerta_id = offerta_per_ordine.get(sap_doc_id)
                opportunity = opportunities.get(sap_offerta_id) if sap_offerta_id else None

                data = {
                    "company_id": company.id,
                    "opportunity_id": opportunity.id if opportunity else None,
                    "sap_document_id": sap_doc_id,
                    "valore_totale": parse_decimal(get(row, "Val.netto")),
                    "data_ordine": parse_date(get(row, "Data doc.")),
                    "data_creazione_sap": parse_date(get(row, "Data cr.")),
                    "sap_creato_da": get(row, "Creato") or None,
                }

                order = db.query(Order).filter(Order.sap_document_id == sap_doc_id).first()
                if order:
                    any_changed = any(
                        _changed(order, k, v)
                        for k, v in data.items() if v is not None and hasattr(order, k)
                    )
                    if any_changed:
                        for k, v in data.items():
                            if v is not None:
                                setattr(order, k, v)
                        updated += 1
                    else:
                        identical += 1
                else:
                    order = Order(**data)
                    db.add(order)
                    db.flush()
                    inserted += 1

                # Se l'offerta collegata esiste in DB ma è ancora "Offerta Mandata", aggiornala a vinta
                if opportunity and opportunity.stage == STAGE_OFFERTA:
                    opportunity.stage = STAGE_VINTO

                db.query(OrderLineItem).filter(OrderLineItem.order_id == order.id).delete()
                for _, riga in posizioni[posizioni["Doc. vend."] == sap_doc_id].iterrows():
                    codice = get(riga, "Materiale")
                    db.add(OrderLineItem(
                        order_id=order.id,
                        codice_sap=codice or None,
                        descrizione_riga=get(riga, "Definizione") or None,
                        quantita=parse_decimal(get(riga, "Qtà ordine", "Qt? ordine", "Qt ordine")),
                        unita_misura=get(riga, "UM") or None,
                        prezzo_unitario=parse_decimal(get(riga, "Prz. netto")),
                        totale_riga=parse_decimal(get(riga, "Val.netto")),
                        gr_merci=(mara_lookup or {}).get(codice) or None,
                    ))

        if (i + 1) % 100 == 0 or i == total - 1:
            yield {"inserted": inserted, "updated": updated, "identical": identical, "skipped": skipped,
                   "processed": i + 1, "total": total}

    db.commit()
    log.info(f"Ordini:     {inserted} inseriti  |  {updated} aggiornati  |  {identical} identici  |  {skipped} saltati")


def import_ordini(ordini: pd.DataFrame, posizioni: pd.DataFrame, offerta_per_ordine: dict, db: Session, mara_lookup: dict = None) -> dict:
    result = {"inserted": 0, "updated": 0, "identical": 0, "skipped": 0}
    for partial in import_ordini_stream(ordini, posizioni, offerta_per_ordine, db, mara_lookup):
        result = partial
    return {k: result[k] for k in ["inserted", "updated", "identical", "skipped"]}


# ---------------------------------------------------------------------------
# run_import_core — used by non-streaming endpoint
# ---------------------------------------------------------------------------

def run_import_core(clienti: pd.DataFrame, docvend: pd.DataFrame, posizioni: pd.DataFrame, flusso: pd.DataFrame, db: Session, mara_lookup: dict = None) -> dict:
    offerte = docvend[docvend["Doc. vend."].str.startswith("5")].copy()
    ordini  = docvend[docvend["Doc. vend."].str.startswith("1")].copy()
    prec = _flusso_series(flusso, "Doc.prec.", "Doc. prec.")
    succ = _flusso_series(flusso, "Doc. succ.", "Doc.succ.")
    offerte_vinte      = set(prec.unique())
    offerta_per_ordine = dict(zip(succ, prec))

    log.info(f"Avvio import: {len(clienti)} clienti, {len(offerte)} offerte, {len(ordini)} ordini, {len(posizioni)} posizioni, {len(mara_lookup or {})} materiali MARA")

    return {
        "companies": import_companies(clienti, db),
        "prodotti":  import_prodotti(posizioni, db),
        "offerte":   import_offerte(offerte, posizioni, offerte_vinte, db, mara_lookup),
        "ordini":    import_ordini(ordini, posizioni, offerta_per_ordine, db, mara_lookup),
    }
