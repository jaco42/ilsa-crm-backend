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

TIPI_OFFERTA = {"ZOF0"}
TIPI_ORDINE  = {"ZOI0", "ZOC0", "ZOE0", "ZRII", "ZRIC", "ZRIE", "ZRAS", "ZSOG", "ZAMM", "ZFIN", "ZVIN"}
TIPI_SKIP    = {"ZACC"}
TIPI_CONTRIBUISCE = {"ZOI0", "ZOC0", "ZOE0", "ZRII", "ZRIC", "ZRIE", "ZRAS"}

_SFRIDI_KW = ("sfridi", "fridi", "rottami", "rottame")
_ROYALTY_KW = ("importo dovuto da contratto",)

def _is_sfridi(descrizione: str) -> bool:
    if not descrizione:
        return False
    d = descrizione.lower()
    return any(kw in d for kw in _SFRIDI_KW)

def _is_royalty(descrizione: str) -> bool:
    if not descrizione:
        return False
    d = descrizione.lower()
    return any(kw in d for kw in _ROYALTY_KW)
COMMITTENTI_NO_FATTURATO = {"1", "3865"}

NOTA_DA_TIPO = {
    "ZSOG": "Ord. sost. in garanzia",
    "ZFIN": "Invio conto fiera",
    "ZVIN": "Invio conto visione",
}

RF_DESC = {
    "01": "Consegna fissata troppo tardi",
    "02": "Qualità scadente",
    "03": "Prezzo eccessivo",
    "04": "Fornitore con servizio migliore",
    "05": "Garanzia",
    "10": "Richieste irragionevoli",
    "11": "Consegna sostitutiva",
    "50": "Operazione sospesa per chiarimenti",
}

# ---------------------------------------------------------------------------
# Gerarchia prodotti → L1 (gr_merci) / L2 (categoria)
# Fonte: listino Excel ILSA 2026 come master per L1.
# Articoli fuori listino classificati per prefisso gerarchia SAP.
# ---------------------------------------------------------------------------

# Gerarchie exact-match che finiscono in Complementi
# (forni linea secondaria e accessori forni venduti come complemento)
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
    """Restituisce (L1, L2) da un codice Gerarchia prodotti SAP.

    L1 segue la struttura del listino ILSA 2026:
      Refrigerazione, Cottura, Neutro, Complementi,
      Ricambi, Speciali, Self Service, Varie + Trasporti
    Cappe inglobate in Neutro (allineato al listino).
    """
    if not g:
        return None, None

    # --- Complementi exact (prima dei prefissi COPF generici) ---
    if g in _COMPLEMENTI_EXACT:
        return "Complementi", "Accessori forni"

    # --- Cottura ---
    if g.startswith("COPF") or g.startswith("COTT"):
        import re
        m = (re.match(r"COPF[A-Z]([A-Z]{3})\d+", g)
             or re.match(r"COTT_([A-Z]{3})\d+", g)
             or re.match(r"COSLC([A-Z]{3})\d+", g))
        l2 = _COTTURA_L2.get(m.group(1) if m else "", "Accessori cottura")
        return "Cottura", l2
    if g.startswith("VARIE_COTT"):
        return "Cottura", "Accessori cottura"
    if g.startswith("COSLCSAM"):
        return "Cottura", "Salamandre"

    # --- Refrigerazione ---
    if g.startswith("REFRG"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Refrigerazione", _REFRG_L2.get(key, "Refrigerazione altro")
    if g.startswith("PZ_NE"):
        return "Refrigerazione", "Tavoli pizza"

    # --- Neutro (include Cappe) ---
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

    # --- Ricambi Neutro (spostato da Neutro a Ricambi) ---
    if g.startswith("PSVEN_NEUT"):
        return "Ricambi", "Ricambi Neutro"

    # --- Complementi ---
    if g.startswith("LAVA_"):
        suffix = g.split("_")[-1] if "_" in g else ""
        return "Complementi", _LAVA_L2.get(suffix, "Lavaggio")
    if g.startswith("VARIE_COMM"):
        return "Complementi", "Fabbricatori ghiaccio"

    # --- Ricambi ---
    if g.startswith("PSVEN"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Ricambi", _PSVEN_L2.get(key, "Ricambi Generali")

    # --- Speciali ---
    if g.startswith("SPEC_"):
        parts = g.split("_")
        key = parts[1] if len(parts) > 1 else ""
        return "Speciali", _SPEC_L2.get(key, "Speciali")

    # --- Self Service ---
    if g.startswith("SELF_"):
        return "Self Service", "Self service"

    # --- Trasporti (ALTRO_GENE, non classificati) ---
    return "Trasporti", "Trasporti"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> pd.DataFrame:
    probe = path.read_bytes()
    lines = [l for l in probe.decode(ENCODING, errors="replace").split("\n") if l.strip()]
    probe_line = lines[3] if len(lines) > 3 else (lines[0] if lines else "")
    sep = "\t" if probe_line.count("\t") > probe_line.count("|") else SEP
    df = pd.read_csv(path, sep=sep, dtype=str, encoding=ENCODING, skiprows=3, skipinitialspace=True, on_bad_lines='skip', quoting=3)
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


def _nota_riga(rf: str) -> str | None:
    rf = rf.strip().lstrip("0") if rf else ""
    rf = rf.zfill(2) if rf else ""
    if not rf:
        return None
    desc = RF_DESC.get(rf, f"Codice {rf}")
    return f"Prodotto annullato: {desc}"


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

        tipo_doc = get(row, "TpDV")
        sap_customer_id = get(row, "Committ.")

        company = companies.get(sap_customer_id)
        if not company:
            log.warning(f"Offerta {sap_doc_id}: cliente '{sap_customer_id}' non trovato — skip")
            skipped += 1
            continue

        stage = STAGE_VINTO if sap_doc_id in offerte_vinte else STAGE_OFFERTA
        contribuisce = sap_customer_id not in COMMITTENTI_NO_FATTURATO

        data = {
            "company_id": company.id,
            "sap_document_id": sap_doc_id,
            "stage": stage,
            "tipo_doc": tipo_doc or None,
            "committente_sap": sap_customer_id or None,
            "nota": NOTA_DA_TIPO.get(tipo_doc) if tipo_doc else None,
            "contribuisce_fatturato": contribuisce,
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
            l1, l2 = _gerarchia_to_famiglia(get(riga, "Gerarchia prodotti"))
            val = parse_decimal(get(riga, "Val.netto"))
            if l1 is None:
                if not val or val == 0:
                    continue
                l1, l2 = "Non categorizzati", "Non categorizzati"
            db.add(OfferLineItem(
                opportunity_id=opp.id,
                codice_sap=codice or None,
                descrizione_riga=get(riga, "Definizione") or None,
                quantita=parse_decimal(get(riga, "Qtà ordine", "Qt? ordine", "Qt ordine")),
                unita_misura=get(riga, "UM") or None,
                prezzo_unitario=parse_decimal(get(riga, "Prz. netto")),
                totale_riga=parse_decimal(get(riga, "Val.netto")),
                categoria=l1,
                prodotto=l2,
                nota=_nota_riga(get(riga, "Rf")),
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

        tipo_doc = get(row, "TpDV")
        sap_customer_id = get(row, "Committ.")

        company = companies.get(sap_customer_id)
        if not company:
            log.warning(f"Ordine {sap_doc_id}: cliente '{sap_customer_id}' non trovato — skip")
            skipped += 1
            continue

        sap_offerta_id = offerta_per_ordine.get(sap_doc_id)
        opportunity = opportunities.get(sap_offerta_id) if sap_offerta_id else None
        contribuisce = tipo_doc in TIPI_CONTRIBUISCE and sap_customer_id not in COMMITTENTI_NO_FATTURATO

        data = {
            "company_id": company.id,
            "opportunity_id": opportunity.id if opportunity else None,
            "sap_document_id": sap_doc_id,
            "tipo_doc": tipo_doc or None,
            "committente_sap": sap_customer_id or None,
            "nota": NOTA_DA_TIPO.get(tipo_doc) if tipo_doc else None,
            "contribuisce_fatturato": contribuisce,
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

        righe_doc = posizioni[posizioni["Doc. vend."] == sap_doc_id]

        # ZAMM: importa solo sfridi e royalties, scarta tutto il resto
        if tipo_doc == "ZAMM":
            has_sfridi = any(_is_sfridi(get(r, "Definizione")) for _, r in righe_doc.iterrows())
            has_royalty = any(_is_royalty(get(r, "Definizione")) for _, r in righe_doc.iterrows())
            if not has_sfridi and not has_royalty:
                # Rimuovi l'ordine appena inserito/aggiornato e salta
                if order.id:
                    db.query(OrderLineItem).filter(OrderLineItem.order_id == order.id).delete()
                    db.delete(order)
                skipped += 1
                if inserted > 0:
                    inserted -= 1
                elif updated > 0:
                    updated -= 1
                continue
            # Sfridi e royalties contribuiscono al fatturato
            order.contribuisce_fatturato = True

        db.query(OrderLineItem).filter(OrderLineItem.order_id == order.id).delete()
        for _, riga in righe_doc.iterrows():
            codice = get(riga, "Materiale")
            if tipo_doc == "ZAMM" and _is_royalty(get(riga, "Definizione")):
                l1, l2 = "Royalties", "Royalties"
            elif tipo_doc == "ZAMM" and _is_sfridi(get(riga, "Definizione")):
                l1, l2 = "Vendita Sfridi", "Vendita Sfridi"
            elif tipo_doc == "ZRAS":
                l1, l2 = "Riparazioni", "Riparazioni"
            else:
                l1, l2 = _gerarchia_to_famiglia(get(riga, "Gerarchia prodotti"))
            val = parse_decimal(get(riga, "Val.netto"))
            if l1 is None:
                if not val or val == 0:
                    continue
                l1, l2 = "Non categorizzati", "Non categorizzati"
            db.add(OrderLineItem(
                order_id=order.id,
                codice_sap=codice or None,
                descrizione_riga=get(riga, "Definizione") or None,
                quantita=parse_decimal(get(riga, "Qtà ordine", "Qt? ordine", "Qt ordine")),
                unita_misura=get(riga, "UM") or None,
                prezzo_unitario=parse_decimal(get(riga, "Prz. netto")),
                totale_riga=parse_decimal(get(riga, "Val.netto")),
                categoria=l1,
                prodotto=l2,
                nota=_nota_riga(get(riga, "Rf")) or NOTA_DA_TIPO.get(tipo_doc),
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

    tipo_col = "TpDV" if "TpDV" in docvend.columns else None
    if tipo_col:
        docvend = docvend[~docvend[tipo_col].isin(TIPI_SKIP)]
        offerte = docvend[docvend[tipo_col].isin(TIPI_OFFERTA)].copy()
        ordini  = docvend[docvend[tipo_col].isin(TIPI_ORDINE)].copy()
    else:
        log.warning("Colonna TpDV non trovata — split per prefisso doc ID (fallback)")
        offerte = docvend[docvend["Doc. vend."].str.startswith("5")].copy()
        ordini  = docvend[docvend["Doc. vend."].str.startswith("1")].copy()
    def _col(df, *names):
        for n in names:
            if n in df.columns:
                return df[n].str.strip()
        raise KeyError(f"Colonna non trovata: {names}. Disponibili: {list(df.columns)}")

    prec = _col(flusso1, "Doc.prec.", "Doc. prec.")
    succ = _col(flusso1, "Doc. succ.", "Doc.succ.")
    offerte_vinte = set(prec.unique())
    offerta_per_ordine = dict(zip(succ, prec))

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
