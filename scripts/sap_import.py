#!/usr/bin/env python3
"""
SAP import script — legge i CSV SAP e aggiorna il DB CRM.
Idempotente: può essere rieseguito più volte senza creare duplicati.

Utilizzo manuale:
    python scripts/sap_import.py
    python scripts/sap_import.py --dir /percorso/cartella/csv

Cron (ogni notte alle 2:00):
    0 2 * * * cd /path/to/project && python scripts/sap_import.py

File attesi nella cartella:
    clienti.txt        — anagrafica clienti SAP
    doc_vend.txt       — documenti di vendita (offerte + ordini)
    posizioni.txt      — righe prodotto delle offerte
    flusso_ordini.txt  — link offerta → ordine (determina Chiuso Vinto)
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.company import Company, CompanyOrigin, CompanyStatus
from app.models.company_sap_ids import CompanySapId
from app.models.dedup import DeduplicaAlert
from app.models.offer_line_item import OfferLineItem
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.order_line_item import OrderLineItem
from app.models.prodotto import Prodotto
from app.services.dedup import find_and_handle_duplicate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

ENCODING = "latin-1"
SEP = "|"
STAGE_VINTO = "Chiuso Vinto"
STAGE_OFFERTA = "Offerta Mandata"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=SEP, dtype=str, encoding=ENCODING, skiprows=3, skipinitialspace=True, on_bad_lines='skip', quoting=3)
    df.columns = df.columns.str.strip().str.strip("|")
    for col in df.columns:
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        if s.dtype == object or str(s.dtype) in ("string", "str"):
            df[col] = s.str.strip().str.strip("|")
    return df.fillna("")


def get(row, *names: str) -> str:
    """Restituisce il primo valore non vuoto tra i nomi colonna dati."""
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


# ---------------------------------------------------------------------------
# Import clienti → companies
# ---------------------------------------------------------------------------

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


def import_companies(clienti: pd.DataFrame, db):
    inserted = updated = skipped = 0

    for _, row in clienti.iterrows():
        codice_cliente = get(row, "Cliente")
        if not codice_cliente:
            skipped += 1
            continue

        tipo = classify_customer_code(codice_cliente)
        if tipo in ("dest_merci", "skip"):
            skipped += 1
            continue

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

        # Cerca prima per sap_customer_id principale, poi nei codici secondari
        company = db.query(Company).filter(Company.sap_customer_id == codice_cliente).first()
        if not company:
            secondary = db.query(CompanySapId).filter(CompanySapId.sap_customer_id == codice_cliente).first()
            if secondary:
                # Codice assorbito da un merge: riempi solo i campi ancora vuoti sul survivor
                s = secondary.company
                fill_fields = ["partita_iva", "indirizzo", "citta", "cap", "provincia", "paese", "tipo_attivita", "sap_created_at"]
                if not s.telefono_override:
                    fill_fields.append("telefono")
                if not s.email_override:
                    fill_fields.append("email")
                changed = [f for f in fill_fields if not getattr(s, f) and data.get(f)]
                for f in changed:
                    setattr(s, f, data[f])
                if changed:
                    log.info(f"Arricchito '{s.ragione_sociale}' da {codice_cliente} ({ragione_sociale}): {changed}")
                    updated += 1
                else:
                    log.info(f"Skip '{ragione_sociale}' ({codice_cliente}): assorbita in '{s.ragione_sociale}', nessun campo nuovo")
                    skipped += 1
                continue
        if company:
            if company.telefono_override:
                data.pop("telefono", None)
            # Non retrocedere mai da cliente a prospect
            if company.status == CompanyStatus.cliente and data.get("status") == CompanyStatus.prospect:
                data.pop("status", None)
            for k, v in data.items():
                setattr(company, k, v)
            updated += 1
        else:
            handled, match = find_and_handle_duplicate(data, db)
            if handled:
                # merge automatica già eseguita sul lead esistente
                log.info(f"Auto-merge: '{data['ragione_sociale']}' → lead esistente")
                updated += 1
            else:
                new_company = Company(**data)
                db.add(new_company)
                db.flush()
                inserted += 1
                if match is not None:
                    # alert simile: crea la notifica per l'inbox
                    from app.services.dedup import score_match
                    reason, s_nome, s_via = score_match(match, new_company)
                    alert = DeduplicaAlert(
                        company_a_id=match.id,
                        company_b_id=new_company.id,
                        reason=reason or "alert_simile",
                        score_nome=s_nome,
                        score_via=s_via if s_via else None,
                    )
                    db.add(alert)
                    log.info(f"Alert dedup: '{data['ragione_sociale']}' simile a '{match.ragione_sociale}'")

    db.commit()
    log.info(f"Companies:  {inserted} inserite  |  {updated} aggiornate  |  {skipped} saltate")


# ---------------------------------------------------------------------------
# Import prodotti da posizioni
# ---------------------------------------------------------------------------

def import_prodotti(posizioni: pd.DataFrame, db):
    inserted = updated = 0

    for _, row in posizioni.drop_duplicates(subset=["Materiale"]).iterrows():
        codice = get(row, "Materiale")
        if not codice:
            continue

        nome = get(row, "Definizione") or codice

        prodotto = db.query(Prodotto).filter(Prodotto.codice_sap == codice).first()
        if prodotto:
            prodotto.nome = nome
            updated += 1
        else:
            db.add(Prodotto(codice_sap=codice, nome=nome, attivo=True))
            inserted += 1

    db.commit()
    log.info(f"Prodotti:   {inserted} inseriti  |  {updated} aggiornati")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _build_companies_lookup(db) -> dict:
    """Lookup sap_customer_id → Company, include codici SAP assorbiti da merge."""
    lookup = {
        c.sap_customer_id: c
        for c in db.query(Company).filter(Company.sap_customer_id.isnot(None)).all()
    }
    for sec in db.query(CompanySapId).all():
        if sec.sap_customer_id not in lookup and sec.company:
            lookup[sec.sap_customer_id] = sec.company
    return lookup


# Import offerte → opportunities + line items
# ---------------------------------------------------------------------------

def import_offerte(offerte: pd.DataFrame, posizioni: pd.DataFrame, offerte_vinte: set, db):
    inserted = updated = skipped = 0

    companies = _build_companies_lookup(db)

    for _, row in offerte.iterrows():
        sap_doc_id = get(row, "Doc. vend.")
        if not sap_doc_id:
            skipped += 1
            continue

        sap_customer_id = get(row, "Committ.")
        company = companies.get(sap_customer_id)
        if not company:
            log.warning(f"Offerta {sap_doc_id}: cliente '{sap_customer_id}' non trovato — skip")
            skipped += 1
            continue

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
            for k, v in data.items():
                if v is not None:
                    setattr(opp, k, v)
            if stage == STAGE_VINTO:
                opp.data_scadenza = None
            updated += 1
        else:
            opp = Opportunity(**data)
            if stage == STAGE_VINTO:
                opp.data_scadenza = None
            db.add(opp)
            db.flush()
            inserted += 1

        # Righe prodotto: cancella e reinserisci
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
            ))

    db.commit()
    log.info(f"Offerte:    {inserted} inserite  |  {updated} aggiornate  |  {skipped} saltate")


# ---------------------------------------------------------------------------
# Import ordini → orders + line items
# ---------------------------------------------------------------------------

def import_ordini(ordini: pd.DataFrame, posizioni: pd.DataFrame, offerta_per_ordine: dict, db):
    inserted = updated = skipped = 0

    companies = _build_companies_lookup(db)
    opportunities = {
        o.sap_document_id: o
        for o in db.query(Opportunity).filter(Opportunity.sap_document_id.isnot(None)).all()
    }

    for _, row in ordini.iterrows():
        sap_doc_id = get(row, "Doc. vend.")
        if not sap_doc_id:
            skipped += 1
            continue

        sap_customer_id = get(row, "Committ.")
        company = companies.get(sap_customer_id)
        if not company:
            log.warning(f"Ordine {sap_doc_id}: cliente '{sap_customer_id}' non trovato — skip")
            skipped += 1
            continue

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
            for k, v in data.items():
                setattr(order, k, v)
            updated += 1
        else:
            order = Order(**data)
            db.add(order)
            db.flush()
            inserted += 1

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
            ))

    db.commit()
    log.info(f"Ordini:     {inserted} inseriti  |  {updated} aggiornati  |  {skipped} saltati")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Importa CSV SAP nel CRM")
    parser.add_argument("--dir", default="./sap_exports", help="Cartella contenente i CSV SAP")
    args = parser.parse_args()

    export_dir = Path(args.dir)
    log.info(f"=== SAP Import avviato — cartella: {export_dir} ===")

    clienti   = load_csv(export_dir / "KNA1.CSV")
    docvend   = load_csv(export_dir / "VBAK.CSV")
    posizioni = load_csv(export_dir / "VBAP.CSV")
    flusso1   = load_csv(export_dir / "VBFA_off.CSV")

    offerte = docvend[docvend["Doc. vend."].str.startswith("5")].copy()
    ordini  = docvend[docvend["Doc. vend."].str.startswith("1")].copy()
    offerte_vinte = set(flusso1["Doc.prec."].str.strip().unique())
    offerta_per_ordine = dict(zip(flusso1["Doc. succ."].str.strip(), flusso1["Doc.prec."].str.strip()))

    log.info(f"Caricati: {len(clienti)} clienti, {len(offerte)} offerte, {len(ordini)} ordini, {len(posizioni)} posizioni")

    db = SessionLocal()
    try:
        import_companies(clienti, db)
        import_prodotti(posizioni, db)
        import_offerte(offerte, posizioni, offerte_vinte, db)
        import_ordini(ordini, posizioni, offerta_per_ordine, db)
    except Exception as e:
        db.rollback()
        log.error(f"Errore durante l'import: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

    log.info("=== SAP Import completato ===")


if __name__ == "__main__":
    main()
